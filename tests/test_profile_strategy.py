import os
from dataclasses import replace
import yaml

import pytest

from astrolabe import node, profile_strategy


# ProfileStrategy()
class TestProfileStrategy:
    # def filter_service_name()
    @pytest.mark.parametrize('service_name,expected', [('foo', True), ('baz', False)])
    def test_filter_service_name_case_not_filter(self, profile_strategy_fixture, service_name, expected):
        """Services are filtered if they are blacklisted by a 'not' filter"""
        # arrange
        sn_filter = {'not': ['foo']}
        profile_strategy_fixture = replace(profile_strategy_fixture, service_name_filter=sn_filter)

        # act/assert
        assert profile_strategy_fixture.filter_service_name(service_name) == expected

    @pytest.mark.parametrize('service_name,expected', [('foo', False), ('bar', False), ('baz', True)])
    def test_filter_service_case_name_only_filter(self, profile_strategy_fixture, service_name, expected):
        """Services are filtered if they are not whitelisted by an 'only' filter"""
        # arrange
        sn_filter = {'only': ['foo', 'bar']}
        profile_strategy_fixture = replace(profile_strategy_fixture, service_name_filter=sn_filter)

        # act/assert
        assert profile_strategy_fixture.filter_service_name(service_name) == expected

    # determine_child_provider()
    def test_determine_child_provider_case_match_all(self, profile_strategy_fixture):
        """Child provider determined correctly for type: 'matchAll'"""
        # arrange
        provider = 'foo'
        node_type = 'COMPUTE'
        child_provider = {
            'type': 'matchAll',
            'provider': (provider, node_type)
        }
        profile_strategy_fixture = replace(profile_strategy_fixture, child_provider=child_provider)

        # act/assert
        provider_result, node_type_result = profile_strategy_fixture.determine_child_provider('dummy')
        assert provider_result == provider
        assert node_type_result == node.NodeType(node_type)

    @pytest.mark.parametrize('port,provider,node_type', [('1234', 'abc', 'COMPUTE'), (5678, 'efg', 'RESOURCE')])
    def test_determine_child_provider_case_match_port(self, profile_strategy_fixture, port, provider, node_type):
        """Child provider determined correctly per port for type: 'matchPort'"""
        # arrange
        default_provider = 'def'
        default_nt = 'UNKNOWN'

        child_provider = {
            'type': 'matchPort',
            'matches': {
                int(port): (provider, node_type)
            },
            'default': (default_provider, default_nt)
        }
        profile_strategy_fixture = replace(profile_strategy_fixture, child_provider=child_provider)

        # act
        provider_expect_match, nt_expect_match = profile_strategy_fixture.determine_child_provider(port)
        provider_expect_miss, nt_expect_miss = profile_strategy_fixture.determine_child_provider('meow')

        # assert
        assert provider_expect_match == provider
        assert nt_expect_match == node.NodeType(node_type)
        assert provider_expect_miss == default_provider
        assert nt_expect_miss == node.NodeType(default_nt)

    @pytest.mark.parametrize('address, provider', [('foo', 'bar'), ('1.2.3.4', 'baz'),
                                                   ('asdf-a7h5f8cndfy-74hf6', 'buzz')])
    def test_determine_child_provider_case_match_address(self, profile_strategy_fixture, address, provider):
        """Child provider determined correctly per address for type: 'matchAddress'"""
        # arrange
        nt = 'COMPUTE'  # we aren't testing thoroughly for nodetype here since it is tested more elsewhere
        default_provider = 'def'
        default_nt = 'UNKNOWN'
        child_provider = {
            'type': 'matchAddress',
            'matches': {
                '^foo$': ('bar', nt),
                '^(?:[0-9]{1,3}\\.){3}[0-9]{1,3}$': ('baz', nt),
                '^.*[0-9a-z]{10}-[0-9a-z]{5}$': ('buzz', nt)
            },
            'default': (default_provider, default_nt)
        }
        profile_strategy_fixture = replace(profile_strategy_fixture, child_provider=child_provider)

        # act
        provider_expect_match, nt_expect_match = profile_strategy_fixture.determine_child_provider('dummy_mux', address)
        provider_expect_miss, nt_expect_miss = profile_strategy_fixture.determine_child_provider('meow', 'i_am_a_cat')

        # assert
        assert provider_expect_match == provider
        assert nt_expect_match == node.NodeType(nt)
        assert provider_expect_miss == default_provider
        assert nt_expect_miss == node.NodeType(default_nt)

    def test_determine_child_provider_case_null_address(self, profile_strategy_fixture):
        """Child provider determined correctly for type: 'matchAddress' with address == None"""
        # arrange
        provider = 'foo'
        node_type = 'RESOURCE'
        child_provider = {
            'type': 'matchAddress',
            'matches': {
                '.*': (provider, node_type)
            },
            'default': ('default_provider', 'UNKNOWN')
        }
        profile_strategy_fixture = replace(profile_strategy_fixture, child_provider=child_provider)

        # act/assert
        provider_result, node_type_result = profile_strategy_fixture.determine_child_provider('dummy_mux', None)
        assert provider_result == provider
        assert node_type_result == node.NodeType(node_type)


# init()
def test_init_case_inits_network(astrolabe_d, core_astrolabe_d, mocker):  # pylint:disable=unused-argument
    """Charlotte.init() spins up network"""
    # `astrolabe_d` referenced in test signature only for patching of the tmp dir - fixture unused in test function
    # arrange
    init_func = mocker.patch('astrolabe.profile_strategy.network.init')

    # act
    profile_strategy.init()

    # assert
    init_func.assert_called()


# pylint:disable=too-many-locals,unused-argument
def test_init_case_wellformed_profile_strategy_yaml(astrolabe_d, core_astrolabe_d, cli_args_mock, mocker):
    """Charlotte loads a well formed profile_strategy from yaml into memory"""
    # `astrolabe_d` referenced in test signature only for patching of the tmp dir - fixture unused in test function
    # arrange
    name, description, providers, protocol, provider_args, child_provider, flter = (
        'Foo', 'Foo ProfileStrategy', ['bar'], 'BAZ', {'command': 'uptime'}, {'type': 'matchAll', 'provider': 'buz'},
        {'only': ['foo-service']}
    )
    cli_args_mock.skip_protocols = []
    stub_protocol = mocker.patch('astrolabe.network.Protocol', ref=protocol)
    mocker.patch('astrolabe.profile_strategy.network.init')
    get_protocol_func = mocker.patch('astrolabe.profile_strategy.network.get_protocol', return_value=stub_protocol)
    fake_profile_strategy_yaml = f"""
---
type: "ProfileStrategy"
name: "{name}"
description: "{description}"    
{yaml.dump({'providers': providers})}
protocol: "{protocol}"
{yaml.dump({'providerArgs': provider_args})}
{yaml.dump({'childProvider': child_provider})}
{yaml.dump({'serviceNameFilter': flter})}
"""
    fake_profile_strategy_yaml_file = os.path.join(astrolabe_d, 'Foo.yaml')
    with open(fake_profile_strategy_yaml_file, 'w', encoding='utf8') as open_file:
        open_file.write(fake_profile_strategy_yaml)

    # act
    profile_strategy.init()

    # assert
    assert 1 == len(profile_strategy.profile_strategies)
    parsed_cs = profile_strategy.profile_strategies[0]
    assert name == parsed_cs.name
    assert description == parsed_cs.description
    assert providers == parsed_cs.providers
    assert stub_protocol == parsed_cs.protocol
    assert provider_args == parsed_cs.provider_args
    assert child_provider == parsed_cs.child_provider
    assert flter == parsed_cs.service_name_filter
    get_protocol_func.assert_called_once_with('BAZ')
