"""
Module Name: export_mermaid

Description:
Exports to mermaid

License:
SPDX-License-Identifier: Apache-2.0

System Requirements:
- requires system installation of `mmdc` package (npm install -g @mermaid-js/mermaid-cli)
"""
import os
import subprocess
from typing import Dict
from astrolabe import constants, database, exporters
from astrolabe.node import Node

MERMAID_LR = 'LR'
MERMAID_TB = 'TB'
MERMAID_AUTO = 'auto'

# Global variables to keep track of nodes and edges
nodes_compiled = []
edges_compiled = []


class MermaidGraph:
    def __init__(self, direction='auto'):
        self.direction = direction
        self.mermaid_lines = []

    def add_node(self, node_name: str, database=False, container=False, node_classes: list = None):
        """
        Adds a node to the mermaid graph.
        """
        if node_classes is None:
            node_classes = []

        if database:
            node_str = f"    {node_name}[({node_name})]"
        elif container:
            node_str = f"    {node_name}{{{{{node_name}}}}}"
        else:
            node_str = f"    {node_name}[{node_name}]"

        self.mermaid_lines.append(node_str)
        for node_class in node_classes:
            self.mermaid_lines.append(f"    class {node_name} {node_class}")

    def add_edge(self, from_node: str, to_node: str, label: str, blocking: bool):
        """
        Adds an edge between two nodes with an optional label.
        """
        if blocking:
            arrow = f"--{label}-->"
        else:
            arrow = f"-.{label}.->"
        edge_str = f"    {from_node} {arrow} {to_node}"

        self.mermaid_lines.append(edge_str)

    def generate(self):
        """
        Returns the generated Mermaid code as a string.
        """
        direction = self.direction
        if direction == MERMAID_AUTO:
            direction = MERMAID_TB  # Automatically choose the top-to-bottom layout as default

        # Initialize flowchart with direction
        mermaid_code = [f"graph {direction}"]

        # Add styling (if any)
        mermaid_code.extend([
            "    classDef error stroke:#f00",
            "    classDef warning stroke:#f90",
            "    classDef defunct stroke-dasharray:5",
        ])

        # Add all lines
        mermaid_code.extend(self.mermaid_lines)
        return "\n".join(mermaid_code)


class ExporterMermaid(exporters.ExporterInterface):
    @staticmethod
    def ref() -> str:
        return 'mermaid'

    @staticmethod
    def register_cli_args(argparser: exporters.ExporterArgParser):
        argparser.add_argument('--direction',
                               choices=[MERMAID_LR, MERMAID_TB, MERMAID_AUTO],
                               default=MERMAID_AUTO,
                               help='Layout direction for mermaid diagram. '
                                    "LR = Left-to-Right, "
                                    "TB = Top-to-Bottom, "
                                    "auto = automatically chooses the best direction")

    def export(self, tree: Dict[str, Node]):
        # Get the generated Mermaid code
        mermaid_code = export_tree(tree)

        # Create the filename based on the seed names or default seeds
        seed_names = ','.join([node.service_name for node in tree.values() if node.service_name is not None])
        seeds = seed_names or ','.join(constants.ARGS.seeds).replace('.', '-')

        # Define the path where the Mermaid file will be saved
        output_mermaid_file_path = os.path.join(constants.OUTPUTS_DIR, f"astromaid_{seeds}.mmd")

        # Write the Mermaid code to the output file
        with open(output_mermaid_file_path, 'w', encoding='utf8') as mermaid_file:
            mermaid_file.write(mermaid_code)

        # Generate PNG using mmdc
        output_image_path = os.path.join(constants.OUTPUTS_DIR, f"astromaid_{seeds}.svg")
        # pylint:disable=subprocess-run-check
        subprocess.run(["mmdc", "-i", output_mermaid_file_path, "-o", output_image_path])

        # Open the PNG file using qlmanage
        # pylint:disable=subprocess-run-check
        subprocess.run(["qlmanage", "-p", output_image_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class ExporterMermaidSource(exporters.ExporterInterface):
    @staticmethod
    def ref() -> str:
        return 'mermaid_source'

    def export(self, tree: Dict[str, Node]):
        print(export_tree(tree))

    @staticmethod
    def register_cli_args(argparser: exporters.ExporterArgParser):
        argparser.add_argument('--direction',
                               choices=[MERMAID_LR, MERMAID_TB, MERMAID_AUTO],
                               default=MERMAID_AUTO,
                               help='Layout direction for mermaid diagram. '
                                    "LR = Left-to-Right, "
                                    "TB = Top-to-Bottom, "
                                    "auto = automatically chooses the best direction")


def export_tree(tree: Dict[str, Node]) -> str:
    mermaid_graph = MermaidGraph(direction=constants.ARGS.export_mermaid_direction)
    compile_mermaid_diagram(tree, mermaid_graph)

    # Get the generated Mermaid code
    mermaid_code = mermaid_graph.generate()

    return mermaid_code


def compile_mermaid_diagram(tree: Dict[str, Node], mermaid_graph: MermaidGraph) -> None:
    """
    Export tree in Mermaid format. Will write an image file to disk and then open it.
    Optionally, output as Mermaid source code instead of PNG.

    :param tree: The tree to export (services and nodes)
    :param mermaid_graph: The MermaidGraph instance used to generate the code
    :param source: If True, export the Mermaid code as source, not as PNG
    :return: None
    """
    nodes_compiled.clear()
    edges_compiled.clear()

    # Export nodes and connections
    for _, node in tree.items():
        _compile_flowchart(node, mermaid_graph)


def _compile_flowchart(node: Node, mermaid_graph: MermaidGraph) -> None:
    node_name = _node_name(node)
    _compile_node(node, node_name, mermaid_graph)

    children = database.get_connections(node)
    if len(children) > 0:
        merged_children = exporters.merge_hints(children)
        for _, child in merged_children.items():
            if child.warnings.get('DEFUNCT') and constants.ARGS.hide_defunct:
                continue

            child_name = _node_name(child)

            _compile_node(child, child_name, mermaid_graph)
            _compile_edge(node_name, child_name, child.protocol.ref, child.protocol.blocking, mermaid_graph)
            _compile_flowchart(child, mermaid_graph)


def _compile_edge(parent_name: str, child_name: str, label: str, blocking: bool, mermaid_graph: MermaidGraph) -> None:
    edge_str = f"{parent_name}.{label}.{child_name}"
    if edge_str not in edges_compiled:
        mermaid_graph.add_edge(parent_name, child_name, label, blocking)
        edges_compiled.append(edge_str)


def _compile_node(node: Node, name: str, mermaid_graph: MermaidGraph) -> None:
    if name not in nodes_compiled:
        node_classes = []
        if node.errors:
            node_classes.append("error")
        if 'DEFUNCT' in node.warnings:
            node_classes.append("defunct")
        elif node.warnings:
            node_classes.append("warning")

        mermaid_graph.add_node(name, node.is_database(), node.containerized, node_classes)
        nodes_compiled.append(name)


def _node_name(node: Node) -> str:
    name = node.service_name or "UNKNOWN"
    clean_name = exporters.clean_service_name(f"{name}-{node.node_name}")
    clean_name = f"{clean_name}-{node.provider}"
    return clean_name
