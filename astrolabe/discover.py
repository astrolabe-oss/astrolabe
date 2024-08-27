"""
Module Name: discover

Description:
The high level async, recursive discovering functionality of astrolabe/discover.  Here is where we recursively
profile nodes and, compile async tasks, lookup node names, and parse children until complete.

Copyright:
Copyright 2024 Magellanbot, Inc

License:
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import ipaddress
import sys
import traceback
from dataclasses import replace, is_dataclass, fields
from typing import Dict, List

from termcolor import colored

from astrolabe import profile_strategy, network, constants, logs, obfuscate, providers
from astrolabe.profile_strategy import ProfileStrategy
from astrolabe.providers import ProviderInterface
from astrolabe.node import Node, NodeTransport

node_inventory_by_address: Dict[str, Node] = {}  # {address: Node()}
node_inventory_by_dnsname: Dict[str, Node] = {}  # {dns_name: Node()}
node_inventory_null_name_by_address: List[str] = []  # [address]
child_cache: Dict[str, Dict[str, Node]] = {}  # {'provider_ref:service_name': {node_ref, Node}}


class DiscoveryException(Exception):
    def __init__(self, message=None):
        super().__init__(message)
        self.node = None


async def discover(tree: Dict[str, Node], ancestors: List[str]):
    depth = len(ancestors)
    logs.logger.debug("Found %s nodes to profile at depth: %d", str(len(tree)), depth)

    asyncio_tasks = []

    for node_ref, node in tree.items():
        asyncio_tasks.append(_discover_node(node_ref, node, ancestors))

    results = await asyncio.gather(*asyncio_tasks, return_exceptions=True)

    for result in results:
        if isinstance(result, DiscoveryException):
            exc = result.__cause__
            node = result.node
            child_of = f"child of {ancestors[len(ancestors) - 1]}" if len(ancestors) > 0 else 'SEED'
            logs.logger.error("Exception %s occurred connecting to %s:%s child of `%s`",
                              exc, node.provider, node.address, child_of)
            traceback.print_tb(exc.__traceback__)
            sys.exit(1)


async def _discover_node(node_ref: str, node: Node, ancestors: List[str]):
    if node.get_profile_timestamp() is not None:
        logs.logger.info("Profile already completed for node: %s:%s (%s)",
                         node.provider, node.address, node.service_name)
        return
    depth = len(ancestors)
    provider = providers.get_provider_by_ref(node.provider)
    try:
        await _discovery_algo(node_ref, node, ancestors, provider, depth)
        node.set_profile_timestamp()
    except (providers.TimeoutException, asyncio.TimeoutError):
        logs.logger.debug("TIMEOUT attempting to connect to %s with address: %s", node_ref, node.address)
        logs.logger.debug({**vars(node), 'profile_strategy': node.profile_strategy.name}, 'yellow')
        node.errors['TIMEOUT'] = True
        return
    except Exception as exc:
        dexc = DiscoveryException(exc)
        dexc.node = node
        raise dexc from exc


async def _discovery_algo(node_ref: str, node: Node, ancestors: List[str], provider: ProviderInterface, depth: int):
    if network.skip_protocol_mux(node.protocol_mux):
        node.errors['CONNECT_SKIPPED'] = True
        return

    # SKIP?
    if node.service_name and network.skip_service_name(node.service_name):
        logs.logger.debug("Not opening connection: skip (%s)", node.address)
        return

    # OPEN CONNECTION -> Optional[Type]
    logs.logger.debug("Opening connection: %s", node.address)
    conn = await asyncio.wait_for(provider.open_connection(node.address), constants.ARGS.timeout)

    # RUN SIDECAR
    logs.logger.debug("Running sidecar for address %s", node.address)
    await asyncio.wait_for(provider.sidecar(node.address, conn), constants.ARGS.timeout)

    # SERVICE NAME
    await asyncio.wait_for(_lookup_service_name(node, provider, conn), constants.ARGS.timeout)

    # DETECT CYCLES
    if node.service_name and node.service_name in ancestors:
        node.errors['CYCLE'] = True
        return

    # MAX DEPTH
    if len(ancestors) > constants.ARGS.max_depth - 1:
        logs.logger.debug("Reached --max-depth of %d at depth: %d", constants.ARGS.max_depth, depth)
        return

    # PROFILEABLE?
    if not node.is_profileable(depth):
        node.errors['PROFILE_SKIPPED'] = True
        return

    # PROFILE
    profiled_children = await _profile_with_hints(node, node_ref, conn, depth)
    node.children = {**node.children, **profiled_children}  # merge with pre-profiled children

    # RECURSE
    children_with_address = {ref: child for ref, child in node.children.items() if child.address}
    if children_with_address:
        asyncio.ensure_future(discover(children_with_address, ancestors + [node.service_name]))


async def _lookup_service_name(node: Node, provider: providers.ProviderInterface,
                               connection: type) -> None:
    if not node.address:
        logs.logger.warning("Node name lookup required with no address!")
        node.warnings['NAME_LOOKUP_FAILED'] = True
        return

    if node.service_name:
        logs.logger.debug("Using pre-profiled/cached service name %s for address: %s)", node.service_name, node.address)
        return
    address = node.address

    logs.logger.debug(f"Getting service name for address %s from provider {provider.ref()}", address)
    service_name = await provider.lookup_name(address, connection)
    if not service_name:
        logs.logger.debug("Name discovery failed for address %s", address)
        node_inventory_null_name_by_address.append(node.address)
        node.warnings['NAME_LOOKUP_FAILED'] = True
        return

    logs.logger.debug("Discovered name: %s for address %s", service_name, address)
    service_name = node.profile_strategy.rewrite_service_name(service_name, node)
    if constants.ARGS.obfuscate:
        service_name = obfuscate.obfuscate_service_name(service_name)
    node.service_name = service_name
    node_inventory_by_address[address] = node


# pylint:disable=too-many-locals
async def _profile_with_hints(node: Node, node_ref: str, connection: type, depth: int) -> Dict[str, Node]:
    provider_ref = node.provider
    address = node.address
    service_name = node.service_name

    # CHECK CACHE
    cache_key = f"{node.provider}:{node.service_name}"
    if cache_key in child_cache:
        logs.logger.debug("Found %d children in cache for:%s", len(child_cache[cache_key]), cache_key)
        # we must to this copy to avoid various contention and infinite recursion bugs
        return {r: replace(n, children={}, warnings=n.warnings.copy(), errors=n.errors.copy())
                for r, n in child_cache[cache_key].items()}

    # PROFILE ASYNCIO TASKS
    logs.logger.debug(f"Profiling provider: '{provider_ref}' for %s", node_ref)
    tasks, profile_strategies = _compile_profile_tasks_and_strategies(address, service_name,
                                                                      providers.get_provider_by_ref(provider_ref),
                                                                      connection)

    # HANDLE EXCEPTIONS
    profile_results = await asyncio.gather(*tasks, return_exceptions=True)
    profile_exceptions = [e for e in profile_results if isinstance(e, Exception)]
    if profile_exceptions:
        if isinstance(profile_exceptions[0], asyncio.TimeoutError):
            print(colored(f"Timeout when attempting to profile service: {service_name}, node_ref: {node_ref}", 'red'))
            print(colored(f"Connection object: {connection}:", 'yellow'))
            print(colored(vars(connection), 'yellow'))
        print(f"{type(profile_exceptions[0])}({profile_exceptions[0]})")
        raise profile_exceptions[0]

    # PARSE PROFILE RESULTS
    children = {}
    for node_transports, prof_strategy in [(nts, cs) for nts, cs in zip(profile_results, profile_strategies) if nts]:
        for node_transport in node_transports:
            if _skip_address(node_transport.address):
                logs.logger.debug("Excluded profile result: `%s`. Reason: address_skipped",
                                  node_transport.address)
                continue
            if _skip_protocol_mux(node_transport.protocol_mux):
                logs.logger.debug("Excluded profile result: `%s`. Reason: protocol_mux_skipped",
                                  node_transport.protocol_mux)
                continue
            child_ref, child = _create_node(prof_strategy, node_transport)
            # if we have inventoried this node already, use that!
            if child.address and child.address in node_inventory_by_address:
                inventory_node = node_inventory_by_address[child.address]
                _merge_node(inventory_node, child)
                child = inventory_node
            children[child_ref] = child

    logs.logger.debug("Profiled %d non-excluded children from %d profile results for %s",
                      len(children), len(profile_results), service_name)

    # CHILD EXCLUSIONS
    child_depth = depth + 1
    nonexcluded_children = {ref: child for ref, child in children.items() if not child.is_excluded(child_depth)}

    # SET CACHE
    child_cache[cache_key] = nonexcluded_children

    # MERGE CHILDREN W/ INVENTORY
    logs.logger.debug("Merging %d existing children for %s", len(node.children), node.address)
    _merge_children_with_inventory_nodes(nonexcluded_children)

    return nonexcluded_children


def _compile_profile_tasks_and_strategies(address: str, service_name: str, provider: providers.ProviderInterface,
                                          connection: type) -> (List[callable], List[ProfileStrategy]):
    tasks = []
    profile_strategies: List[ProfileStrategy] = []

    # PROFILE STRATEGIES
    for pfs in profile_strategy.profile_strategies:
        if provider.ref() not in pfs.providers:
            continue
        if pfs.protocol.ref in constants.ARGS.skip_protocols:
            continue
        if pfs.filter_service_name(service_name):
            continue
        profile_strategies.append(pfs)
        tasks.append(asyncio.wait_for(
            provider.profile(address, pfs, connection),
            timeout=constants.ARGS.timeout
        ))

    # HINTS
    for hint in [hint for hint in network.hints(service_name)
                 if hint.instance_provider not in constants.ARGS.disable_providers]:
        hint_provider = providers.get_provider_by_ref(hint.instance_provider)
        tasks.append(asyncio.wait_for(hint_provider.take_a_hint(hint), timeout=constants.ARGS.timeout))
        profile_strategies.append(
            replace(
                profile_strategy.HINT_PROFILE_STRATEGY,
                child_provider={'type': 'matchAll', 'provider': hint.provider},
                protocol=hint.protocol
            )
        )

    return tasks, profile_strategies


###########
# HELPERS #
###########


def _merge_children_with_inventory_nodes(children: Dict[str, Node]) -> None:
    """we want nodes in the tree and inventory to be the same memory space nodes, so
          here we merge the tree node's attributes into the inventory node, and then
          drop the tree node and replace it with the pointer to the inventory node"""
    for ref, node in children.items():
        if node.address in node_inventory_by_address:
            inventory_node = node_inventory_by_address[node.address]
            _merge_node(copyto_node=inventory_node, copyfrom_node=node)
            # replace dictionary node with the inventory node to preserve memory linkage
            children[ref] = inventory_node


def _merge_node(copyto_node: Node, copyfrom_node: Node) -> None:
    if not is_dataclass(copyto_node) or not is_dataclass(copyfrom_node):
        raise ValueError("Both copyto_node and copyfrom_node must be dataclass instances")

    for field in fields(Node):
        attr_name = field.name
        inventory_preferred_attrs = ['provider', 'node_type']
        if attr_name in inventory_preferred_attrs:
            continue

        copyfrom_value = getattr(copyfrom_node, attr_name)

        # Only copy if the source value is not None, empty string, empty dict, or empty list
        if copyfrom_value is not None and copyfrom_value != "" and copyfrom_value != {} and copyfrom_value != []:
            setattr(copyto_node, attr_name, copyfrom_value)


def _skip_protocol_mux(mux: str):
    for skip in constants.ARGS.skip_protocol_muxes:
        if skip in mux:
            return True

    return False


ignored_cidrs = ['169.254.169.254/32']
ignored_ip_networks = [ipaddress.ip_network(cidr) for cidr in ignored_cidrs]


def _skip_address(address: str):
    try:
        ipaddr = ipaddress.ip_address(address)
        skip = any(ipaddr in cidr for cidr in ignored_ip_networks)
        return skip
    except ValueError:
        pass  # address is not a valid IP address
    return False


def _create_node(ps_used: ProfileStrategy, node_transport: NodeTransport) -> (str, Node):
    provider = ps_used.determine_child_provider(node_transport.protocol_mux, node_transport.address)
    from_hint = constants.PROVIDER_HINT in ps_used.providers
    if constants.ARGS.obfuscate:
        node_transport = obfuscate.obfuscate_node_transport(node_transport)
    node = Node(
        profile_strategy=ps_used,
        protocol=ps_used.protocol,
        protocol_mux=node_transport.protocol_mux,
        provider=provider,
        containerized=providers.get_provider_by_ref(provider).is_container_platform(),
        from_hint=from_hint,
        address=node_transport.address,
        service_name=node_transport.debug_identifier if from_hint else None,
        metadata=node_transport.metadata
    )

    # warnings/errors
    if not node_transport.address or 'null' == node_transport.address:
        node.errors['NULL_ADDRESS'] = True
    if 0 == node_transport.num_connections:
        node.warnings['DEFUNCT'] = True

    node_ref = '_'.join(x for x in [ps_used.protocol.ref, node_transport.address,
                        node_transport.protocol_mux, node_transport.debug_identifier]
                        if x is not None)
    return node_ref, node
