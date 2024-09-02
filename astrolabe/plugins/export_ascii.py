"""
Module Name: export_ascii

Description:
Exports nodes in ascii tree format to the STDOUT

Copyright:
Copyright 2024 Magellanbot, Inc

License:
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import sys
from collections import namedtuple
from dataclasses import asdict
from typing import List, Dict

from termcolor import colored
from termcolor.termcolor import Color

from astrolabe import constants, logs, exporters
from astrolabe.node import Node


def colored_force(text: str, color: Color) -> str:
    """We are only doing this because tests fail if we don't force_color=True
    due to a tty check in termcolor, and that we haven't figured out the secret
    sauce to monkeypatching sys.stdin.istty() via fixture in tests where there
    is no real tty!"""
    return colored(text, color, force_color=True)


class ExporterAscii(exporters.ExporterInterface):
    @staticmethod
    def ref() -> str:
        return 'ascii'

    def export(self, tree: Dict[str, Node]):
        asyncio.get_event_loop().run_until_complete(export_tree(tree, [], sys.stdout))

    @staticmethod
    def register_cli_args(argparser: exporters.ExporterArgParser):
        argparser.add_argument('--verbose', action='store_true', help='Verbose mode for ascii exporter')


live_export_lock = asyncio.Lock()
Ancestor = namedtuple('Ancestor', 'last_sibling spacing')

_SLEEP_FOR_HUMANS_SECONDS: float = .01
_SLEEP_FOR_HUMANS_COUNTER = 0


async def export_tree(nodes: Dict[str, Node], parents: List[Ancestor], out=sys.stderr,
                      print_slowly_for_humans: bool = False) -> None:
    """
    Export tree during live discovering of the graph.

    For better or for worse... it relies upon the node items it is iterating through
    being mutated elsewhere in the execution of this program.  This is how we achieve
    asynchronous discovery, yet synchronous exporting!

    It waits for 'children' to be added to the node before exporting, indicating
    that requisite stages of the discovering process are complete

    :param nodes: - the tree (or subset thereof) of Node() objects to export
    :param parents: - list of ancestors for the tree - used for exporting depth/context
    :param out: - a file-like object (stream) where to print, defaults to stderr
    :param print_slowly_for_humans: - if we are exporting an already discovered tree, print slowly so humans can see
    :return: None
    """
    await _wait_for_service_names(nodes, len(parents))
    nodes_merged = _merge_nodes_by_service_name(exporters.merge_hints(nodes))

    depth = len(parents)
    nodes_to_export = nodes_merged.copy()
    while len(nodes_to_export) > 0:
        for node_ref in list(sorted(nodes_to_export)):  # list b/c we cannot mutate a dict as we loop
            node = nodes_merged[node_ref]
            if node.warnings.get('DEFUNCT') and constants.ARGS.hide_defunct:
                nodes_to_export.pop(node_ref)
                continue

            if node.profile_complete():
                # this sleep allows human eyes to comprehend output
                if print_slowly_for_humans:
                    await asyncio.sleep(_get_sleep_for_humans_seconds())
                is_last_sibling = 1 == len(nodes_to_export)

                # set up recursive children's parent back-reference
                childrens_ancestors = parents.copy()  # copy isolates branch parents
                childrens_ancestors.append(Ancestor(is_last_sibling, len(node.protocol.ref)))

                # print prefixes
                print_prefix = _export_node_display_prefix(parents)
                error_print_prefix = _export_node_display_prefix(childrens_ancestors)

                # export
                _export_node(node, depth, print_prefix, is_last_sibling, out)
                if constants.ARGS.export_ascii_verbose:
                    _export_node_errs_warns(node, error_print_prefix, out)

                nodes_to_export.pop(node_ref)

                if len(childrens_ancestors) <= constants.ARGS.max_depth and node.children:
                    await export_tree(node.children, childrens_ancestors, out, print_slowly_for_humans)

        # this sleep prevents CPU hoarding
        if (len(nodes_to_export)) > 0:
            await asyncio.sleep(.1)

        if constants.ARGS.debug:
            logs.logger.debug("Waiting for discover to complete for %d nodes at depth %d...",
                              len(nodes_to_export), len(parents))
            logs.logger.debug(nodes_to_export)
            await asyncio.sleep(5)


def _get_sleep_for_humans_seconds() -> float:
    global _SLEEP_FOR_HUMANS_COUNTER, _SLEEP_FOR_HUMANS_SECONDS
    if _SLEEP_FOR_HUMANS_COUNTER == 100:
        _SLEEP_FOR_HUMANS_SECONDS /= 1.2
        _SLEEP_FOR_HUMANS_COUNTER = 0
    _SLEEP_FOR_HUMANS_COUNTER += 1
    return _SLEEP_FOR_HUMANS_SECONDS


def _export_node_display_prefix(parents: List[Ancestor]) -> str:
    """
    Create print prefix which will export the node at the correct indentation on screen

    :param parents: - list of Ancestor objects - informs indentations/formatting
    :return: - the formatted print prefix
    """
    print_prefix = ''
    for i, parent in enumerate(parents):
        if 0 == i:
            print_prefix += ' '
            continue
        parent_branch = ' ' if parent.last_sibling else '|'
        print_prefix += f"{parent_branch}       " + ' ' * parent.spacing

    return print_prefix


def _export_node(node: Node, depth: int, prefix: str, is_last_sibling: bool, out):
    """
    This function does the main work for exporting the node to the screen.

    It formats the various outputs and ultimately prints the node and any associated discovering
    errors.

    :param node:
    :param depth:
    :param prefix:
    :param is_last_sibling:
    :param out: - file-like object to print to (sys.stderr, sys.stdout)
    :return: None
    """
    # service name
    service_name = node.service_name or node.address

    # terminus
    if node.warnings.get('DEFUNCT'):
        terminus = 'x'
    elif node.errors.get('CYCLE'):
        terminus = '>'
    elif node.errors:
        terminus = '?'
    else:
        terminus = '>'

    # branch
    branch = ''
    if depth > 0:
        bud = f"{'└' if is_last_sibling else '|'}" if not node.errors.get('CYCLE') else '<'
        branch += f"{bud}--{node.protocol.ref}--{terminus} "

    # hint display
    info = colored_force('{INFO:FROM_HINT} ', "cyan") if node.from_hint else ''

    # concise warning display
    concise_warnings = ''
    if not constants.ARGS.export_ascii_verbose and node.warnings:
        concise_warnings = colored_force('{WARN:' + '|'.join(node.warnings) + '} ', "yellow")

    # concise error display
    concise_errors = ''
    if not constants.ARGS.export_ascii_verbose and node.errors:
        concise_errors = colored_force('{ERR:' + '|'.join(node.errors) + '} ', "red")

    # newline for SEED nodes
    if 0 == depth:
        print("")

    # protocol mux
    protocol_mux = f"port:{node.protocol_mux}" if node.protocol.blocking and depth > 0 else node.protocol_mux

    # print node
    address = f" ({node.provider}:{node.address})" if constants.ARGS.export_ascii_verbose else ''
    line = f"{prefix}{branch}{info}{concise_warnings}{concise_errors}{service_name} [{protocol_mux}]{address}"
    print(line, file=out)


def _export_node_errs_warns(node: Node, error_prefix: str, out):
    """
    Export errors and warnings for the node on a new line

    :param node:
    :param error_prefix:
    :param out: - file-like object to print to (sys.stderr, sys.stdout)
    :return:
    """
    # errors/warnings
    error_messages = {
        'CONNECT_SKIPPED': f"service detected on {node.protocol.ref}:{node.protocol_mux}, however name discovery"
                           f"and discovering skipped by configuration!",
        'NULL_ADDRESS': f"service '{node.service_name}' detected but an instance address is not available to discover!",
        'TIMEOUT': f"SSH timeout connecting to service:'{node.service_name}' at address: '{node.address}'",
        'CYCLE': f"service '{node.service_name}' discovered as a parent of itself!",
        'PROFILE_SKIPPED': f"service '{node.service_name}' discovered but discovering skipped by configuration"
    }
    warning_messages = {
        'DEFUNCT': f"service '{node.service_name}' configuration present on parent, but it not in use!",
        'NAME_LOOKUP_FAILED': f"Name lookup failed for :'{_synthesize_node_ref(node, 'UNKNOWN')}'"
                              f" at address: '{node.address}'"
    }

    # warnings verbose display
    if node.warnings:
        for warning in node.warnings:
            print(error_prefix + colored_force(f"└> WARN: ({warning}): ", "yellow")
                  + warning_messages[warning], file=out)

    # error verbose display
    if node.errors:
        for error in node.errors:
            print(error_prefix + colored_force(f"└> ERROR: ({error}): ", "red")
                  + error_messages[error], file=out)


async def _wait_for_service_names(nodes: Dict[str, Node], depth: int) -> None:
    """
    Wait for 'service_name' to be discovered in all nodes

    :param nodes:
    :param depth:
    :return: None
    """
    for _ in range(100):
        for node in nodes.values():
            if not node.name_lookup_complete():
                await asyncio.sleep(1)
                break
        else:
            break

        if constants.ARGS.debug:
            remaining = _remaining_nodes_for_debugging(nodes)
            logs.logger.debug("Waiting for remaining %d service names before exporting ascii at depth %d...",
                              len(remaining), depth)
            logs.logger.debug(remaining)
            await asyncio.sleep(5)
    else:
        remaining = _remaining_nodes_for_debugging(nodes)
        print(colored_force(f"Infinite wait interrupted waiting for {len(remaining)} services names for: ", "red"))
        print(colored_force(constants.PP.pformat(remaining), "yellow"))
        sys.exit(1)


def _remaining_nodes_for_debugging(nodes: Dict[str, Node]) -> dict:
    return {node_ref: {**asdict(node), 'discover_strategy': node.profile_strategy.name}
            for node_ref, node in nodes.items() if not node.name_lookup_complete()}


def _merge_nodes_by_service_name(nodes: Dict[str, Node]) -> Dict[str, Node]:
    """
    Return a dict of nodes, merging input nodes with the same protocol and 'service_name'
    into one node.  Merges the associated protocol_mux's

    :param nodes: the unmerged dictionary of Node()s
    :return: the merged dictionary of Node()s
    """
    merged_nodes = {}
    for node_ref, node in nodes.items():
        synthetic_node_ref = _synthesize_node_ref(node, node_ref)
        if synthetic_node_ref not in merged_nodes:
            merged_nodes[synthetic_node_ref] = node
        elif node.protocol_mux not in merged_nodes[synthetic_node_ref].protocol_mux:
            merged_nodes[synthetic_node_ref].protocol_mux = ','.join(
                [merged_nodes[synthetic_node_ref].protocol_mux, node.protocol_mux]
            )

    return merged_nodes


def _synthesize_node_ref(node: Node, default: str) -> str:
    """
    Synthesize a node_ref using node attributes

    :param node: - the Node() object
    :param default: - default to use if node_ref not synthesizable
    :return: a 'synthetic' node_ref
    """
    if node.service_name:
        synthetic_node_ref = f"{node.protocol.ref.lower()}_{node.service_name}"
        if constants.ARGS.export_ascii_verbose:
            synthetic_node_ref += f"_{node.provider}"
        return synthetic_node_ref

    return default
