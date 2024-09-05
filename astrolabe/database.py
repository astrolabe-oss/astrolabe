from dataclasses import is_dataclass, fields
from typing import Dict, Optional

from astrolabe import constants, obfuscate, providers
from astrolabe.node import Node, NodeTransport, NodeType
from astrolabe.profile_strategy import ProfileStrategy

_node_index_by_address: Dict[str, Node] = {}  # {address: Node()}
_node_index_by_dnsname: Dict[str, Node] = {}  # {dns_name: Node()}


def save_node(node: Node):
    if not node.address:
        raise Exception("Node has no address, cannot save!")  # pylint:disable=broad-exception-raised

    if node.address:
        _node_index_by_address[node.address] = node


def save_node_by_dnsname(node: Node, dns_name: str):
    _node_index_by_dnsname[dns_name] = node


def get_node_by_address(address: str) -> Optional[Node]:
    if address not in _node_index_by_address:
        return None

    return _node_index_by_address[address]


def get_node_by_dnsname(dns_name: str) -> Optional[Node]:
    if dns_name not in _node_index_by_dnsname:
        return None

    return _node_index_by_dnsname[dns_name]


def get_nodes_pending_dnslookup() -> [str, Node]:  # {dns_name: Node()}
    return _node_index_by_dnsname.items()


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
