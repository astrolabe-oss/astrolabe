from dataclasses import is_dataclass, fields
from typing import Dict, Optional

from astrolabe import constants, obfuscate, providers
from astrolabe.node import Node, NodeTransport, NodeType
from astrolabe.profile_strategy import ProfileStrategy

_node_index_by_address: Dict[str, Node] = {}  # {address: Node()}
_node_index_by_dnsname: Dict[str, Node] = {}  # {dns_name: Node()}

# we are storing nodes with the unique id as provider:address for now.  This is a decent proxy for a unique ID
#  escept that sometimes during inventory  we find nodes without an address (just DNS names).  So... kick this can down
#  the road.
_node_primary_index: Dict[str, Node] = {}  # {node_id: Node()}


def get_nodes_unprofiled() -> Dict[str, Node]:
    return {
        n_id: node
        for n_id, node in _node_primary_index.items()
        if not node.profile_complete()
        and node.address is not None
    }


def save_node(node: Node) -> Node:
    if not node.address and len(node.aliases) < 1:
        raise Exception(f"Node must have address or aliases to save!: {node}")  # pylint:disable=broad-exception-raised

    # DNSNAME INDEX
    ret_node = node
    if len(node.aliases) > 0:
        for alias in node.aliases:
            _node_index_by_dnsname[alias] = node

    if node.address:
        # ADDRESS INDEX
        if node.address in _node_index_by_address:
            index_node = _node_index_by_address[node.address]
            merge_node(index_node, node)
            ret_node = index_node
        else:
            _node_index_by_address[node.address] = node

        # PRIMARY KEY INDEX
        primary_key = f"{node.provider}:{node.address}"
        if primary_key in _node_primary_index:
            db_node = _node_primary_index[primary_key]
            merge_node(db_node, node)
            ret_node = db_node
        else:
            _node_primary_index[primary_key] = node

    return ret_node


def connect_nodes(node1: Node, node2: Node):
    """This is just fooey.  When we have a real database it will be saved to the database.  For now, in memory the
         connection is made without having to do a lookup on any of our indices"""
    key = f"{node2.provider}:{node2.address}"
    node1.children[key] = node2


def get_node_by_address(address: str) -> Optional[Node]:
    if address not in _node_index_by_address:
        return None

    return _node_index_by_address[address]


def get_nodes_pending_dnslookup() -> [str, Node]:  # {dns_name: Node()}
    return {hostname: node for hostname, node in _node_index_by_dnsname.items() if node.address is None}.items()


def node_is_k8s_load_balancer(address: str) -> bool:
    if address not in _node_index_by_address:
        return False

    service_name = _node_index_by_address[address].service_name
    k8s_lbs = [node.service_name for node in _node_index_by_dnsname.values()
               if node.provider == 'k8s' and node.node_type == NodeType.TRAFFIC_CONTROLLER]
    return service_name in k8s_lbs


def node_is_k8s_service(address: str) -> bool:
    if address not in _node_index_by_address:
        return False

    node = _node_index_by_address[address]
    return node.provider == 'k8s' and node.node_type == NodeType.DEPLOYMENT


def create_node(ps_used: ProfileStrategy, node_transport: NodeTransport) -> (str, Node):
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


def merge_node(copyto_node: Node, copyfrom_node: Node) -> None:
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
