"""
Module Name: discover

Description:
The high level async, iterative discovering functionality of astrolabe/discover. Here is where we iteratively
profile nodes, compile async tasks, lookup node names, and parse children until complete.

License:
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import ipaddress
import traceback

from typing import Dict, List, Optional

from termcolor import colored

from astrolabe import database, profile_strategy, network, constants, logs, obfuscate, providers
from astrolabe.constants import CURRENT_RUN_TIMESTAMP
from astrolabe.profile_strategy import ProfileStrategy
from astrolabe.providers import ProviderInterface
from astrolabe.node import Node, NodeTransport, merge_node

# An internal cache which prevents astrolabe from re-profiling a Compute node of the same Application
# that has already been profiled on a different address. We may not want this "feature" going forward
# if we want to do more thorough/exhaustive profiling of every individual Compute node in a cluster.
child_cache: Dict[str, Dict[str, Node]] = {}  # {'provider_ref:service_name': {node_ref, Node}}

# We keep track of the "ancestors" of a node as it is profiled during the run.  This was we can check for cycles
#  and also "max-depth" of this discovery run.  We don't used "visited" pattern for cycle detection because
#  it is allowed for a node to be seen/visited multiple times during a run if it appears in different branches
#  of the discovery tree - this makes sure it is only a cycle if seen in the same branch.
discovery_ancestors: Dict[str, List[str]] = {}  # {node.address: List[ancestor_addresses]}


class DiscoveryException(Exception):
    def __init__(self, message=None):
        super().__init__(message)
        self.node: Optional[Node] = None
        self.ancestors: Optional[List[str]] = None


def _get_nodes_unprofiled(seeds: Dict[str, Node]) -> Dict[str, Node]:
    upn = database.get_nodes_unprofiled(constants.CURRENT_RUN_TIMESTAMP)
    if not constants.ARGS.seeds_only:
        return upn

    # respect --seeds-only
    # O(n^2)!
    seed_derived_nodes = {}
    for ref, node in upn.items():
        for seed in seeds.values():
            if node.address == seed.address:
                seed_derived_nodes[ref] = node
                continue
            if node.address in discovery_ancestors and seed.address in discovery_ancestors[node.address]:
                seed_derived_nodes[ref] = node
                continue
            continue
    logs.logger.debug("CLI arg --seeds-only=True: profiling seed derived nodes [%s]", ",".join(seed_derived_nodes))
    return seed_derived_nodes


# pylint:disable=too-many-locals
async def discover(seeds: Dict[str, Node], initial_ancestors: List[str]):  # noqa: C901, MC0001
    global discovery_ancestors  # pylint:disable=global-variable-not-assigned
    # SEED DATABASE
    for ref, node in seeds.items():
        logs.logger.info("Seeding database with node: %s", node.debug_id())
        # POPULATE ANCESTRY LIST
        discovery_ancestors[node.address] = initial_ancestors
        # REBUILD TREE NODES TO MERGE W/ INVENTORY
        saved_node = database.save_node(node)
        seeds[ref] = saved_node
    coroutines = []

    # PROFILE NODES
    unlocked_logging_sleep = 0.1
    unlocked_logging_max_sleep = 1

    while unprofiled_nodes := _get_nodes_unprofiled(seeds):
        unlocked_nodes = {n_id: node for n_id, node in unprofiled_nodes.items() if not node.profile_locked()}
        if not unlocked_nodes:
            pending = ",".join((f"{n.provider}:{n.address}" for n in unprofiled_nodes.values() if n.profile_locked()))
            logs.logger.info("Waiting for %d pending profile jobs to complete, sleeping %.1f (%s)",
                             len(unprofiled_nodes), unlocked_logging_sleep, pending)
            await asyncio.sleep(unlocked_logging_sleep)
            new_sleep = unlocked_logging_sleep + .1
            unlocked_logging_sleep = new_sleep if new_sleep < unlocked_logging_max_sleep else unlocked_logging_max_sleep
            continue
        unlocked_logging_sleep = 0.1

        logs.logger.debug("Found %d nodes to profile", len(unlocked_nodes))
        node_id, node = next(iter(unlocked_nodes.items()))
        if node.address in discovery_ancestors:
            ancestors = discovery_ancestors[node.address]
        else:
            ancestors = []
            discovery_ancestors[node.address] = ancestors

        depth = len(ancestors)
        logs.logger.debug("Profiling node %s at depth: %d", node_id, depth)

        async def discover_node_with_locking(node_id: str, node: Node, ancestors: List[str]):
            try:
                node.aquire_profile_lock()
                database.save_node(node)  # persists lock
                await _discover_node(node_id, node, ancestors)
                # await asyncio.wait_for(_discover_node(node_id, node, ancestors), constants.ARGS.timeout)
            finally:
                logs.logger.info("Profile complete for %s, releasing lock", node_id)
                node.set_profile_timestamp()
                node.clear_profile_lock()
                database.save_node(node)  # persists cleared lock
                # merge back the discovered node to seeds, for export processing
                node_ref = f"{node.provider}:{node.address}"
                if node_ref in seeds:
                    merge_node(seeds[node_ref], node)

        coro = asyncio.create_task(discover_node_with_locking(node_id, node, ancestors))
        coroutines.append(coro)
        await asyncio.sleep(0)  # explicitly hand off the loop
        await asyncio.sleep(0.1)  # actually give it a sec

    logs.logger.info("All nodes profiled, moving onto exception handling")
    # "HANDLE" EXCEPTIONS
    for coro in coroutines:
        try:
            await coro
        except DiscoveryException as disc_exc:
            exc = disc_exc.__cause__
            node = disc_exc.node
            ancestors = disc_exc.ancestors
            child_of = f"child of {ancestors[len(ancestors) - 1]}" if len(ancestors) > 0 else 'SEED'
            logs.logger.error("Exception %s occurred connecting to %s:%s child of `%s`",
                              exc, node.provider, node.address, child_of)
            traceback.print_tb(exc.__traceback__)
    logs.logger.info("Discovery/profile complete!")


async def _discover_node(node_ref: str, node: Node, ancestors: List[str]):
    global discovery_ancestors  # pylint:disable=global-variable-not-assigned
    if node.profile_complete(CURRENT_RUN_TIMESTAMP):
        logs.logger.info("Profile already completed for node: %s:%s (%s)",
                         node.provider, node.address, node.service_name)
        return node, {}

    depth = len(ancestors)
    print(constants.ARGS.disable_providers)
    if node.provider in constants.ARGS.disable_providers:
        logs.logger.info("Skipping discovery for node: %s due to disabled provider: %s", node.debug_id(), node.provider)
        return node, {}

    provider = providers.get_provider_by_ref(node.provider)
    try:
        logs.logger.info("Discovery initiated for node: %s", node.debug_id())
        profiled_children = await _discovery_algo(node_ref, node, ancestors, provider, depth)
        logs.logger.info("Discovered %d children for node %s (%s): %s", len(profiled_children), node.debug_id(),
                         node.service_name, ",".join([f"{n.node_type.value}:{n.debug_id()}"
                                                      for n in profiled_children.values()]))
        # if we have inventoried this node already, use that!
        for ref, child in profiled_children.items():
            inventory_node = database.get_node_by_address(child.address)
            if inventory_node:
                merge_node(inventory_node, child)
                database.save_node(inventory_node)
                profiled_children[ref] = inventory_node
            else:
                database.save_node(child)

            discovery_ancestors[child.address] = ancestors + [node.address]
            database.connect_nodes(node, profiled_children[ref])
    except (providers.TimeoutException, asyncio.TimeoutError):
        logs.logger.debug("TIMEOUT attempting to connect to %s with address: %s", node_ref, node.address)
        logs.logger.debug({**vars(node), 'profile_strategy': node.profile_strategy_name}, 'yellow')
        node.errors['TIMEOUT'] = True
    except Exception as exc:
        dexc = DiscoveryException(exc)
        dexc.node = node
        dexc.ancestors = ancestors
        raise dexc from exc


#  pylint:disable=too-many-return-statements
async def _discovery_algo(node_ref: str, node: Node, ancestors: List[str], provider: ProviderInterface, depth: int)\
        -> Dict[str, Node]:  # children
    # SKIP PROTOCOL MUX
    if network.skip_protocol_mux(node.protocol_mux):
        logs.logger.debug("Not opening connection: skip protocol mux (%s)", node.protocol_mux)
        node.errors['CONNECT_SKIPPED'] = True
        return {}

    # SKIP ADDRESS
    if node.address and network.skip_address(node.address):
        logs.logger.debug("Not opening connection: skip address (%s)", node.address)
        node.errors['CONNECT_SKIPPED'] = True
        return {}

    # OPEN CONNECTION
    logs.logger.debug("Opening connection: %s", node.address)
    conn = await asyncio.wait_for(provider.open_connection(node.address), constants.ARGS.connection_timeout)

    # RUN SIDECAR
    if constants.ARGS.skip_sidecar:
        logs.logger.debug("Skipping sidecar for address %s due to --skip-sidecar CLI arg ", node.address)
    else:
        logs.logger.debug("Running sidecar for address %s", node.address)
        await asyncio.wait_for(provider.sidecar(node.address, conn), constants.ARGS.timeout)

    # LOOKUP SERVICE NAME
    await asyncio.wait_for(_lookup_service_name(node, provider, conn), constants.ARGS.timeout)
    database.save_node(node)  # This persists the "service name" (Application)

    # SKIP SERVICE NAME
    if node.service_name and network.skip_service_name(node.service_name):
        logs.logger.debug("Not profiling: skip service name (%s)", node.service_name)
        node.errors['PROFILE_SKIPPED'] = True
        return {}

    # DETECT CYCLES
    if node.service_name and node.service_name in ancestors:
        node.errors['CYCLE'] = True
        return {}

    # MAX DEPTH
    if len(ancestors) > constants.ARGS.max_depth - 1:
        logs.logger.debug("Reached --max-depth of %d at depth: %d", constants.ARGS.max_depth, depth)
        return {}

    # DO NOT PROFILE NODE w/ ERRORS
    if bool(node.errors):
        logs.logger.debug("Not profiling service %s(%s) due to accrued errors: (%s)",
                          node.service_name, node.address, node.errors)
        node.errors['PROFILE_SKIPPED'] = True
        return {}

    # PROFILE
    return await _profile_node(node, node_ref, conn)


async def _lookup_service_name(node: Node, provider: providers.ProviderInterface,
                               connection: type) -> None:
    # ADDRESS REQUIRED
    if not node.address:
        logs.logger.warning("Node name lookup required with no address!")
        node.warnings['NAME_LOOKUP_FAILED'] = True
        return

    # SERVICE NAME FROM INVENTORYING
    if node.service_name:
        logs.logger.debug("Using pre-profiled/cached service name %s for address: %s)", node.service_name, node.address)
        return

    # LOOKUP SERVICE NAME
    logs.logger.debug(f"Getting service name for address %s from provider {provider.ref()}", node.address)
    service_name = await provider.lookup_name(node.address, connection)

    # CHECK NOT NONE
    if not service_name:
        logs.logger.debug("Name discovery failed for address %s", node.address)
        node.warnings['NAME_LOOKUP_FAILED'] = True
        return

    # REWRITE/OBFUSCATE
    logs.logger.debug("Discovered name: %s for address %s", service_name, node.address)
    service_name = network.rewrite_service_name(service_name, node)
    if constants.ARGS.obfuscate:
        service_name = obfuscate.obfuscate_service_name(service_name)

    # WRITE/CACHE
    node.service_name = service_name


# pylint:disable=too-many-locals
async def _profile_node(node: Node, node_ref: str, connection: type) -> Dict[str, Node]:  # noqa: C901, MC0001
    provider_ref = node.provider
    service_name = node.service_name

    # COMPILE PROFILE STRATEGIES
    tasks = []
    profile_strategies: List[ProfileStrategy] = []
    for pfs in profile_strategy.profile_strategies:
        if provider_ref not in pfs.providers:
            continue
        if pfs.protocol.ref in constants.ARGS.skip_protocols:
            continue
        if pfs.filter_service_name(service_name):
            continue
        profile_strategies.append(pfs)
    tasks.append(asyncio.wait_for(
        providers.get_provider_by_ref(provider_ref).profile(node, profile_strategies, connection),
        timeout=constants.ARGS.timeout
    ))

    # COMPILE USER DEFINED HINTS
    for hint in [hint for hint in network.hints(service_name)
                 if hint.instance_provider not in constants.ARGS.disable_providers]:
        hint_provider = providers.get_provider_by_ref(hint.instance_provider)
        tasks.append(asyncio.wait_for(hint_provider.take_a_hint(hint), timeout=constants.ARGS.timeout))

    # PROFILE!
    logs.logger.debug(f"Profiling provider: '{provider_ref}' for %s", node_ref)

    # HANDLE EXCEPTIONS
    profile_results = await asyncio.gather(*tasks, return_exceptions=True)

    # HANDLE EXCEPTIONS
    profile_exceptions = [e for e in profile_results if isinstance(e, Exception)]
    if profile_exceptions:
        if isinstance(profile_exceptions[0], asyncio.TimeoutError):
            print(colored(f"Timeout when attempting to profile service: {service_name}, node_ref: {node_ref}",
                          'red'))
            print(colored(f"Connection object: {connection}:", 'yellow'))
            print(colored(vars(connection) if connection else 'no connection', 'yellow'))
        print(f"{type(profile_exceptions[0])}({profile_exceptions[0]})")
        raise profile_exceptions[0]

    # PARSE PROFILE RESULTS
    children = {}
    for node_transports in profile_results:
        for node_transport in node_transports:
            if network.skip_address(node_transport.address):
                logs.logger.debug("Excluded profile result: `%s`. Reason: address_skipped",
                                  node_transport.address)
                continue
            if network.skip_protocol_mux(node_transport.protocol_mux):
                logs.logger.debug("Excluded profile result: `%s`. Reason: protocol_mux_skipped",
                                  node_transport.protocol_mux)
                continue
            child_ref, child = create_node(node_transport)
            if child:
                children[child_ref] = child

    logs.logger.debug("Profiled %d non-excluded children from %d profile results for %s",
                      len(children), len(profile_results), service_name)

    # EXCLUDE DISABLED PROVIDERS
    nonexcluded_children = {ref: n for ref, n in children.items() if n.provider not in constants.ARGS.disable_providers}

    return nonexcluded_children


def create_node(node_transport: NodeTransport) -> (str, Optional[Node]):
    if constants.ARGS.obfuscate:
        node_transport = obfuscate.obfuscate_node_transport(node_transport)
    if node_transport.provider in constants.ARGS.disable_providers:
        logs.logger.info("Skipping discovery for node: %s:%s due to disabled provider: %s",
                         node_transport.provider, node_transport.address, node_transport.provider)
        return "", None

    public_ip = _is_public_ip(node_transport.address)
    node = Node(
        profile_strategy_name=node_transport.profile_strategy_name,
        protocol=node_transport.protocol,
        protocol_mux=node_transport.protocol_mux,
        provider='www' if public_ip else node_transport.provider,
        containerized=providers.get_provider_by_ref(node_transport.provider).is_container_platform(),
        from_hint=node_transport.from_hint,
        public_ip=public_ip,
        address=node_transport.address,
        service_name=node_transport.debug_identifier if node_transport.from_hint else None,
        metadata=node_transport.metadata,
        node_type=node_transport.node_type
    )

    # warnings/errors
    if not node_transport.address or 'null' == node_transport.address:
        node.errors['NULL_ADDRESS'] = True
    if 0 == node_transport.num_connections:
        node.warnings['DEFUNCT'] = True

    node_ref = '_'.join(str(x) for x in [node_transport.protocol.ref, node_transport.address,
                        node_transport.protocol_mux, node_transport.debug_identifier]
                        if x is not None)
    return node_ref, node


def _is_public_ip(ip_string):
    try:
        ip = ipaddress.ip_address(ip_string)
        if ip.is_unspecified:
            # for our implementation we are considering unknown as "public"
            return True
        if ip.is_reserved or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            return False
        return not ip.is_private
    except ValueError:
        return False
