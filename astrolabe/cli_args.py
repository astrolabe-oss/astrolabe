"""
Module Name: cli_args

Description:
Defines the cli arg parsers for use by command line interface

Copyright:
Copyright 2024 Magellanbot, Inc

License:
SPDX-License-Identifier: Apache-2.0
"""

import argparse
from typing import List, Optional

import configargparse


command_discover = 'discover'
command_export = 'export'
argparser: Optional[configargparse.ArgParser] = None
discover_subparser: Optional[configargparse.ArgParser] = None
export_subparser: Optional[configargparse.ArgParser] = None


def parse_args(registered_exporter_refs: List[str]) -> (configargparse.Namespace, list):
    class ConciseHelpFormatter(argparse.ArgumentDefaultsHelpFormatter):
        """Custom formatter to reduce redundancy in Help Display Output"""
        def _format_action_invocation(self, action):
            if not action.option_strings or action.nargs == 0:
                return super()._format_action_invocation(action)
            # we only care about `-s ARGS, --long ARGS`
            default = self._get_default_metavar_for_optional(action)
            args_string = self._format_args(action, default)
            return ', '.join(action.option_strings) + ' ' + args_string

    global argparser, discover_subparser, export_subparser
    argparser = configargparse.ArgumentParser(
        description="Run Astrolabe against your datacenter to discover network topology!"
    )

    def formatter_class(prog):
        return ConciseHelpFormatter(prog, max_help_position=100, width=200)
    # subparsers
    subparsers = argparser.add_subparsers(
        help=f'Please select an acceptable command for astrolabe: "{command_discover}" or "{command_export}"'
    )
    subparsers.required = True
    subparsers.dest = 'command'
    discover_p = subparsers.add_parser(command_discover, help='Crawl a network of services - given a seed',
                                       formatter_class=formatter_class, default_config_files=['./astrolabe.conf'])
    export_p = subparsers.add_parser(command_export, help='Export results of a previous discover',
                                     formatter_class=formatter_class)
    discover_subparser = discover_p
    export_subparser = export_p

    # add common opts to each sub parser
    for sub_p in subparsers.choices.values():
        # common args
        sub_p.add_argument('-D', '--hide-defunct', action='store_true',
                           help='Hide defunct (unused) connections')
        sub_p.add_argument('-o', '--output', action='append', choices=registered_exporter_refs,
                           help='Format in which to output the final graph.  Available options: '
                                f"[{','.join(registered_exporter_refs)}]")
        sub_p.add_argument('--debug', action='store_true', help='Log debug output to stderr')
        sub_p.add_argument('-c', '--config-file', is_config_file=True, metavar='FILE',
                            help='Specify a config file path')

    # discover command args
    discover_p.add_argument('-s', '--seeds', required=True, nargs='+', metavar='SEED',
                          help='Seed host(s) to begin discovering viz. an IP address or hostname.  '
                               'Must be in the format: "provider:address".  '
                               'e.g. "ssh:10.0.0.42" or "k8s:widget-machine-5b5bc8f67f-2qmkp')
    discover_p.add_argument('-t', '--timeout', type=int, default=60, metavar='TIMEOUT',
                          help='Timeout when discovering a node')
    discover_p.add_argument('-d', '--max-depth', type=int, default=100, metavar='DEPTH',
                            help='Max tree depth to discover')
    discover_p.add_argument('-X', '--disable-providers', nargs='+', default=[], metavar='PROVIDER',
                          help="Do not initialize or discover with these providers")
    discover_p.add_argument('-P', '--skip-protocols', nargs='+', default=[], metavar='PROTOCOL',
                          help='A list of protocols to skip.  e.g. "NSQ PXY"')
    discover_p.add_argument('-M', '--skip-protocol-muxes', nargs='+', default=[], metavar='MUX',
                          help='Skip discovering for children on services with these '
                               'names (name lookup will still happen)')
    discover_p.add_argument('-G', '--skip-nonblocking-grandchildren', action='store_true',
                          help='Skip discovering of nonblocking children unless they '
                               'are direct children of the seed nodes')
    discover_p.add_argument('-x', '--obfuscate', action='store_true',
                          help="Obfuscate graph details.  Useful for sharing exported output outside of "
                               "trusted organizations.")
    discover_p.add_argument('-q', '--quiet', action='store_true',
                          help='Do not export graph output to stdout while discovering')

    # export command args
    export_p.add_argument('-f', '--json-file', metavar='FILE',
                          help='Instead of discovering, load and export a json serialization of the tree')

    return argparser.parse_known_args()
