import re

import pytest

from astrolabe import obfuscate


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
def test_obfuscate_protocol_mux(real_mux, expect_mux_match):
    """obfuscate twice to ensure consistent obfuscation"""
    # arrange

    # act
    obfuscated_once = obfuscate.obfuscate_protocol_mux(real_mux)
    obfuscated_twoce = obfuscate.obfuscate_protocol_mux(real_mux)

    # assert
    assert obfuscated_once != real_mux
    assert re.search(expect_mux_match, obfuscated_once)
    assert re.search(expect_mux_match, obfuscated_twoce)
    assert obfuscated_once == obfuscated_twoce
