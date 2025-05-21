"""
Module Name: platdb

Description:
Defines the PlatDB schema for a Neo4J neomodel database, as well as several access methods.

License:
SPDX-License-Identifier: Apache-2.0
"""
import datetime
import importlib

from typing import Any, Optional

import neo4j

from neo4j import GraphDatabase
from neomodel import (    # pylint: disable=unused-import
    ArrayProperty,
    BooleanProperty,
    DoesNotExist,
    DateTimeProperty,
    JSONProperty,
    RelationshipFrom,
    RelationshipTo,
    StringProperty,
    StructuredNode,
    ZeroOrOne,
    ZeroOrMore,
    db
)

# Q is required for neomodel queries to work correctly, even if not directly referenced in this file
from neomodel import Q  # noqa: F401 pylint: disable=unused-import

from neomodel.properties import Property


class Neo4jConnection:
    def __init__(self, uri: str, database: str, auth: tuple[str, str]):
        self._uri = uri
        self._auth = auth
        self._database = database
        self._driver = None

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def open(self):
        self._driver = GraphDatabase.driver(self._uri, auth=self._auth, database=self._database)
        db.set_connection(self._uri, self._driver)

        # Clear sensitive information
        self._auth = None

        return self

    def close(self):
        self._driver.close()

    def get_full_graph_as_json(self) -> tuple[dict, list]:  
        vertices = {}
        edges = []
        platdb_module = importlib.import_module('astrolabe.platdb')

        results, _ = db.cypher_query(
            """
            MATCH (parent)-[edge]->(child) 
            RETURN 
                parent, labels(parent) AS parent_type, 
                edge, type(edge) AS edge_type, 
                child, labels(child) AS child_type
            """
        )

        for row in results:
            parent, parent_type, edge, edge_type, child, child_type = row
            parent_type = parent_type[0]
            child_type = child_type[0]

            if parent.element_id not in vertices:
                vertices[parent.element_id] = self._create_platdb_ht(
                    platdb_module=platdb_module,
                    platdb_type=parent_type,
                    vertex=parent)

            if child.element_id not in vertices:
                vertices[child.element_id] = self._create_platdb_ht(
                    platdb_module=platdb_module,
                    platdb_type=child_type,
                    vertex=child)

            edges.append({
                "start_node": parent.element_id,
                "end_node": child.element_id,
                "type": edge_type,
                "properties": dict(edge)
            })

        return vertices, edges

    def _create_platdb_ht(
            self, 
            platdb_module: Any, 
            platdb_type: str, 
            vertex: neo4j.graph.Node
    ) -> dict:
        platdb_cls = getattr(platdb_module, platdb_type)
        platdb_obj = platdb_cls.inflate(vertex)
        platdb_ht = platdb_obj.platdbnode_to_dict()
        platdb_ht['type'] = platdb_type

        return platdb_ht


class PlatDBNode(StructuredNode):
    __abstract_node__ = True  # prevents neo4j from adding `PlatDBNode` as a "label" in the graph db
    profile_timestamp: Optional[datetime.datetime] = DateTimeProperty()
    profile_lock_time: Optional[datetime.datetime] = DateTimeProperty()

    # Attributes that are being added to maintain the Node obj in Astrolabe
    profile_strategy_name = StringProperty()
    provider = StringProperty()
    app_name = StringProperty()

    # New fields to mirror `warnings` and `errors` in Astrolabe Node class
    profile_warnings = JSONProperty(default={})
    profile_errors = JSONProperty(default={})

    @classmethod
    def delete_by_attributes(cls, attributes: dict) -> bool:
        try:
            obj = cls.nodes.get(**attributes)  # pylint: disable=no-member
            return super(PlatDBNode, obj).delete()
        except DoesNotExist:
            return False

    @classmethod
    def update(cls, attributes: dict, new_attributes: dict
               ) -> Optional["PlatDBNode"]:
        """TODO: Is this method used anywhere? Defunct?"""
        try:
            obj = cls.nodes.get(**attributes)  # pylint: disable=no-member

            for key, value in new_attributes.items():
                setattr(obj, key, value)

            obj.save()

            return obj
        except DoesNotExist:
            return None

    @classmethod
    def create_or_update(cls, *props, **kwargs):
        """We have to do this because apparently neomodel library does not null-out an attribute
           when you try to update an existing attribute with a None/null replacement!"""
        instances = super().create_or_update(*props, **kwargs)

        # Check each instance to ensure profile_lock_time is set to None if specified
        for instance, prop in zip(instances, props):
            if 'profile_lock_time' in prop and prop['profile_lock_time'] is None:
                instance.profile_lock_time = None
                instance.save()  # Persist the explicit None value

        return instances

    def platdbnode_to_dict(self):
        data = {}

        for attr in dir(self):
            obj_attr = getattr(self.__class__, attr, None)

            # Only want to keep neomodel Property objects and Relationships
            # Any other attribute present in the object should be ignored
            if isinstance(obj_attr, Property):
                data[attr] = getattr(self, attr)
            elif isinstance(obj_attr, (RelationshipTo, RelationshipFrom)):
                data[attr] = [rel.element_id for rel in getattr(self, attr).all()]

        return data


class Application(PlatDBNode):
    name = StringProperty(unique_index=True)

    # Application-Deployment relationships
    deployments = RelationshipTo('Deployment', 'IMPLEMENTED_BY', cardinality=ZeroOrMore)


class PlatDBNetworkNode(PlatDBNode):
    __abstract_node__ = True
    """Base class for nodes with network properties."""
    name = StringProperty()
    address = StringProperty(required=True)
    protocol = StringProperty()
    protocol_multiplexor = StringProperty()
    public_ip = BooleanProperty()
    ipaddrs = ArrayProperty(StringProperty(), null=True)
    cluster = StringProperty()


class Deployment(PlatDBNetworkNode):
    name = StringProperty(unique_index=True)
    cluster = StringProperty(required=True)
    deployment_type = StringProperty(choices={
        "aws_asg": "AWS Auto Scaling Group",
        "k8s_deployment": "K8s Deployment"})

    # Relationships
    application = RelationshipFrom('Application', 'IMPLEMENTED_BY', cardinality=ZeroOrOne)
    computes = RelationshipTo('Compute', 'HAS_MEMBER', cardinality=ZeroOrMore)
    traffic_controller = RelationshipFrom('TrafficController', 'FORWARDS_TO',
                                          cardinality=ZeroOrOne)
    downstream_traffic_ctrls = RelationshipTo('TrafficController', 'CALLS', cardinality=ZeroOrMore)
    downstream_deployments = RelationshipTo('Deployment', 'CALLS', cardinality=ZeroOrMore)
    upstream_deployments = RelationshipFrom('Deployment', 'CALLS', cardinality=ZeroOrMore)
    resources = RelationshipTo('Resource', 'CALLS', cardinality=ZeroOrMore)


class Compute(PlatDBNetworkNode):
    platform = StringProperty()

    # Relationships
    deployment = RelationshipFrom('Deployment', 'HAS_MEMBER', cardinality=ZeroOrMore)

    # I Think we need to get rid of or refactor this, and corresponding database.py usages
    downstream_computes = RelationshipTo('Compute', 'CALLS', cardinality=ZeroOrMore)
    upstream_computes = RelationshipFrom('Compute', 'CALLS', cardinality=ZeroOrMore)
    downstream_unknowns = RelationshipTo('Unknown', 'CALLS', cardinality=ZeroOrMore)


class Unknown(PlatDBNetworkNode):
    upstream_computes = RelationshipFrom('Compute', 'CALLED_BY', cardinality=ZeroOrMore)


class PlatDBDNSNode(PlatDBNetworkNode):
    __abstract_node__ = True
    address = StringProperty(unique_index=True, null=True, required=False)
    dns_names = ArrayProperty(StringProperty(), unique_index=True, null=True)

    # pylint:disable=arguments-differ
    @classmethod
    def create_or_update(cls, data):  # NOQA
        """For PlatDBDNSNode, sometimes we have the address and not the dns names, sometimes we have the dns_names and
             not the address.  However, address:dns_names is a natural unique key.  So we cannot specify unique and null
             in neomodel - so as you see here we create that constraint programmatically in the application layer"""
        # MUST HAVE ADDRESS OR DNS_NAMES
        address = data.get('address', None)
        dns_names = data.get('dns_names', [])
        if not address and not dns_names:
            # pylint:disable=broad-exception-raised
            raise Exception('neomodel Resource type must have either address or dns_names fields set to save!')

        # TRY TO FIND BY ADDRESS
        existing_resource = None
        if address:
            try:
                existing_resource = cls.nodes.get(address=address)
            except DoesNotExist:
                pass

        # IF NOT, TRY TO FIND BY DNS_NAMES
        if not existing_resource:
            # No current way to run this query in neomodel!  https://github.com/neo4j-contrib/neomodel/issues/379
            all_resources = cls.nodes.all()
            if len(all_resources) > 0:
                for resource in all_resources:
                    for dns_name in dns_names:
                        if resource.dns_names and dns_name in resource.dns_names:
                            existing_resource = resource 
                            continue

        # IF NOT, MUST BE A NEW RESOURCE TO INSERT!
        if not existing_resource:
            new_resource = cls(**data)
            new_resource.save()
            return [new_resource]

        # OTHERWISE, "UPDATE" EXISTING
        for k, v in data.items():
            setattr(existing_resource, k, v)

        existing_resource.save()
        return [existing_resource]


class TrafficController(PlatDBDNSNode):
    # Relationships
    downstream_deployments = RelationshipTo('Deployment', 'FORWARDS_TO', cardinality=ZeroOrOne)
    upstream_deployments = RelationshipFrom('Deployment', 'CALLS', cardinality=ZeroOrMore)


class Resource(PlatDBDNSNode):
    # Relationships
    upstreams = RelationshipFrom('Deployment', 'CALLS', cardinality=ZeroOrMore)
