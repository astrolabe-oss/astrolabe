import os

from typing import Dict, Optional

from astrolabe.node import Node, NodeType, merge_node
from astrolabe import logs

from corelib import platdb

NEO4J_URI = os.getenv('NEO4J_URI')
NEO4J_USERNAME = os.getenv('NEO4J_USERNAME')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD')
NEO4J_CONNECTION = platdb.Neo4jConnection(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))
NEO4J_CONNECTION.open()
# TODO: probably should close the database somewhere

_node_index_by_address: Dict[str, Node] = {}  # {address: Node()}
_node_index_by_dnsname: Dict[str, Node] = {}  # {dns_name: Node()}

# we are storing nodes with the unique id as provider:address for now.  This is a decent proxy for a unique ID
#  escept that sometimes during inventory  we find nodes without an address (just DNS names).  So... kick this can down
#  the road.
_node_primary_index: Dict[str, Node] = {}  # {node_id: Node()}

def _serialize_node(node: Node) -> Optional[dict]:
    # TODO only unique identifier is address
    # except for Resources the unique ID will be Node.alias 
    if not isinstance(node, Node):
        raise Excpetion(f'The %$#@ Node is not a node:: {node}')

    return {
        'address': node.address
    }

def _load_node_from_neo4j(node: Node) -> Optional[platdb.PlatDBNode]:
    # TODO If it's not working for resource than I might have to try looking
    # up by the DNS name as well
    node_type_to_class = {
        NodeType.COMPUTE: platdb.Compute,     
        NodeType.DEPLOYMENT: platdb.Deployment,
        NodeType.RESOURCE: platdb.Resource,
        NodeType.TRAFFIC_CONTROLLER: platdb.TrafficController
    }

    cls = node_type_to_class[node.node_type]

    # Try to query based of address but if address is not set yet than use
    # DNS names
    try:
        obj = cls.nodes.get(**{'address': node.address})
    except:
        obj = cls.nodes.get(**{'dns_names': node.aliases})

    return obj

def get_nodes_unprofiled() -> Dict[str, Node]:
    return {
        n_id: node
        for n_id, node in _node_primary_index.items()
        if not node.profile_complete()
        and node.address is not None
    }


def save_node(node: Node) -> Node:
    new_save_node(node)

    return _old_save_node(node)

def _old_save_node(node: Node) -> Node:
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

def new_save_node(node: Node):
    # TODO should protocol be required?
    # TODO Is each node going to have to have it's own req'd attributes?
    protocol = None

    if node.protocol and node.protocol.ref:
        protocol = node.protocol.ref

    props = {
        'name': node.service_name,
        'address': node.address,
        'protocol': protocol,
        'protocol_multiplexor': node.protocol_mux,
        'profile_timestamp': node._profile_timestamp,
        'profile_lock_time': node._profile_lock_time
    }

    if node.node_type in [NodeType.COMPUTE, NodeType.NULL]:
        pdb_node = _merge_compute(node, props)
    elif node.node_type == NodeType.DEPLOYMENT:
        pdb_node = _merge_deployment(node, props)
    elif node.node_type == NodeType.RESOURCE:
        pdb_node = _merge_resource(node, props)
    elif node.node_type == NodeType.TRAFFIC_CONTROLLER:
        pdb_node = _merge_traffic_controller(node, props)
    else:
        raise Exception(f"Unknown node type {node.node_type}!")  # pylint:disable=broad-exception-raised

    return pdb_node


def _merge_compute(node: Node, props: dict) -> platdb.PlatDBNode:
    props['platform'] = 'k8s' if node.containerized else 'ipv4'
    address = {'address': props['address']}

    compute = platdb.Compute.create_or_update(address)[0]
    
    for k, v in props.items():
        setattr(compute, k, v)

    app = None
    if node.service_name:
        app = platdb.Application.create_or_update({"name": node.service_name})[0]
        compute.applications.connect(app)

    return compute

def _merge_deployment(node: Node, props: dict) -> platdb.PlatDBNode:
    props['deployment_type'] = 'k8s_deployment'

    deployment = platdb.Deployment.create_or_update(props)[0]

    return deployment

def _merge_resource(node: Node, props: dict) -> platdb.PlatDBNode:
    resource = platdb.Resource.create_or_update(props)

    return resource

def _merge_traffic_controller(node: Node, props: dict) -> platdb.PlatDBNode:
    props['dns_names'] = node.aliases

    tctl = platdb.TrafficController.create_or_update(props)[0]

    return tctl

def connect_nodes(node1: Node, node2: Node):
    _new_connect_nodes(node1, node2)
    _old_connect_nodes(node1, node2)

def _old_connect_nodes(node1: Node, node2: Node):
    """This is just fooey.  When we have a real database it will be saved to the database.  For now, in memory the
         connection is made without having to do a lookup on any of our indices"""
    key = f"{node2.provider}:{node2.address}"
    node1.children[key] = node2

def _new_connect_nodes(parent_node: Node, child_node: Node):
    # Since node objects are being passed in we need to get the PlatDBNode
    # objs from Neo4j
    parent = _load_node_from_neo4j(parent_node)
    child = _load_node_from_neo4j(child_node)

    if not parent or not child:
        logs.logger.error(f'Uh oh the parent or child is a none. Parent then child::',
                          parent, child)
        return

    if isinstance(parent, platdb.Compute):
        _connect_compute(parent, child)
    elif isinstance(parent, platdb.Deployment):
        _connect_deployment(parent, child)
    elif isinstance(parent, platdb.TrafficController):
        _connect_traffic_controller(parent, child)
    else:
        raise Exception(f'The parent in connect node is not being handled it is a {parent.__class__}')  # pylint:disable=broad-exception-raised


def _connect_compute(parent: platdb.PlatDBNode, child: platdb.PlatDBNode):
    if isinstance(child, platdb.Compute):
        parent.compute_to.connect(child)
        parent.compute_from.connect(child)
    elif isinstance(child, platdb.Resource):
        for parent_app in parent.applications.all():
            parent_app.resources.connect(child)
            child.applications.connect(parent_app)
    elif isinstance(child, platdb.TrafficController):
        for parent_app in parent.applications.all():
            parent_app.traffic_controllers.connect(child)
            child.applications.connect(parent_app)
    else:
        raise Exception(f'The child of the compute is not a compute it is a {child.__class__} :: {child}')  # pylint:disable=broad-exception-raised

def _connect_deployment(parent: platdb.Deployment, child: platdb.PlatDBNode):
    if isinstance(child, platdb.Compute):
        parent.computes.connect(child)
        child.deployments.connect(parent)
    else:
        raise Exception(
            'The child in _connect_deployment is not being handled. '
            f'It is of type {child.__class__} :: {child}'
        )  # pylint:disable=broad-exception-raised

def _connect_traffic_controller(parent: platdb.TrafficController, child: platdb.PlatDBNode):
    if isinstance(child, platdb.Deployment):
        parent.deployments.connect(child)
        child.traffic_controllers.connect(parent)
    else:
        raise Exception(
            'The child in _connect_traffic_controller is not being handled. '
            f'It is of type {child.__class__} :: {child}'
        )  # pylint:disable=broad-exception-raised
    

def get_node_by_address(address: str) -> Optional[Node]:
    if address not in _node_index_by_address:
        return None

    return _node_index_by_address[address]


def get_nodes_pending_dnslookup() -> [str, Node]:  # {dns_name: Node()}
    # TODO Lookup all nodes that have alias field populated (aliases are the DNS names)
    # Populate the addresses in the Resources
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
