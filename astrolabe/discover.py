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
import sys
import traceback

from dataclasses import replace
from termcolor import colored
from typing import Dict, List, Optional, Tuple

from . import profile_strategy, network, constants, logs, obfuscate, providers
from .profile_strategy import ProfileStrategy
from .node import Node, NodeTransport

service_name_cache: Dict[str, Optional[str]] = {}  # {address: service_name}
child_cache: Dict[str, Dict[str, Node]] = {}  # {service_name: {node_ref, Node}}


async def discover(tree: Dict[str, Node], ancestors: list):
    depth = len(ancestors)
    logs.logger.debug("Found %s nodes to profile at depth: %d", str(len(tree)), depth)

    conns, tree = await _open_connections(tree, ancestors)
    service_names, conns = await _lookup_service_names(tree, conns)
    await _assign_names_and_detect_cycles(tree, service_names, ancestors)

    if len(ancestors) > constants.ARGS.max_depth - 1:
        logs.logger.debug("Reached --max-depth of %d at depth: %d", constants.ARGS.max_depth, depth)
        return

    nodes_with_conns = [(item[0], item[1], conn) for item, conn in zip(tree.items(), conns)]
    profileable_nodes = _filter_unprofileable_nodes_and_add_warnings(nodes_with_conns, depth)
    await _recursively_profile(tree, profileable_nodes, depth, ancestors)


def _filter_unprofileable_nodes_and_add_warnings(nodes_with_conns: List[Tuple[str, Node, type]], 
                                                 depth: int) -> List[Tuple[str, Node, type]]:
    profileable_nodes = []
    for ref, node, conn in nodes_with_conns:
        if node.is_profileable(depth):
            profileable_nodes.append((ref, node, conn))
        else:
            node.warnings['PROFILE_SKIPPED'] = True

    return profileable_nodes


async def _recursively_profile(tree: Dict[str, Node], profileable_nodes: List[Tuple[str, Node, type]],
                               depth: int, ancestors: list):
    profile_tasks = [_profile_with_hints(tree[ref].provider, ref, node.address, node.service_name, conn)
                     for ref, node, conn in profileable_nodes]
    while len(profile_tasks) > 0:
        children_res, children_pending_tasks = await asyncio.wait(profile_tasks, return_when=asyncio.FIRST_COMPLETED)
        for future in children_res:
            node_ref, children = _get_profile_result_with_exception_handling(future)
            child_depth = depth + 1
            nonexcluded_children = {ref: child for ref, child in children.items() if not child.is_excluded(child_depth)}
            tree[node_ref].children = nonexcluded_children
            children_with_address = {ref: child for ref, child in nonexcluded_children.items() if child.address}
            if children_with_address:
                asyncio.ensure_future(discover(children_with_address, ancestors + [tree[node_ref].service_name]))
        profile_tasks = children_pending_tasks


async def _assign_names_and_detect_cycles(tree: Dict[str, Node], service_names: str, ancestors: list):
    for node_ref, service_name in zip(list(tree), service_names):
        if not service_name:
            logs.logger.debug("Name lookup failed for %s with address: %s", node_ref, tree[node_ref].address)
            service_name_cache[tree[node_ref].address] = None
            tree[node_ref].errors['NAME_LOOKUP_FAILED'] = True
            continue
        service_name = tree[node_ref].profile_strategy.rewrite_service_name(service_name, tree[node_ref])
        if constants.ARGS.obfuscate:
            service_name = obfuscate.obfuscate_service_name(service_name)
        if service_name in ancestors:
            tree[node_ref].warnings['CYCLE'] = True
        tree[node_ref].service_name = service_name


def _get_profile_result_with_exception_handling(future: asyncio.Future) -> (str, Dict[str, Node]):
    try:
        return future.result()
    except TimeoutError:
        sys.exit(1)
    except Exception as e:
        traceback.print_tb(e.__traceback__)
        sys.exit(1)


async def _open_connections(tree: Dict[str, Node], ancestors: List[str]) -> (list, Dict[str, Node]):
    connectable_tree = _filter_skipped_nodes_and_add_errors(tree)
    conns = await _gather_connections(connectable_tree)
    exceptions = [(ref, e) for ref, e in zip(list(connectable_tree), conns) if isinstance(e, Exception)]
    _handle_connection_open_exceptions(exceptions, tree, ancestors)
    clean_tree = {item[0]: item[1] for item, conn in zip(connectable_tree.items(), conns)
                  if not isinstance(conn, Exception)}
    clean_conns = [conn for conn in conns if not isinstance(conn, Exception)]

    return clean_conns, clean_tree


def _filter_skipped_nodes_and_add_errors(tree: Dict[str, Node]) -> Dict[str, Node]:
    connectable_tree = {}
    for ref, node in tree.items():
        if network.skip_protocol_mux(node.protocol_mux):
            node.errors['CONNECT_SKIPPED'] = True
        else:
            connectable_tree[ref] = node
    return connectable_tree


async def _gather_connections(tree: Dict[str, Node]):
    return await asyncio.gather(
        *[asyncio.wait_for(
            _open_connection(node.address, providers.get_provider_by_ref(node.provider)), constants.ARGS.timeout
        ) for node_ref, node in tree.items()],
        return_exceptions=True
    )


def _handle_connection_open_exceptions(exceptions: List[Tuple[str, Exception]], tree: Dict[str, Node],
                                       ancestors: List[str]):
    for node_ref, e in exceptions:
        if isinstance(e, (providers.TimeoutException, asyncio.TimeoutError)):
            logs.logger.debug("Connection timeout when attempting to connect to %s with address: %s"
                              , node_ref, tree[node_ref].address)
            tree[node_ref].errors['TIMEOUT'] = True
        else:
            child_of = f"child of {ancestors[len(ancestors)-1]}" if len(ancestors) > 0 else ''
            print(colored(f"Exception {e.__class__.__name__} occurred opening connection for {node_ref}, "
                          f"{tree[node_ref].address} {child_of}", 'red'))
            traceback.print_tb(e.__traceback__)
            sys.exit(1)


async def _open_connection(address: str, provider: providers.ProviderInterface):
    if address in service_name_cache:
        if service_name_cache[address] is None:
            logs.logger.debug("Not opening connection: name is None (%s)", address)
            return None
        if network.skip_service_name(service_name_cache[address]):
            logs.logger.debug("Not opening connection: skip (%s)", service_name_cache[address])
            return None
        if service_name_cache[address] in child_cache:
            logs.logger.debug("Not opening connections: cached (%s)", service_name_cache[address])
            return None

    logs.logger.debug("Opening connection: %s", address)
    return await provider.open_connection(address)


async def _lookup_service_names(tree: Dict[str, Node], conns: list) -> (List[str], list):
    # lookup_name / detect cycles
    service_names = await asyncio.gather(
        *[asyncio.wait_for(
            _lookup_service_name(node.address, providers.get_provider_by_ref(node.provider), conn),
            constants.ARGS.timeout) for node, conn in zip(tree.values(), conns)],
        return_exceptions=True
    )

    # handle exceptions
    exceptions = [(ref, e) for ref, e in zip(list(tree), service_names) if isinstance(e, Exception)]
    for node_ref, e in exceptions:
        if isinstance(e, asyncio.TimeoutError):
            print(colored("Timeout during name lookup for %s:", node_ref, 'red'))
            print(colored({**vars(tree[node_ref]), 'profile_strategy': tree[node_ref].profile_strategy.name},
                          'yellow'))
            traceback.print_tb(e.__traceback__)
            sys.exit(1)
        else:
            traceback.print_tb(e.__traceback__)
            sys.exit(1)

    return service_names, conns


async def _lookup_service_name(address: str, provider: providers.ProviderInterface,
                               connection: type) -> Optional[str]:
    if address in service_name_cache:
        logs.logger.debug("Using cached service name (%s for: %s)", service_name_cache[address], address)
        return service_name_cache[address]

    logs.logger.debug("Getting service name for address %s", address)
    service_name = await provider.lookup_name(address, connection)
    logs.logger.debug("Discovered name: %s for address %s", service_name, address)
    service_name_cache[address] = service_name

    return service_name


async def _profile_with_hints(provider_ref: str, node_ref: str, address: str, service_name: str,
                              connection: type) -> (str, Dict[str, Node]):
    if service_name in child_cache:
        logs.logger.debug("Found %d children in cache for:%s", len(child_cache[service_name]), service_name)
        # we must to this copy to avoid various contention and infinite recursion bugs
        return node_ref, {r: replace(n, children={}, warnings=n.warnings.copy(), errors=n.errors.copy())
                          for r, n in child_cache[service_name].items()}

    logs.logger.debug("Profiling for %s", node_ref)
    tasks, profile_strategies = _compile_profile_tasks_and_strategies(address, service_name,
                                                                      providers.get_provider_by_ref(provider_ref),
                                                                      connection)

    # if there are any timeouts or exceptions, panic and run away! we don't want an incomplete graph to look complete
    profile_results = await asyncio.gather(*tasks, return_exceptions=True)
    profile_exceptions = [e for e in profile_results if isinstance(e, Exception)]
    if profile_exceptions:
        if isinstance(profile_exceptions[0], asyncio.TimeoutError):
            print(colored(f"Timeout when attempting to profile service: {service_name}, node_ref: {node_ref}", 'red'))
            print(colored(f"Connection object: {connection}:", 'yellow'))
            print(colored(vars(connection), 'yellow'))
        print(f"{type(profile_exceptions[0])}({profile_exceptions[0]})")
        raise profile_exceptions[0]

    # parse returned NodeTransport objects to Node objects
    children = {}
    for node_transports, prof_strategy in [(nts, cs) for nts, cs in zip(profile_results, profile_strategies) if nts]:
        for node_transport in node_transports:
            if _skip_protocol_mux(node_transport.protocol_mux):
                continue
            child_ref, child = _create_node(prof_strategy, node_transport)
            children[child_ref] = child
    logs.logger.debug("Found %d children for %s", len(children), service_name)
    child_cache[service_name] = children

    return node_ref, children


def _compile_profile_tasks_and_strategies(address: str, service_name: str, provider: providers.ProviderInterface,
                                          connection: type) -> (List[callable], List[ProfileStrategy]):
    tasks = []
    profile_strategies: List[ProfileStrategy] = []

    # profile_strategies
    for cs in profile_strategy.profile_strategies:
        if cs.protocol.ref in constants.ARGS.skip_protocols or cs.filter_service_name(service_name) \
                or provider.ref() not in cs.providers:
            continue
        profile_strategies.append(cs)
        tasks.append(asyncio.wait_for(
            provider.profile(address, connection, **cs.provider_args),
            timeout=constants.ARGS.timeout
        ))

    # take hints
    for hint in [hint for hint in network.hints(service_name)
                 if hint.instance_provider not in constants.ARGS.disable_providers]:
        hint_provider = providers.get_provider_by_ref(hint.instance_provider)
        tasks.append(asyncio.wait_for(hint_provider.take_a_hint(hint), timeout=constants.ARGS.timeout))
        profile_strategies.append(
            replace(
                profile_strategy.HINT_DISCOVERY_STRATEGY,
                child_provider={'type': 'matchAll', 'provider': hint.provider},
                protocol=hint.protocol
            )
        )

    return tasks, profile_strategies


def _skip_protocol_mux(mux: str):
    for skip in constants.ARGS.skip_protocol_muxes:
        if skip in mux:
            return True

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

    node_ref = '_'.join(x for x in [ps_used.protocol.ref, node_transport.protocol_mux, node_transport.debug_identifier]
                        if x is not None)
    return node_ref, node
