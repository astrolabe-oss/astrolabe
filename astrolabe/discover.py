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
from typing import Dict, List, Optional, Tuple

from termcolor import colored

from astrolabe import profile_strategy, network, constants, logs, obfuscate, providers
from astrolabe.profile_strategy import ProfileStrategy
from astrolabe.node import Node, NodeTransport

node_inventory_by_address: Dict[str, Node] = {}  # {address: Node()}
node_inventory_by_dnsname: Dict[str, Node] = {}  # {dns_name: Node()}
node_inventory_null_name_by_address: List[str] = []  # [address]
child_cache: Dict[str, Dict[str, Node]] = {}  # {service_name: {node_ref, Node}}


async def discover(tree: Dict[str, Node], ancestors: list):
    depth = len(ancestors)
    logs.logger.debug("Found %s nodes to profile at depth: %d", str(len(tree)), depth)

    conns, tree = await _open_connections(tree, ancestors)
    await _run_sidecars(tree, conns)
    service_names, conns = await _lookup_service_names(tree, conns)
    await _assign_names_and_detect_cycles(tree, service_names, ancestors)

    if len(ancestors) > constants.ARGS.max_depth - 1:
        logs.logger.debug("Reached --max-depth of %d at depth: %d", constants.ARGS.max_depth, depth)
        return

    nodes_with_conns = [(item[0], item[1], conn) for item, conn in zip(tree.items(), conns)]
    profileable_nodes = _filter_unprofileable_nodes_and_add_warnings(nodes_with_conns, depth)
    await _recursively_profile(tree, profileable_nodes, depth, ancestors)


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


def _filter_unprofileable_nodes_and_add_warnings(nodes_with_conns: List[Tuple[str, Node, type]], 
                                                 depth: int) -> List[Tuple[str, Node, type]]:
    profileable_nodes = []
    for ref, node, conn in nodes_with_conns:
        if node.is_profileable(depth):
            profileable_nodes.append((ref, node, conn))
        else:
            node.errors['PROFILE_SKIPPED'] = True

    return profileable_nodes


async def _recursively_profile(tree: Dict[str, Node], profileable_nodes: List[Tuple[str, Node, type]],
                               depth: int, ancestors: list):
    profile_tasks = [_profile_with_hints(tree[ref].provider, ref, node.address, node.service_name, conn)
                     for ref, node, conn in profileable_nodes]
    while len(profile_tasks) > 0:
        children_res, children_pending_tasks = await asyncio.wait(profile_tasks, return_when=asyncio.FIRST_COMPLETED)
        for future in children_res:
            node_ref, children = _get_profile_result_with_exception_handling(future)
            node = tree[node_ref]
            child_depth = depth + 1
            nonexcluded_children = {ref: child for ref, child in children.items() if not child.is_excluded(child_depth)}
            _merge_children_with_inventory_nodes(nonexcluded_children)
            logs.logger.debug("Merging %d existing children for %s", len(node.children), tree[node_ref].address)
            node.children = {**node.children, **nonexcluded_children}  # merge with pre-profiled children
            children_with_address = {ref: child for ref, child in node.children.items() if child.address}
            if children_with_address:
                asyncio.ensure_future(discover(children_with_address, ancestors + [node.service_name]))
            node.set_profile_timestamp()  # will indicate that Node.profile_complete() is complete
        profile_tasks = children_pending_tasks


async def _assign_names_and_detect_cycles(tree: Dict[str, Node], service_names: str, ancestors: list):
    for node_ref, service_name in zip(list(tree), service_names):
        if not service_name:
            logs.logger.debug("Name lookup failed for %s with address: %s", node_ref, tree[node_ref].address)
            node_inventory_null_name_by_address.append(tree[node_ref].address)
            tree[node_ref].warnings['NAME_LOOKUP_FAILED'] = True
            continue
        service_name = tree[node_ref].profile_strategy.rewrite_service_name(service_name, tree[node_ref])
        if constants.ARGS.obfuscate:
            service_name = obfuscate.obfuscate_service_name(service_name)
        if service_name in ancestors:
            tree[node_ref].errors['CYCLE'] = True
        tree[node_ref].service_name = service_name


def _get_profile_result_with_exception_handling(future: asyncio.Future) -> (str, Dict[str, Node]):
    try:
        return future.result()
    except asyncio.TimeoutError as exc:
        print(exc, file=sys.stderr)
        traceback.print_tb(exc.__traceback__)
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
    for node_ref, exc in exceptions:
        if isinstance(exc, (providers.TimeoutException, asyncio.TimeoutError)):
            logs.logger.debug("Connection timeout when attempting to connect to %s with address: %s",
                              node_ref, tree[node_ref].address)
            tree[node_ref].errors['TIMEOUT'] = True
        else:
            child_of = f"child of {ancestors[len(ancestors)-1]}" if len(ancestors) > 0 else ''
            print(colored(f"Exception {exc.__class__.__name__} occurred opening connection for {node_ref}, "
                          f"{tree[node_ref].address} {child_of}", 'red'))
            traceback.print_tb(exc.__traceback__)
            sys.exit(1)


async def _open_connection(address: str, provider: providers.ProviderInterface):
    if address in node_inventory_null_name_by_address:
        logs.logger.debug("Not opening connection: name is None (%s)", address)
        return None

    if address in node_inventory_by_address:
        node = node_inventory_by_address[address]
        if network.skip_service_name(node.address):
            logs.logger.debug("Not opening connection: skip (%s)", node.address)
            return None
        if node.address in child_cache:
            logs.logger.debug("Not opening connections: profile results cached (%s)", node.address)
            return None

    logs.logger.debug("Opening connection: %s", address)
    return await provider.open_connection(address)


async def _lookup_service_names(tree: Dict[str, Node], conns: list) -> (List[str], list):
    # lookup_name / detect cycles
    service_names = await asyncio.gather(
        *[asyncio.wait_for(
            _lookup_service_name(node, providers.get_provider_by_ref(node.provider), conn),
            constants.ARGS.timeout) for node, conn in zip(tree.values(), conns)],
        return_exceptions=True
    )

    # handle exceptions
    exceptions = [(ref, e) for ref, e in zip(list(tree), service_names) if isinstance(e, Exception)]
    for node_ref, exc in exceptions:
        if isinstance(exc, asyncio.TimeoutError):
            print(colored("Timeout during name lookup for %s:", node_ref, 'red'))
            print(colored({**vars(tree[node_ref]), 'profile_strategy': tree[node_ref].profile_strategy.name},
                          'yellow'))
            traceback.print_tb(exc.__traceback__)
            sys.exit(1)
        else:
            traceback.print_tb(exc.__traceback__)
            sys.exit(1)

    return service_names, conns


async def _run_sidecars(tree: Dict[str, Node], conns: list) -> None:
    # lookup_name / detect cycles
    responses = await asyncio.gather(
        *[asyncio.wait_for(
            _run_sidecar(node.address, providers.get_provider_by_ref(node.provider), conn),
            constants.ARGS.timeout) for node, conn in zip(tree.values(), conns)],
        return_exceptions=True
    )

    # handle exceptions
    exceptions = [(ref, exc) for ref, exc in zip(list(tree), responses) if isinstance(exc, Exception)]
    for node_ref, exc in exceptions:
        if isinstance(exc, asyncio.TimeoutError):
            print(colored("Timeout during sidecar for %s:", node_ref, 'red'))
            print(colored({**vars(tree[node_ref]), 'profile_strategy': tree[node_ref].profile_strategy.name},
                          'yellow'))
            traceback.print_tb(exc.__traceback__)
            sys.exit(1)
        else:
            print(exc)
            traceback.print_tb(exc.__traceback__)
            sys.exit(1)


async def _lookup_service_name(node: Node, provider: providers.ProviderInterface,
                               connection: type) -> Optional[str]:
    if not node.address:
        logs.logger.warning("Node name lookup required with no address!")
        return None

    if node.service_name:
        logs.logger.debug("Using pre-profiled/cached service name %s for address: %s)", node.service_name, node.address)
        return node.service_name
    address = node.address

    logs.logger.debug(f"Getting service name for address %s from provider {provider.ref()}", address)
    service_name = await provider.lookup_name(address, connection)
    if not service_name:
        logs.logger.debug("Name discovery failed for address %s", address)
        return None

    logs.logger.debug("Discovered name: %s for address %s", service_name, address)
    node.service_name = service_name
    node_inventory_by_address[address] = node

    return service_name


async def _run_sidecar(address: str, provider: providers.ProviderInterface,
                       connection: type) -> bool:
    logs.logger.debug("Running sidecar for address %s", address)
    await provider.sidecar(address, connection)
    logs.logger.debug("Ran sidecar for address %s", address)

    return True


# pylint:disable=too-many-locals
async def _profile_with_hints(provider_ref: str, node_ref: str, address: str, service_name: str,
                              connection: type) -> (str, Dict[str, Node]):
    if service_name in child_cache:
        logs.logger.debug("Found %d children in cache for:%s", len(child_cache[service_name]), service_name)
        # we must to this copy to avoid various contention and infinite recursion bugs
        return node_ref, {r: replace(n, children={}, warnings=n.warnings.copy(), errors=n.errors.copy())
                          for r, n in child_cache[service_name].items()}

    logs.logger.debug(f"Profiling provider: '{provider_ref}' for %s", node_ref)
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
    child_cache[service_name] = children

    return node_ref, children


def _compile_profile_tasks_and_strategies(address: str, service_name: str, provider: providers.ProviderInterface,
                                          connection: type) -> (List[callable], List[ProfileStrategy]):
    tasks = []
    profile_strategies: List[ProfileStrategy] = []

    # profile_strategies
    for pfs in profile_strategy.profile_strategies:
        if pfs.protocol.ref in constants.ARGS.skip_protocols or pfs.filter_service_name(service_name) \
                or provider.ref() not in pfs.providers:
            continue
        profile_strategies.append(pfs)
        tasks.append(asyncio.wait_for(
            provider.profile(address, pfs, connection),
            timeout=constants.ARGS.timeout
        ))

    # take hints
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
