import os

from typing import Dict, Optional

from corelib import platdb

from astrolabe.node import Node, NodeType
from astrolabe import network, logs

NEO4J_URI = os.getenv('NEO4J_URI', 'bolt://localhost:7689')
NEO4J_USERNAME = os.getenv('NEO4J_USERNAME', '')
NEO4J_PASSWORD = os.getenv('NEO4J_PASSWORD', '')
NEO4J_CONNECTION = platdb.Neo4jConnection(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD))


def init():
    NEO4J_CONNECTION.open()


def close():
    NEO4J_CONNECTION.close()


def neomodel_to_node(platdb_node: platdb.PlatDBNode) -> Node:
    class_to_node = {
        platdb.Compute: NodeType.COMPUTE,
        platdb.Deployment: NodeType.DEPLOYMENT,
        platdb.Resource: NodeType.RESOURCE,
        platdb.TrafficController: NodeType.TRAFFIC_CONTROLLER
    }

    # TODO if platdb_node is Compute then fill service_name with child App
    # Apps might be able to be ignored because they are kinda virtual

    node = Node(
        profile_strategy_name=platdb_node.profile_strategy_name,
        protocol=network._protocols.get(platdb_node.protocol),  # pylint:disable=protected-access
        protocol_mux=platdb_node.protocol_multiplexor,
        provider=platdb_node.provider,
        containerized=False,  # I don't know what else to put here
        from_hint=False,  # No hints in the sandbox for now
        address=platdb_node.address,
        service_name=platdb_node.name,
        _profile_timestamp=platdb_node.profile_timestamp,
        _profile_lock_time=platdb_node.profile_lock_time,
        node_type=class_to_node[platdb_node.__class__]
    )

    if hasattr(platdb_node, 'dns_names'):
        node.aliases = platdb_node.dns_names

    return node


def save_node(node: Node) -> Node:
    protocol = None

    if node.protocol and node.protocol.ref:
        protocol = node.protocol.ref

    props = {
        'name': node.service_name,
        'address': node.address,
        'profile_strategy_name': node.profile_strategy_name,
        'protocol': protocol,
        'protocol_multiplexor': node.protocol_mux,
        'profile_timestamp': node.get_profile_timestamp(),
        'profile_lock_time': node.get_profile_lock_time(),
        'provider': node.provider
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
    else:
        raise Exception(f"Unknown node type {node.node_type}!")  # pylint:disable=broad-exception-raised

    return neomodel_to_node(pdb_node)


def _merge_compute(node: Node, props: dict) -> platdb.PlatDBNode:
    props['platform'] = 'k8s' if node.containerized else 'ipv4'
    compute = platdb.Compute.create_or_update(props)[0]

    if node.service_name:
        app = platdb.Application.create_or_update({"name": node.service_name})[0]
        compute.applications.connect(app)

    return compute


def _merge_deployment(node: Node, props: dict) -> platdb.PlatDBNode:  # pylint:disable=unused-argument
    # TODO: this is not always the case anymore... we also have "auto_scaling_group"!
    props['deployment_type'] = 'k8s_deployment' if node.provider == 'k8s' else 'auto_scaling_group'
    deployment = platdb.Deployment.create_or_update(props)[0]

    return deployment


def _merge_resource(node: Node, props: dict) -> platdb.PlatDBNode:
    props['dns_names'] = node.aliases
    resource = platdb.Resource.create_or_update(props)[0]

    return resource


def _merge_traffic_controller(node: Node, props: dict) -> platdb.PlatDBNode:
    props['dns_names'] = node.aliases
    tctl = platdb.TrafficController.create_or_update(props)[0]

    return tctl


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


def _load_node_from_neo4j(node: Node) -> Optional[platdb.PlatDBNode]:
    node_type_to_class = {
        NodeType.COMPUTE: platdb.Compute,
        NodeType.DEPLOYMENT: platdb.Deployment,
        NodeType.RESOURCE: platdb.Resource,
        NodeType.TRAFFIC_CONTROLLER: platdb.TrafficController
    }

    cls = node_type_to_class[node.node_type]

    # Try to query based of address but if address is not set yet than use DNS names
    try:
        obj = cls.nodes.get(**{'address': node.address})
    except platdb.DoesNotExist:
        obj = cls.nodes.get(**{'dns_names': node.aliases})

    return obj


def _connect_compute(parent: platdb.PlatDBNode, child: platdb.PlatDBNode):
    if isinstance(child, platdb.Compute):
        parent.compute_to.connect(child)
        parent.compute_from.connect(child)
        return

    if isinstance(child, platdb.Resource):
        for parent_app in parent.applications.all():
            parent_app.resources.connect(child)
            child.applications.connect(parent_app)
        return

    if isinstance(child, platdb.TrafficController):
        for parent_app in parent.applications.all():
            parent_app.traffic_controllers.connect(child)
            child.applications.connect(parent_app)
        return

    raise Exception(  # pylint:disable=broad-exception-raised
        f'The child of the compute is not a compute it is a {child.__class__} :: {child}'
    )


def _connect_deployment(parent: platdb.Deployment, child: platdb.PlatDBNode):
    if isinstance(child, platdb.Compute):
        parent.computes.connect(child)
        child.deployments.connect(parent)
        return

    raise Exception(  # pylint:disable=broad-exception-raised
        'The child in _connect_deployment is not being handled. '
        f'It is of type {child.__class__} :: {child}'
    )


def _connect_traffic_controller(parent: platdb.TrafficController, child: platdb.PlatDBNode):
    if isinstance(child, platdb.Deployment):
        parent.deployments.connect(child)
        child.traffic_controllers.connect(parent)
        return

    raise Exception(  # pylint:disable=broad-exception-raised
        'The child in _connect_traffic_controller is not being handled. '
        f'It is of type {child.__class__} :: {child}'
    )


def get_nodes_unprofiled() -> Dict[str, Node]:
    node_class = [platdb.Compute, platdb.Deployment, platdb.Resource, platdb.TrafficController]
    results = {}

    for cls in node_class:
        nodes = cls.nodes.filter(
            platdb.Q(profile_timestamp__isnull=True) & platdb.Q(address__isnull=False)
        )

        for node in nodes:
            results[node.element_id_property] = neomodel_to_node(node)

    return results


def get_node_by_address(address: str) -> Optional[Node]:
    query = """
    MATCH (n)
    WHERE n.address = $address
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
        "TrafficController": platdb.TrafficController
    }

    obj = neomodel_classes[cls].inflate(neomodel_node)

    return neomodel_to_node(obj)


def get_nodes_pending_dnslookup() -> [str, Node]:  # {dns_name: Node()}
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
        node = neomodel_to_node(obj)

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
