"""
Module Name: network

Description:
The network.yaml config file is loaded here - where users configure the various protocols, hints and skips
of their known network map.

License:
SPDX-License-Identifier: Apache-2.0
"""

import ipaddress
import sys
from dataclasses import dataclass, asdict
from typing import NamedTuple, Dict, List
from string import Template
from yaml import safe_load

from termcolor import colored
from astrolabe import constants, config, node


# using this instead of a namedtuple for ease of json serialization/deserialization
@dataclass(frozen=True)
class Protocol:
    ref: str
    name: str
    blocking: bool
    is_database: bool = False
    __type__: str = 'Protocol'  # for json serialization/deserialization


class Hint(NamedTuple):
    service_name: str
    protocol: Protocol
    protocol_mux: str
    provider: str
    instance_provider: str


class WebYamlException(Exception):
    """Errors parsing web.yaml file"""


_NETWORK_FILE = 'network.yaml'
_hints:  Dict[str, List[Hint]] = {}
_protocols: Dict[str, Protocol] = {}
_ignored_cidrs = ['169.254.169.254/32']
_ignored_ip_networks = [ipaddress.ip_network(cidr) for cidr in _ignored_cidrs]
_skip_addresses: List[str] = []
_skip_service_names: List[str] = []
_skip_protocol_muxes: List[str] = []
_service_name_rewrites: Dict[str, str] = {}

PROTOCOL_TCP = Protocol('TCP', 'TCP', True)
PROTOCOL_SEED = Protocol('SEED', 'Seed', True)
PROTOCOL_HINT = Protocol('HNT', 'Hint', True)
PROTOCOL_INVENTORY = Protocol('INV', 'Inventory', True)
_builtin_protocols = {PROTOCOL_SEED, PROTOCOL_HINT}
_protocols['SEED'] = PROTOCOL_SEED
_protocols['HNT'] = PROTOCOL_HINT
_protocols['TCP'] = PROTOCOL_TCP


def init():
    """It initializes the network from network.yaml"""
    for file in config.get_network_yaml_files():
        with open(file, 'r', encoding='utf-8') as stream:
            configs = _parse_yaml_config(stream, file)
            _parse_protocols(configs)
            _parse_skips(configs)
            _parse_rewrites(configs)

            # hints
            global _hints  # pylint: disable=global-variable-not-assigned
            if configs.get('hints'):
                for service_name, lst in configs.get('hints').items():
                    try:
                        _hints[service_name] = [Hint(**dict(dct, **{'protocol': get_protocol(dct['protocol'])}))
                                                for dct in lst]
                    except TypeError:
                        print(colored(f"Hints malformed in {_NETWORK_FILE}.  Fields expected: {Hint._fields}",
                                      'red'))
                        print(colored(lst, 'yellow'))
                        sys.exit(1)

            # validate
            _validate()


def _validate() -> None:
    if len(_protocols) <= len(_builtin_protocols):
        print(
            colored('No protocols defined in astrolabe.d/network.yaml!  Please define protocols before proceeding',
                    'red')
        )
        sys.exit(1)


def _parse_yaml_config(stream, file) -> Dict[str, dict]:
    try:
        return safe_load(stream)
    except Exception as exc:
        raise WebYamlException(f"Unable to load yaml {file}") from exc


def _parse_protocols(configs: Dict[str, dict]) -> None:
    if not configs.get('protocols'):
        return

    try:
        for protocol, attrs in configs.get('protocols').items():
            _protocols[protocol] = Protocol(ref=protocol, **attrs)
    except Exception as exc:
        raise WebYamlException(f"protocols malformed in {_NETWORK_FILE}") from exc


def _parse_skips(configs: Dict[str, dict]) -> None:
    global _skip_service_names, _skip_protocol_muxes, _skip_addresses
    _skip_addresses = configs.get('skips').get('addresses') if configs.get('skips') else []
    _skip_service_names = configs.get('skips').get('service_names') if configs.get('skips') else []
    _skip_protocol_muxes = configs.get('skips').get('protocol_muxes') if configs.get('skips') else []


def _parse_rewrites(configs: Dict[str, dict]) -> None:
    global _service_name_rewrites
    _service_name_rewrites = configs.get('service-name-rewrites') if configs.get('service-name-rewrites') else {}


def skip_address(address: str) -> bool:
    # Check against astrolabe.d/network.yaml
    if True in [match in address for match in _skip_addresses]:
        return True

    # Check against default ignored CIDRs
    try:
        ipaddr = ipaddress.ip_address(address)
        skip = any(ipaddr in cidr for cidr in _ignored_ip_networks)
        return skip
    except ValueError:
        pass  # not an IP address

    return False


def skip_service_name(service_name: str) -> bool:
    return True in [match in service_name for match in _skip_service_names]


def skip_protocol_mux(protocol_mux: str) -> bool:
    # Check again CLI args
    for skip in constants.ARGS.skip_protocol_muxes:
        if skip in protocol_mux:
            return True

    # Check against astrolabe.d/network.yaml
    matched = [match in protocol_mux for match in _skip_protocol_muxes] or []
    return True in matched


def hints(service_name: str) -> List[Hint]:
    return _hints.get(service_name) or []


def get_protocol(ref: str) -> Protocol:
    try:
        return _protocols[ref]
    except KeyError as exc:
        print(colored(f"Protocol {ref} not found!  Please validate your configurations in "
                      f"{config.ASTROLABE_DIR}", 'red'))
        raise exc


def rewrite_service_name(service_name: str, node: node.Node) -> str:
    """
    Some service names have to be filtered/rewritten.  It uses string.Template
    to re-write the service name based on node attributes.

    :param service_name: the service name to rewrite, if needed
    :param node: used to interpolate attributes into the rewrite
    :return:
    """
    for match, rewrite in _service_name_rewrites.items():
        if service_name and match in service_name:
            return Template(rewrite).substitute(dict(asdict(node)))

    return service_name
