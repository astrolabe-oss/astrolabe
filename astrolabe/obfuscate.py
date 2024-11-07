"""
Module Name: obfuscate

Description:
Code for obfuscate service names during export

License:
SPDX-License-Identifier: Apache-2.0
"""

from dataclasses import replace
from typing import Dict

import coolname
import faker

from astrolabe.node import NodeTransport
_obfuscated_service_names: Dict[str, str] = {}
_obfuscated_protocol_muxes: Dict[str, str] = {}


def obfuscate_service_name(service_name: str):
    if service_name in _obfuscated_service_names:
        return _obfuscated_service_names[service_name]
    obfuscated_name = coolname.generate_slug(2)
    _obfuscated_service_names[service_name] = obfuscated_name
    return obfuscated_name


def obfuscate_node_transport(node_transport: NodeTransport) -> NodeTransport:
    obfuscated_protocol_mux = _obfuscate_protocol_mux(node_transport.protocol_mux)
    return replace(node_transport, protocol_mux=obfuscated_protocol_mux)


def _obfuscate_protocol_mux(protocol_mux: str) -> str:
    if protocol_mux in _obfuscated_protocol_muxes:
        return _obfuscated_protocol_muxes[protocol_mux]
    if protocol_mux.isdigit():
        obfuscated_protocol_mux = str(faker.Factory.create().port_number())
    else:
        obfuscated_protocol_mux = '#'.join(coolname.generate(2))
    _obfuscated_protocol_muxes[protocol_mux] = obfuscated_protocol_mux
    return obfuscated_protocol_mux