"""
Module Name: providers

Description:
In astrolable, "providers" can be though of as "Node Providers" - external data sources such as data centers
which we will query and connect to for discovering and profiling nodes.  Providers code is defined here which builds
 upon the plugin core interface.  Actual provider code is found in the ./plugins directory

Copyright:
Copyright 2024 Magellanbot, Inc

License:
SPDX-License-Identifier: Apache-2.0
"""

from typing import List, Optional

import configargparse

from astrolabe import constants, logs
from astrolabe.network import Hint
from astrolabe.node import NodeTransport
from astrolabe.plugin_core import PluginInterface, PluginFamilyRegistry
from astrolabe.profile_strategy import ProfileStrategy


class TimeoutException(Exception):
    """Timeout occurred connecting to the provider"""


class CreateNodeTransportException(Exception):
    """An exception during creation of Node Transport"""


class ProviderInterface(PluginInterface):
    @staticmethod
    def is_container_platform() -> bool:
        """
        Optionally announce whether this provider is a container based platform (kubernetes, docker).  This is used to
        export container nodes differently than traditional servers systems.
        :return:
        """
        return False

    async def open_connection(self, address: str) -> Optional[type]:
        """
        Optionally open a connection which can then be passed into lookup_name() and discover()

        :param address: for example, and ip address for which to open and ssh connection
        :return: mixed type object representing a connection to node in the provider
        :raises:
            TimeoutException - Timeout connecting to provider for name lookup
        """
        del address
        return None

    async def lookup_name(self, address: str, connection: Optional[type]) -> Optional[str]:
        """
        Takes and address and lookups up service name in provider.  Default response when subclassing
        will be a no-op, which allows provider subclasses to only implement aspects of this classes functionality
        a-la-cart style

        :param address: look up the name for this IP address
        :param connection: optional connection.  for example if an ssh connection was opened during
                                   lookup_name() it can be returned there and re-used here
        :return: the derived service name in string form
        :raises:
            NameLookupFailedException - Not able to find a name in the provider
        """
        del address, connection
        return None

    async def sidecar(self, address: str, connection: Optional[type]) -> Optional[str]:
        """
        Optionally run any arbitrary code from with in the node context.  Lets just call it a sidecar b/c it
        kind of is.

        :param address: look up the name for this IP address
        :param connection: optional connection.  for example if an ssh connection was opened during
                                   lookup_name() it can be returned there and re-used here
        :return: the derived service name in string form
        :raises:
            NameLookupFailedException - Not able to find a name in the provider
        """
        del address, connection
        return None

    async def take_a_hint(self, hint: Hint) -> List[NodeTransport]:
        """
        Takes a hint, looks up an instance of service in the provider, and returns a NodeTransport representing the
        Node discovered in the Provider. Default response when subclassing will be a no-op, which allows provider
        subclasses to only implement aspects of this classes functionality a-la-cart style.
        Please return the NodeTransport object in the form of a List of 1 NodeTransport object!
        :param hint: take this hint
        :return:
        """
        del hint
        return []

    async def profile(self, address: str, pfs: ProfileStrategy, connection: Optional[type]) -> List[NodeTransport]:
        """
        Discover provider for downstream services using ProfileStrategy.  Default response when subclassing will be a
        no-op, which allows provider subclasses to only implement aspects of this classes functionality a-la-cart style.
        Please cache your results to improve system performance!

        :param address: address to discover
        :param pfs: ProfileStrategy used to profile
        :param connection: optional connection.  for example if an ssh connection was opened during
                                   lookup_name() it can be returned there and re-used here
        :Keyword Arguments: extra arguments passed to provider from ProfileStrategy.provider_args

        :return: the children as a list of Node()s
        """
        del address, connection, pfs
        return []


_provider_registry = PluginFamilyRegistry(ProviderInterface)


def parse_provider_args(argparser: configargparse.ArgParser, disabled_provider_refs: Optional[List[str]] = None):
    _provider_registry.parse_plugin_args(argparser, disabled_provider_refs)


def register_providers():
    _provider_registry.register_plugins(constants.ARGS.disable_providers)


def get_provider_by_ref(provider_ref: str) -> ProviderInterface:
    return _provider_registry.get_plugin(provider_ref)


def parse_profile_strategy_response(response: str, address: str, pfs_name: str) -> List[NodeTransport]:
    lines = response.splitlines()
    if len(lines) < 2:
        return []
    header_line = lines.pop(0)
    node_transports = [_create_node_transport_from_profile_strategy_response_line(header_line, data_line)
                       for data_line in lines]
    logs.logger.debug("Found %d profile results for %s, profile strategy: \"%s\"..",
                      len(node_transports), address, pfs_name)
    return node_transports


def _create_node_transport_from_profile_strategy_response_line(header_line: str, data_line: str):
    field_map = {
        'mux': 'protocol_mux',
        'address': 'address',
        'id': 'debug_identifier',
        'conns': 'num_connections',
        'metadata': 'metadata'
    }
    fields = {}
    for label, value in zip(header_line.split(), data_line.split()):
        if label == 'address' and value == 'null':
            continue
        fields[label] = value

    # field transforms/requirements
    if 'mux' not in fields:
        raise CreateNodeTransportException("protocol_mux missing from profile strategy results")
    if 'metadata' in fields:
        fields['metadata'] = dict(tuple(i.split('=') for i in fields['metadata'].split(',')))
    if 'conns' in fields:
        fields['conns'] = int(fields['conns'])
    return NodeTransport(**{field_map[k]: v for k, v in fields.items() if v})
