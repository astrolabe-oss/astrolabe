"""
Module Name: export_text

Description:
Exports to basic text output

License:
SPDX-License-Identifier: Apache-2.0
"""

from typing import Dict

from astrolabe import node, exporters, database

flat_relationships = {}


class ExporterGraphvizSource(exporters.ExporterInterface):
    @staticmethod
    def ref() -> str:
        return 'text'

    def export(self, tree: Dict[str, node.Node]):
        export_tree(tree)


def export_tree(tree: Dict[str, node.Node]) -> None:
    for tree_node in tree.values():
        build_flat_services(tree_node)

    for relationship in sorted(flat_relationships):
        print(relationship)


def build_flat_services(tree_node: node.Node) -> None:
    children = database.get_connections(tree_node)
    if len(children) < 1:
        return

    for child in children.values():
        relationship = (f"{tree_node.service_name or 'UNKNOWN'} ({tree_node.node_name}) "
                        f"--[{child.protocol.ref}:{child.protocol_mux}]--> "
                        f"{child.service_name or child.address} ({child.node_name})")
        if relationship not in flat_relationships:
            flat_relationships[relationship] = (tree_node, child)
        build_flat_services(child)
