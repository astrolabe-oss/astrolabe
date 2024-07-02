import re

import pytest

from astrolabe import obfuscate, node


def test_obfuscate_service_name():
    """obfuscate twice to ensure consistent obfuscation"""
    # arrange
    service_name = 'foo'

    # act
    obfuscated_service_name = obfuscate.obfuscate_service_name(service_name)
    obfuscated_service_name_two = obfuscate.obfuscate_service_name(service_name)

    # assert
    assert obfuscated_service_name != service_name
    assert obfuscated_service_name == obfuscated_service_name_two
    assert obfuscated_service_name is not None
    assert obfuscated_service_name != ''
    assert len(obfuscated_service_name) > 5


@pytest.mark.parametrize('real_mux,expect_mux_match', [('8080', '[0-9]+'), ('foobar', '[a-z]+#[a-z]+')])
def test_obfuscate_node_transport_case_protocol_mux(real_mux, expect_mux_match):
    """obfuscate twice to ensure consistent obfuscation"""
    # arrange
    node_transport = node.NodeTransport(real_mux)

    # act
    obfuscated_node_transport = obfuscate.obfuscate_node_transport(node_transport)
    obfuscated_node_transport_two = obfuscate.obfuscate_node_transport(node_transport)

    # assert
    assert obfuscated_node_transport.protocol_mux != real_mux
    assert re.search(expect_mux_match, obfuscated_node_transport.protocol_mux)
    assert obfuscated_node_transport == obfuscated_node_transport_two
