"""
Module Name: astrolabe

Description:
Main module for astrolabe.  Contains main() entrypoint for astrolabe as well as high level command arguments
and the recipe for loading cli args and executing the specified command.

License:
SPDX-License-Identifier: Apache-2.0
"""

__version__ = "0.1.0"

import asyncio
import getpass
import logging
import os
import signal
import sys
import traceback
from contextlib import contextmanager
from typing import Dict

import configargparse
from termcolor import colored

from astrolabe import (profile_strategy, network, cli_args, constants, discover, logs, node, plugin_core, providers,
                       exporters, database)
from astrolabe.plugins import export_json, export_ascii


# python3 check
REQUIRED_PYTHON_VERSION = (3, 8)


def tuple_join(the_tuple):
    return '.'.join(str(i) for i in the_tuple)


if sys.version_info[0] < REQUIRED_PYTHON_VERSION[0] or sys.version_info[1] < REQUIRED_PYTHON_VERSION[1]:
    print(f"Python version {tuple_join(sys.version_info[:2])} detected. This script requires Python version >= "
          f"{tuple_join(REQUIRED_PYTHON_VERSION)} available at `/usr/bin/env python3`")
    sys.exit(1)

# catch ctrl-c
signal.signal(signal.SIGINT, lambda x, y: sys.exit(0))


def main():
    print(f"Hello, {getpass.getuser()}", file=sys.stderr)
    database.init()
    plugin_core.import_plugin_classes()
    _parse_builtin_args()
    _set_debug_level()
    profile_strategy.init()
    _create_outputs_directory_if_absent()
    command = _cli_command()
    command.parse_args()
    constants.ARGS, _ = cli_args.argparser.parse_known_args()
    if constants.ARGS.debug:
        _debug_print_args()
    command.exec()
    database.close()
    print(f"\nGoodbye, {getpass.getuser()}\n", file=sys.stderr)


def _debug_print_args():
    print("\nCommand line arguments:", file=sys.stderr)
    print("----------------------", file=sys.stderr)
    for arg_name, arg_value in vars(constants.ARGS).items():
        if isinstance(arg_value, list):
            print(f"{arg_name}:", file=sys.stderr)
            for item in arg_value:
                print(f"  - {item}", file=sys.stderr)
        else:
            print(f"{arg_name}: {arg_value}", file=sys.stderr)
    print("----------------------\n", file=sys.stderr)


def _parse_builtin_args():
    try:
        with _suppress_console_out():
            constants.ARGS, _ = cli_args.parse_args(exporters.get_exporter_refs())
    except SystemExit:
        # this is done in order to display custom plugin level arguments in --help script output
        providers.parse_provider_args(cli_args.discover_subparser)
        exporters.parse_exporter_args(cli_args.discover_subparser)
        exporters.parse_exporter_args(cli_args.export_subparser)
        cli_args.argparser.parse_known_args()


@contextmanager
def _suppress_console_out():
    with open(os.devnull, "w", encoding="utf-8") as devnull:
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = devnull
        sys.stderr = devnull
        try:
            yield
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr


class Command:
    def __init__(self, argparser: configargparse.ArgParser):
        self._argparser = argparser

    def parse_args(self):
        raise NotImplementedError('Plugin Arg Parsing not implemented')

    def exec(self):
        self._initialize_plugins()
        tree = self._generate_tree()
        _export(tree)
        self._cleanup()

    def _initialize_plugins(self):
        raise NotImplementedError('Plugin initialization not implemented')

    def _generate_tree(self) -> Dict[str, node.Node]:
        raise NotImplementedError('Tree generation not implemented')

    def _cleanup(self):
        return


class ExportCommand(Command):
    def parse_args(self):
        exporters.parse_exporter_args(self._argparser)

    def _initialize_plugins(self):
        exporters.register_exporters()

    def _generate_tree(self) -> Dict[str, node.Node]:
        if not constants.ARGS.output:
            constants.ARGS.output = ['ascii']
        tree, timestamp = export_json.load(constants.ARGS.json_file or constants.LASTRUN_FILE)
        constants.CURRENT_RUN_TIMESTAMP = timestamp
        return tree


class DiscoverCommand(Command):
    def parse_args(self):
        exporters.parse_exporter_args(self._argparser)
        providers.parse_provider_args(self._argparser, constants.ARGS.disable_providers)

    def _initialize_plugins(self):
        exporters.register_exporters()
        providers.register_providers()
        asyncio.get_event_loop().run_until_complete(providers.perform_inventory())

    def _generate_tree(self) -> Dict[str, node.Node]:
        if constants.ARGS.inventory_only:
            return {}
        tree = asyncio.get_event_loop().run_until_complete(_discover_network())
        export_json.dump(tree, constants.LASTRUN_FILE)
        return tree

    def _cleanup(self):
        providers.cleanup_providers()


async def _discover_network():
    tree = await _parse_seed_tree()
    if constants.ARGS.quiet:
        await asyncio.gather(
            discover.discover(tree, []),
            export_ascii.export_tree(tree, [], out=sys.stderr, print_slowly_for_humans=True)
        )
    else:
        try:
            await discover.discover(tree, [])
        except Exception as e:  # pylint:disable=broad-exception-caught
            print(f"Error during discovery process export: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
        # try to print anyways
        try:
            await export_ascii.export_tree(tree, [], out=sys.stderr, print_slowly_for_humans=True)
        except Exception as e:  # pylint:disable=broad-exception-caught
            print(f"Error during ASCII tree export: {e}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
    return tree


def _cli_command() -> Command:
    if cli_args.COMMAND_EXPORT == constants.ARGS.command:
        return ExportCommand(cli_args.export_subparser)
    elif cli_args.COMMAND_DISCOVER == constants.ARGS.command:
        return DiscoverCommand(cli_args.discover_subparser)
    else:
        print(colored(f"Invalid command: {constants.ARGS.command}.  Please file bug with maintainer.", 'red'))
        sys.exit(1)


async def _parse_seed_tree() -> Dict[str, node.Node]:
    seeds = {}
    for provider, address in [seed.split(':') for seed in constants.ARGS.seeds]:
        # we do this so we call the niceties that come with create_node
        nt = node.NodeTransport(
            address=address,
            protocol=network.get_protocol('TCP'),
            protocol_mux='seed',
            profile_strategy_name='_seed',
            provider=provider,
            from_hint=False,
            node_type=node.NodeType(node.NodeType.COMPUTE)
        )
        provider_obj = providers.get_provider_by_ref(provider)
        _ref, _node = await node.create_node(nt, provider_obj)
        seeds[_ref] = _node
    return seeds


def _create_outputs_directory_if_absent():
    if not os.path.exists(constants.OUTPUTS_DIR):
        os.makedirs(constants.OUTPUTS_DIR)


def _export(tree: Dict[str, node.Node]) -> None:
    if not constants.ARGS.output:
        return
    for exporter_ref in constants.ARGS.output:
        exporter = exporters.get_exporter_by_ref(exporter_ref)
        exporter.export(tree)


def _set_debug_level():
    if constants.ARGS.debug:
        logs.logger.setLevel(logging.DEBUG)
        return
    if hasattr(constants.ARGS, 'quiet') and not constants.ARGS.quiet:
        logs.logger.setLevel(logging.INFO)
