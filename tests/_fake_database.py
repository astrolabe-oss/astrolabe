# _fake_database.py... a fake database module used for testing patching

from typing import Dict, Optional

from astrolabe.node import Node, NodeType, merge_node

_node_primary_index: Dict[str, Node] = {}  # {"Node.provider:Node.address": Node()}


_node_index_by_address: Dict[str, Node] = {}  # {address: Node()}
_node_index_by_dnsname: Dict[str, Node] = {}  # {dns_name: Node()}
_node_connections: Dict[str, Dict[str, Node]] = {}  # {id(Node): {node_ref: Node()}


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
    parent_key = str(id(node1))
    if parent_key not in _node_connections:
        children = {}
        _node_connections[parent_key] = children
    children = _node_connections[parent_key]
    child_key = f"{node2.provider}:{node2.address}"
    children[child_key] = node2


def get_connections(node: Node) -> Optional[Dict[str, Node]]:
    key = str(id(node))
    if key not in _node_connections:
        return None
    return _node_connections[key]


def get_nodes_unprofiled() -> Dict[str, Node]:
    return {
        n_id: node
        for n_id, node in _node_primary_index.items()
        if not node.profile_complete()
        and node.address is not None
    }


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
