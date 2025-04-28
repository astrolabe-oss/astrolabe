"""
Module Name: profile_strategy

Description:
Various profile strategies are loaded from CustomNameProfileStrategy.yaml files and loaded in the objects
for use in profiling and discovering nodes in the network.

License:
SPDX-License-Identifier: Apache-2.0
"""

import typing
import re
from dataclasses import dataclass, asdict
from typing import List, Optional
import yaml
from yaml import safe_load_all

from astrolabe import config, constants, logs, network, node


class ProfileStrategyException(Exception):
    """Exceptions for ProfileStrategy"""


@dataclass(frozen=True)
class ProfileStrategy:  # pylint:disable=too-many-instance-attributes
    description: str
    name: str
    protocol: network.Protocol
    providers: List[str]
    provider_args: dict
    child_provider: dict
    service_name_filter: dict
    __type__: str = 'ProfileStrategy'  # for json serialization/deserialization

    def filter_service_name(self, service_name: str) -> bool:
        """
        Crawl strategy may filter out this service-name. True response means this service_name should not be profiled

        :param service_name:
        :return:
        """
        if not self.service_name_filter:
            return False

        not_filters = self.service_name_filter.get('not')
        only_filters = self.service_name_filter.get('only')
        if not_filters and service_name in not_filters:
            return True
        if only_filters and service_name not in only_filters:
            return True

        return False

    def determine_child_provider(self, protocol_mux: str, address: str = None) -> (Optional[str], node.NodeType):
        """
        Determine the provider for the protocol_mux of a node discovered using this profile strategy

        :param protocol_mux: the protocol mux (port, nsq channel...)
        :param address: address of the node
        :return: a string representation of the provider
        """

        # Determine provider and node type based on configuration
        child_provider_type = self.child_provider['type']

        if child_provider_type == 'matchAll':
            provider, node_type = self.child_provider['provider']
        elif child_provider_type == 'matchAddress':
            for match, provider_info in self.child_provider['matches'].items():
                if re.search(match, address or ''):
                    provider, node_type = provider_info
                    break
            else:
                provider, node_type = self.child_provider['default']
        elif child_provider_type == 'matchPort':
            try:
                port = int(protocol_mux)
                provider_info = self.child_provider['matches'].get(port)
                provider, node_type = provider_info if provider_info else self.child_provider['default']
            except (ValueError, IndexError):
                provider, node_type = self.child_provider['default']
        else:
            logs.logger.fatal("child provider match type: %s not supported", child_provider_type)
            raise ProfileStrategyException()

        return provider, node.NodeType(node_type)


profile_strategies: typing.List[ProfileStrategy] = []
_seed_profile_strategy_child_provider = {'type': 'matchAll', 'provider': constants.PROVIDER_SSH}
SEED_PROFILE_STRATEGY_NAME = 'Seed'
INVENTORY_PROFILE_STRATEGY_NAME = 'Inventory'
HINT_PROFILE_STRATEGY_NAME = 'Hint'


def init():
    network.init()
    _load_profile_strategies()


def _safe_dump(obj):
    """Safely dump object to YAML, handling problematic types."""
    try:
        if not isinstance(obj, ProfileStrategy):
            return yaml.dump(asdict(obj), default_flow_style=False, sort_keys=False)
        pfs_dict = asdict(obj)
        pfs_dict.pop('provider_args', None)  # Remove provider_args from dict
        return yaml.dump(pfs_dict, default_flow_style=False, sort_keys=False)
    except ValueError:
        return str(obj)


def _load_profile_strategies():
    for file in config.get_config_yaml_files():
        with open(file, 'r', encoding='utf-8') as stream:
            dcts = safe_load_all(stream)
            for dct in dcts:
                if 'ProfileStrategy' == dct.get('type'):
                    protocol = network.get_protocol(dct['protocol'])
                    pfs = ProfileStrategy(
                        dct['description'],
                        dct['name'],
                        protocol,
                        dct['providers'],
                        dct['providerArgs'],
                        dct['childProvider'],
                        dct['serviceNameFilter'] if 'serviceNameFilter' in dct else {}
                    )
                    profile_strategies.append(pfs)
                    logs.logger.debug('Loaded ProfileStrategy:')
                    logs.logger.debug(_safe_dump(pfs))
