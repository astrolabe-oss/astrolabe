"""
Module Name: config

Description:
Read and parse astrolabe specific config files such as network.yaml and Profile Strategy files

License:
SPDX-License-Identifier: Apache-2.0
"""
import os

from typing import Dict, Optional
from datetime import datetime

from astrolabe.node import Node, NodeType
from astrolabe import network, logs, platdb

NEO4J_URI = os.getenv('NEO4J_URI', 'bolt://localhost:7689')
NEO4J_USERNAME = os.getenv('NEO4J_USERNAME', '')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD', '')
NEO4J_CONNECTION = platdb.Neo4jConnection(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))


def init():
    NEO4J_CONNECTION.open()


def close():
    NEO4J_CONNECTION.close()


def _neomodel_to_node(platdb_node: platdb.PlatDBNode) -> Node:
    class_to_node = {
        platdb.Compute: NodeType.COMPUTE,
        platdb.Deployment: NodeType.DEPLOYMENT,
        platdb.Resource: NodeType.RESOURCE,
        platdb.TrafficController: NodeType.TRAFFIC_CONTROLLER,
        platdb.Unknown: NodeType.UNKNOWN
    }

    node = Node(
        profile_strategy_name=platdb_node.profile_strategy_name,
        protocol=network._protocols.get(platdb_node.protocol),  # pylint:disable=protected-access
        protocol_mux=platdb_node.protocol_multiplexor,
        provider=platdb_node.provider,
        containerized=platdb_node.provider == 'k8s',
        from_hint=False,  # No hints in the sandbox for now
        public_ip=platdb_node.public_ip,
        address=platdb_node.address,
        service_name=platdb_node.app_name,
        node_name=platdb_node.name,
        warnings=platdb_node.profile_warnings,
        errors=platdb_node.profile_errors,
        _profile_timestamp=platdb_node.profile_timestamp,
        _profile_lock_time=platdb_node.profile_lock_time,
        node_type=class_to_node[platdb_node.__class__],
        cluster=platdb_node.cluster
    )

    if hasattr(platdb_node, 'ipaddrs'):
        node.ipaddrs = platdb_node.ipaddrs

    if hasattr(platdb_node, 'dns_names'):
        node.aliases = platdb_node.dns_names

    if hasattr(platdb_node, 'platform'):
        node.containerized = platdb_node.platform == 'k8s'

    return node


def save_node(node: Node) -> Node:
    protocol = None

    if node.protocol and node.protocol.ref:
        protocol = node.protocol.ref

    props = {
        'name': node.node_name,
        'app_name': node.service_name,
        'address': node.address,
        'profile_strategy_name': node.profile_strategy_name,
        'protocol': protocol,
        'protocol_multiplexor': node.protocol_mux,
        'profile_timestamp': node.get_profile_timestamp(),
        'profile_lock_time': node.get_profile_lock_time(),
        'provider': node.provider,
        'public_ip': node.public_ip,
        'profile_warnings': node.warnings,
        'profile_errors': node.errors,
        'cluster': node.cluster
    }

    # NOTE Node.node_type defaults to COMPUTE
    if node.node_type == NodeType.COMPUTE:
        pdb_node = _merge_compute(node, props)
    elif node.node_type == NodeType.DEPLOYMENT:
        pdb_node = _merge_deployment(node, props)
    elif node.node_type == NodeType.RESOURCE:
        pdb_node = _merge_resource(node, props)
    elif node.node_type == NodeType.TRAFFIC_CONTROLLER:
        pdb_node = _merge_traffic_controller(node, props)
    elif node.node_type == NodeType.UNKNOWN:
        pdb_node = _merge_unknown(node, props)
    else:
        raise Exception(f"Unknown node type {node.node_type}!")  # pylint:disable=broad-exception-raised

    return _neomodel_to_node(pdb_node)


def _merge_compute(node: Node, props: dict) -> platdb.PlatDBNode:
    props['platform'] = 'k8s' if node.containerized else 'ipv4'
    compute = platdb.Compute.create_or_update(props)[0]

    return compute


def _merge_deployment(node: Node, props: dict) -> platdb.PlatDBNode:  # pylint:disable=unused-argument
    props['deployment_type'] = 'k8s_deployment' if node.provider == 'k8s' else 'aws_asg'
    deployment = platdb.Deployment.create_or_update(props)[0]

    if node.service_name:
        app = platdb.Application.create_or_update(
            {
                "name": node.service_name,
                "app_name": node.service_name,
            }
        )[0]
        deployment.application.replace(app)
        app.deployments.connect(deployment)

    return deployment


def _merge_resource(node: Node, props: dict) -> platdb.PlatDBNode:
    props['dns_names'] = node.aliases
    resource = platdb.Resource.create_or_update(props)[0]

    return resource


def _merge_traffic_controller(node: Node, props: dict) -> platdb.PlatDBNode:
    props['dns_names'] = node.aliases
    props['ipaddrs'] = node.ipaddrs
    tctl = platdb.TrafficController.create_or_update(props)[0]

    return tctl


def _merge_unknown(_: Node, props: dict) -> platdb.PlatDBNode:
    unknown = platdb.Unknown.create_or_update(props)[0]

    return unknown


def connect_nodes(parent_node: Node, child_node: Node):
    parent = _load_node_from_neo4j(parent_node)
    child = _load_node_from_neo4j(child_node)

    if not parent or not child:
        logs.logger.error('Failed to load nodes from neo4j! Parent: %s, child: %s', parent, child)
        return

    if isinstance(parent, platdb.Compute):
        _connect_compute(parent, child)
        return

    if isinstance(parent, platdb.Deployment):
        _connect_deployment(parent, child)
        return

    if isinstance(parent, platdb.TrafficController):
        _connect_traffic_controller(parent, child)
        return

    # pylint:disable=broad-exception-raised
    raise Exception(f'The parent in connect node is not being handled it is a {parent.__class__}')


def _connect_compute(parent: platdb.PlatDBNode, child: platdb.PlatDBNode):
    if isinstance(child, platdb.Compute):
        parent.downstream_computes.connect(child)
        return

    if isinstance(child, platdb.Resource):
        for parent_deployment in parent.deployment.all():
            parent_deployment.resources.connect(child)
        return

    if isinstance(child, platdb.Deployment):
        for parent_deployment in parent.deployment.all():
            parent_deployment.downstream_deployments.connect(child)
        return

    if isinstance(child, platdb.TrafficController):
        for parent_deployment in parent.deployment.all():
            parent_deployment.downstream_traffic_ctrls.connect(child)
        return

    if isinstance(child, platdb.Unknown):
        parent.downstream_unknowns.connect(child)
        return

    raise Exception(  # pylint:disable=broad-exception-raised
        f'The child of the compute is not handled. It is a {child.__class__} :: {child}'
    )


def _connect_deployment(parent: platdb.Deployment, child: platdb.PlatDBNode):
    if isinstance(child, platdb.Compute):
        parent.computes.connect(child)
        return

    raise Exception(  # pylint:disable=broad-exception-raised
        'The child in _connect_deployment is not being handled. '
        f'It is of type {child.__class__} :: {child}'
    )


def _connect_traffic_controller(parent: platdb.TrafficController, child: platdb.PlatDBNode):
    if isinstance(child, platdb.Deployment):
        parent.downstream_deployments.replace(child)
        return

    raise Exception(  # pylint:disable=broad-exception-raised
        'The child in _connect_traffic_controller is not being handled. '
        f'It is of type {child.__class__} :: {child}'
    )


# pylint:disable=broad-exception-raised
def get_connections(node: Node) -> Dict[str, Node]:
    """This method is directional - we are only getting downstream nodes from this node"""
    # Load the platdb_node from Neo4j using its unique properties
    platdb_node = _load_node_from_neo4j(node)

    if not platdb_node:
        logs.logger.error("Node not found in Neo4j: %s", node)
        return {}

    # Determine the type of `platdb_node` and call the appropriate helper
    if isinstance(platdb_node, platdb.TrafficController):
        return _get_traffic_controller_connections(platdb_node)
    elif isinstance(platdb_node, platdb.Resource):
        return _get_resource_connections(platdb_node)
    elif isinstance(platdb_node, platdb.Deployment):
        return _get_deployment_connections(platdb_node)
    elif isinstance(platdb_node, platdb.Compute):
        return _get_compute_connections(platdb_node)
    elif isinstance(platdb_node, platdb.Unknown):
        return {}
    else:
        raise Exception(f"Unsupported node type for getting connections: {type(platdb_node).__name__}")


def _get_traffic_controller_connections(node: platdb.TrafficController) -> Dict[str, Node]:
    """Since this is directional - we only want connections in the directions requests flow through
        load balancers... as in: the downstream ASGs, deployments, etc..."""
    connections = {}
    for deployment in node.downstream_deployments.all():
        connected_node = _neomodel_to_node(deployment)
        _add_connection(connections, connected_node)
    return connections


def _get_resource_connections(_node: platdb.Resource) -> Dict[str, Node]:
    """Resources currently have no downstream connections"""
    return {}


def _get_deployment_connections(node: platdb.Deployment) -> Dict[str, Node]:
    """Since this is direcitonal - we only want the compute nodes associated iwth a deployment,
       not the upstream traffic controllers..."""
    connections = {}
    for compute in node.computes.all():
        connected_node = _neomodel_to_node(compute)
        _add_connection(connections, connected_node)
    return connections


def _get_compute_connections(node: platdb.Compute) -> Dict[str, Node]:
    """In the real world, downstream compute connections are to Resources and TrafficControllers.  However,
       in our neomodel model - we have a "virtual" Node called Application which we must step through.

       Also - until we have UNKNOWN Node type... sometimes compute have a downstream Compute which is our
       current (incorrect) default Node type"""
    connections = {}
    for downstream_compute in node.downstream_computes.all():
        connected_node = _neomodel_to_node(downstream_compute)
        _add_connection(connections, connected_node)
    for downstream_unknowns in node.downstream_unknowns.all():
        connected_node = _neomodel_to_node(downstream_unknowns)
        _add_connection(connections, connected_node)
    for deployment in node.deployment.all():
        for resource in deployment.resources.all():
            d_connected_node = _neomodel_to_node(resource)
            _add_connection(connections, d_connected_node)
        for d_deployment in deployment.downstream_deployments.all():
            d_connected_node = _neomodel_to_node(d_deployment)
            _add_connection(connections, d_connected_node)
        for d_tc in deployment.downstream_traffic_ctrls.all():
            d_connected_node = _neomodel_to_node(d_tc)
            _add_connection(connections, d_connected_node)
    return connections


# Utility function to handle adding connections while avoiding duplicates or recursion
def _add_connection(connections: Dict[str, Node], connected_node: Node) -> None:
    key = f"{connected_node.provider}:{connected_node.address or ','.join(connected_node.aliases)}"
    connections[key] = connected_node


def _load_node_from_neo4j(node: Node) -> Optional[platdb.PlatDBNode]:
    node_type_to_class = {
        NodeType.COMPUTE: platdb.Compute,
        NodeType.DEPLOYMENT: platdb.Deployment,
        NodeType.RESOURCE: platdb.Resource,
        NodeType.TRAFFIC_CONTROLLER: platdb.TrafficController,
        NodeType.UNKNOWN: platdb.Unknown
    }

    cls = node_type_to_class[node.node_type]

    # Try to query based of address but if address is not set yet than use DNS names
    try:
        obj = cls.nodes.get(**{'address': node.address})
    except platdb.DoesNotExist:
        obj = cls.nodes.get(**{'dns_names': node.aliases})

    return obj


def get_nodes_unprofiled(since: datetime) -> Dict[str, Node]:
    """Query for unprofiled nodes, where the node has never been profiled, or the
       node has not been profiled **since** the passed in timestamp"""
    node_class = [platdb.Compute, platdb.Deployment, platdb.Resource, platdb.TrafficController, platdb.Unknown]
    results = {}

    for cls in node_class:
        # Add the additional filter for profile_timestamp
        nodes = cls.nodes.filter(
            (platdb.Q(profile_timestamp__isnull=True) |
             platdb.Q(profile_timestamp__lt=since)) &
            platdb.Q(address__isnull=False)
        )

        for pdb_node in nodes:
            node = _neomodel_to_node(pdb_node)
            ref = f"{node.provider}:{node.node_type}:{node.address or ','.join(node.aliases)}"
            results[ref] = node

    return results


def get_node_by_address(address: str) -> Optional[Node]:
    query = """
    MATCH (n)
    WHERE n.address = $address OR $address IN n.ipaddrs
    RETURN n
    """
    results, _ = platdb.db.cypher_query(query, {"address": address})

    if len(results) == 0 or len(results[0]) == 0:
        return None

    if len(results) > 1 or len(results[0]) > 1:
        raise Exception(  # pylint:disable=broad-exception-raised
            f"To many things were returned from get_node_by_address for address {address} Results: {results}"
        )

    cls: str = list(results[0][0].labels)[0]
    neomodel_node = results[0][0]

    neomodel_classes = {
        "Compute": platdb.Compute,
        "Deployment": platdb.Deployment,
        "Resource": platdb.Resource,
        "TrafficController": platdb.TrafficController,
        "Unknown": platdb.Unknown
    }

    obj = neomodel_classes[cls].inflate(neomodel_node)

    return _neomodel_to_node(obj)


def get_nodes_pending_dnslookup() -> Dict[str, Node]:  # {dns_name: Node()}
    # Give all the nodes that have ANY dns name AKA alias and don't have address field
    query = """
    MATCH (n)
    WHERE n.dns_names IS NOT NULL AND n.address IS NULL
    RETURN n
    """
    res = {}
    neomodel_classes = {
        "Compute": platdb.Compute,
        "Deployment": platdb.Deployment,
        "Resource": platdb.Resource,
        "TrafficController": platdb.TrafficController
    }

    results, _ = platdb.db.cypher_query(query)

    for result in results:
        if len(result) > 1:
            raise Exception(  # pylint:disable=broad-exception-raised
                f'Cannot explain why result in get_nodes_pending_dnslookup has more than 1 element: {result}'
            )

        cls: str = list(result[0].labels)[0]
        dns_name = result[0]['dns_names'][0]
        neomodel_node = result[0]
        obj = neomodel_classes[cls].inflate(neomodel_node)
        node = _neomodel_to_node(obj)

        res[dns_name] = node

    return res.items()


def node_is_k8s_load_balancer(address: str) -> bool:
    traffic_controllers = platdb.TrafficController.nodes.filter(address=address, provider="k8s")

    if len(traffic_controllers) == 1:
        return True
    elif len(traffic_controllers) > 1:
        raise Exception(  # pylint:disable=broad-exception-raised
            f"Multiple traffic controllers with address {address} in node is k8s load balancer"
        )
    else:
        return False


def node_is_k8s_service(address: str) -> bool:
    deployments = platdb.Deployment.nodes.filter(address=address, provider="k8s")

    if len(deployments) == 1:
        return True
    elif len(deployments) > 1:
        # pylint:disable=broad-exception-raised
        raise Exception(f"Multiple traffic controllers with address {address} in node is k8s load balancer")
    else:
        return False
