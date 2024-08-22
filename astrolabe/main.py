"""
Module Name: astrolabe

Description:
Main module for astrolabe.  Contains main() entrypoint for astrolabe as well as high level command arguments
and the recipe for loading cli args and executing the specified command.

Copyright:
Copyright 2024 Magellanbot, Inc

License:
SPDX-License-Identifier: Apache-2.0
"""

__version__ = "0.0.1"

import asyncio
import getpass
import logging
import os
import signal
import sys
from contextlib import contextmanager
from typing import Dict

import configargparse
from termcolor import colored

from astrolabe import (profile_strategy, network, cli_args, constants, discover, logs, node, plugin_core, providers,
                       exporters)
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
    plugin_core.import_plugin_classes()
    _parse_builtin_args()
    _set_debug_level()
    profile_strategy.init()
    _create_outputs_directory_if_absent()
    command = _cli_command()
    command.parse_args()
    constants.ARGS, _ = cli_args.argparser.parse_known_args()
    if constants.ARGS.debug:
        constants.PP.pprint(constants.ARGS)
    command.exec()
    print(f"\nGoodbye, {getpass.getuser()}\n", file=sys.stderr)


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

    def _initialize_plugins(self):
        raise NotImplementedError('Plugin initialization not implemented')

    def _generate_tree(self) -> Dict[str, node.Node]:
        raise NotImplementedError('Tree generation not implemented')


class ExportCommand(Command):
    def parse_args(self):
        exporters.parse_exporter_args(self._argparser)

    def _initialize_plugins(self):
        exporters.register_exporters()

    def _generate_tree(self) -> Dict[str, node.Node]:
        if not constants.ARGS.output:
            constants.ARGS.output = ['ascii']
        return export_json.load(constants.ARGS.json_file or constants.LASTRUN_FILE)


class DiscoverCommand(Command):
    def parse_args(self):
        exporters.parse_exporter_args(self._argparser)
        providers.parse_provider_args(self._argparser, constants.ARGS.disable_providers)

    def _initialize_plugins(self):
        exporters.register_exporters()
        providers.register_providers()

    def _generate_tree(self) -> Dict[str, node.Node]:
        tree = asyncio.get_event_loop().run_until_complete(_discover_network())
        export_json.dump(tree, constants.LASTRUN_FILE)
        return tree


def _cli_command() -> Command:
    if cli_args.COMMAND_EXPORT == constants.ARGS.command:
        return ExportCommand(cli_args.export_subparser)
    elif cli_args.COMMAND_DISCOVER == constants.ARGS.command:
        return DiscoverCommand(cli_args.discover_subparser)
    else:
        print(colored(f"Invalid command: {constants.ARGS.command}.  Please file bug with maintainer.", 'red'))
        sys.exit(1)


async def _discover_network():
    tree = _parse_seed_tree()
    await _discover_and_export_to_stderr_unless_quiet_is_specified(tree)
    return tree


async def _discover_and_export_to_stderr_unless_quiet_is_specified(tree: Dict[str, node.Node]):
    # pylint:disable=consider-using-with  # open will close stderr when done, bad!
    outfile = open(os.devnull, 'w', encoding="utf-8") if constants.ARGS.quiet else sys.stderr
    discover_tasks = [
        discover.discover(tree, []),
        export_ascii.export_tree(tree, [], out=outfile, print_slowly_for_humans=True)
    ]
    await asyncio.gather(*discover_tasks)


def _parse_seed_tree() -> Dict[str, node.Node]:
    return {
        f"SEED:{address}":
            node.Node(
                profile_strategy=profile_strategy.SEED_PROFILE_STRATEGY,
                protocol=network.PROTOCOL_SEED,
                protocol_mux='seed',
                provider=provider,
                containerized=providers.get_provider_by_ref(provider).is_container_platform(),
                from_hint=False,
                address=address
            )
        for provider, address in [seed.split(':') for seed in constants.ARGS.seeds]
    }


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