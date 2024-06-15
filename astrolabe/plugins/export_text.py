"""
Module Name: export_text

Description:
Exports to basic text output

Copyright:
Copyright 2024 Magellanbot, Inc

License:
SPDX-License-Identifier: Apache-2.0
"""

from astrolabe import node, exporters
from typing import Dict

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
    if not tree_node.children:
        return

    for child in tree_node.children.values():
        relationship = f"{tree_node.service_name or 'UNKNOWN'} --[{child.protocol.ref}]--> " \
                       f"{child.service_name or 'UNKNOWN'} ({child.protocol_mux})"
        if relationship not in flat_relationships:
            flat_relationships[relationship] = (tree_node, child)
        build_flat_services(child)