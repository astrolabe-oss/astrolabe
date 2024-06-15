"""
Module Name: export_neo4j

Description:
Exports nodes in ascii tree format to the STDOUT

Copyright:
Copyright 2024 Magellanbot, Inc

License:
SPDX-License-Identifier: Apache-2.0
"""

from typing import Dict, Any, List

from astrolabe import constants, exporters
from astrolabe.node import Node

from neo4j import GraphDatabase, Record, Driver
uri = "bolt://localhost:7687"
user = "neo4j"
password = "password"

driver: Driver


class ExporterNeo4j(exporters.ExporterInterface):
    @staticmethod
    def ref() -> str:
        return 'neo4j'

    def export(self, tree: Dict[str, Node]):
        global driver
        driver = GraphDatabase.driver(uri, auth=(user, password))
        export_tree(tree)
        driver.close()

    @staticmethod
    def register_cli_args(argparser: exporters.ExporterArgParser):
        argparser.add_argument('--address', help='Neo4j server address. defaults to neo4j://localhost:7687')
        argparser.add_argument('--username', help='Neo4j username')
        argparser.add_argument('--password', help='Neo4j password')


def export_tree(tree: Dict[str, Node]) -> None:
    for node_ref, node in tree.items():
        _merge_node_and_children(node)


def _merge_node_and_children(node: Node) -> None:
    _neo4j_merge_single_node(node)
    if node.children:
        children = exporters.merge_hints(node.children)  # this is a non-neo4j "merge"
        for child_ref, child in children.items():
            child: Node
            _neo4j_merge_single_node(child)
            _neo4j_merge_relationships(node, child)
            _merge_node_and_children(child)


def _execute_query(query: str, parameters: Dict[str, Any] = None) -> List[Record]:
    with driver.session() as session:
        result = session.run(query, parameters)
        return [record for record in result]


def _neo4j_merge_single_node(node: Node):
    # Define the Cypher query
    query = """
    MERGE (c:Compute {address: $compute_address, protocol: $compute_protocol})
    ON CREATE SET c.created = timestamp()
    ON MATCH SET c.lastSeen = timestamp()
    MERGE (a:Application {name: $app_name})
    ON CREATE SET a.created = timestamp()
    ON MATCH SET a.lastSeen = timestamp()
    MERGE (c)-[:RUNS]->(a)
    """

    # Define the parameters
    parameters = {
        "compute_address": node.address,
        "compute_protocol": 'k8s' if node.containerized else 'ipv4',
        "app_name": node.service_name
    }

    # execute
    results = _execute_query(query, parameters)

    # take this out
    for record in results:
        print(record)


def _neo4j_merge_relationships(node: Node, child_node: Node):
    # Define the Cypher query
    query = """
    MATCH (c1:Compute {address: $compute1_address, protocol: $compute1_protocol})
    MATCH (a1:Application {name: $app1_name})
    MATCH (c2:Compute {address: $compute2_address, protocol: $compute2_protocol})
    MATCH (a2:Application {name: $app2_name})
    MERGE (c1)-[:CALLS]->(c2)
    MERGE (a1)-[:CALLS]->(a2)
    """

    # Define the parameters
    parameters = {
        "compute1_address": node.address,
        "compute1_protocol": 'k8s' if node.containerized else 'ipv4',
        "app1_name": node.service_name,
        "compute2_address": child_node.address,
        "compute2_protocol": 'k8s' if child_node.containerized else 'ipv4',
        "app2_name": child_node.service_name
    }

    # execute
    results = _execute_query(query, parameters)

    # take this out
    for record in results:
        print(record)
