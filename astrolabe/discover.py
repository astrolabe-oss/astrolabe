"""
Module Name: discover

Description:
The high level async, iterative discovering functionality of astrolabe/discover. Here is where we iteratively
profile nodes, compile async tasks, lookup node names, and parse children until complete.

Copyright:
Copyright 2024 Magellanbot, Inc

License:
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import sys
import traceback
from dataclasses import replace
from typing import Dict, List, Tuple, Optional

from termcolor import colored

from astrolabe import database, profile_strategy, network, constants, logs, obfuscate, providers
from astrolabe.profile_strategy import ProfileStrategy
from astrolabe.providers import ProviderInterface
from astrolabe.node import Node

# An internal cache which prevents astrolabe from re-profiling a Compute node of the same Application
# that has already been profiled on a different address. We may not want this "feature" going forward
# if we want to do more thorough/exhaustive profiling of every individual Compute node in a cluster.
child_cache: Dict[str, Dict[str, Node]] = {}  # {'provider_ref:service_name': {node_ref, Node}}


class DiscoveryException(Exception):
    def __init__(self, message=None):
        super().__init__(message)
        self.node: Optional[Node] = None
        self.ancestors: Optional[List[str]] = None


stack: Dict[str, Tuple[Node, List[str]]]


async def discover(initial_tree: Dict[str, Node], initial_ancestors: List[str]):
    global stack
    stack = {f"{n.provider}:{n.address}": (n, initial_ancestors) for n in initial_tree.values()}
    coroutines = []

    while len([n for n in stack.values() if not n[0].profile_complete()]) > 0:
        sleep_secs = 0.01
        unprofiled_stack = {key: (n, a) for key, (n, a) in stack.items()
                            if not n.profile_complete() and not n.profile_locked()}
        if not unprofiled_stack:
            logs.logger.debug("Waiting for pending profiles to complete, sleeping %d", sleep_secs)
            await asyncio.sleep(sleep_secs)
            continue

        logs.logger.debug("Stack of %d nodes found to profile", len(unprofiled_stack))
        node_ref, (node, ancestors) = next(iter(unprofiled_stack.items()))
        depth = len(ancestors)
        logs.logger.debug("Profiling node %s at depth: %d", node_ref, depth)

        node.aquire_profile_lock()
        coro = asyncio.create_task(_discover_node(node_ref, node, ancestors))
        coroutines.append(coro)
        await asyncio.sleep(0)  # explicitly hand off the loop
        await asyncio.sleep(sleep_secs)  # actually give it a sec

    # For now, we are doing a fail fast on unknown discovery exceptions.
    #  TODO: Eventually, we will be more elegant about async error handling!
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
            sys.exit(1)


async def _discover_node(node_ref: str, node: Node, ancestors: List[str]):
    global stack  # pylint:disable=global-variable-not-assigned
    if node.get_profile_timestamp() is not None:
        logs.logger.info("Profile already completed for node: %s:%s (%s)",
                         node.provider, node.address, node.service_name)
        return node, {}

    depth = len(ancestors)
    provider = providers.get_provider_by_ref(node.provider)

    try:
        profiled_children = await _discovery_algo(node_ref, node, ancestors, provider, depth)
        node.children = {**node.children, **profiled_children}  # merge with pre-profiled children

        # ONLY ITERATE OVER CHILDREN W/ ADDRESS
        #  TODO: Better error handling for children discovered, for some reason?, without address...
        children_with_address = [child for child in node.children.values() if child.address]

        for child in children_with_address:
            stack[f"{child.provider}:{child.address}"] = (child, ancestors + [node.service_name])
    except (providers.TimeoutException, asyncio.TimeoutError):
        logs.logger.debug("TIMEOUT attempting to connect to %s with address: %s", node_ref, node.address)
        logs.logger.debug({**vars(node), 'profile_strategy': node.profile_strategy.name}, 'yellow')
        node.errors['TIMEOUT'] = True
    except Exception as exc:
        dexc = DiscoveryException(exc)
        dexc.node = node
        dexc.ancestors = ancestors
        raise dexc from exc
    finally:
        logs.logger.debug("Setting profile timestamp for %s", node_ref)
        node.set_profile_timestamp()
        node.clear_profile_lock()
        database.save_node(node)


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
    conn = await asyncio.wait_for(provider.open_connection(node.address), constants.ARGS.timeout)

    # RUN SIDECAR
    logs.logger.debug("Running sidecar for address %s", node.address)
    await asyncio.wait_for(provider.sidecar(node.address, conn), constants.ARGS.timeout)

    # LOOKUP SERVICE NAME
    await asyncio.wait_for(_lookup_service_name(node, provider, conn), constants.ARGS.timeout)

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
    return await _profile_with_hints(node, node_ref, conn)


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
    service_name = node.profile_strategy.rewrite_service_name(service_name, node)
    if constants.ARGS.obfuscate:
        service_name = obfuscate.obfuscate_service_name(service_name)

    # WRITE/CACHE
    node.service_name = service_name


# pylint:disable=too-many-locals
async def _profile_with_hints(node: Node, node_ref: str, connection: type) -> Dict[str, Node]:
    provider_ref = node.provider
    address = node.address
    service_name = node.service_name

    # CHECK CACHE
    cache_key = f"{node.provider}:{node.service_name}"
    if cache_key in child_cache:
        logs.logger.debug("Found %d children in cache for:%s", len(child_cache[cache_key]), cache_key)
        # we must do this copy to avoid various contention and infinite recursion bugs
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
            if network.skip_address(node_transport.address):
                logs.logger.debug("Excluded profile result: `%s`. Reason: address_skipped",
                                  node_transport.address)
                continue
            if network.skip_protocol_mux(node_transport.protocol_mux):
                logs.logger.debug("Excluded profile result: `%s`. Reason: protocol_mux_skipped",
                                  node_transport.protocol_mux)
                continue
            child_ref, child = database.create_node(prof_strategy, node_transport)
            # if we have inventoried this node already, use that!
            inventory_node = database.get_node_by_address(child.address)
            if inventory_node:
                database.merge_node(inventory_node, child)
                child = inventory_node
            children[child_ref] = child

    logs.logger.debug("Profiled %d non-excluded children from %d profile results for %s",
                      len(children), len(profile_results), service_name)

    # EXCLUDE DISABLED PROVIDERS
    nonexcluded_children = {ref: n for ref, n in children.items() if n.provider not in constants.ARGS.disable_providers}

    # SET CACHE
    child_cache[cache_key] = nonexcluded_children
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
