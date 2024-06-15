import os
import pytest
import yaml
from dataclasses import replace

from astrolabe import profile_strategy


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
        cp = {
            'type': 'matchAll',
            'provider': provider
        }
        profile_strategy_fixture = replace(profile_strategy_fixture, child_provider=cp)

        # act/assert
        assert profile_strategy_fixture.determine_child_provider('dummy') == provider

    @pytest.mark.parametrize('port,provider', [('1234', 'abc'), (5678, 'efg')])
    def test_determine_child_provider_case_match_port(self, profile_strategy_fixture, port, provider):
        """Child provider determined correctly per port for type: 'matchPort'"""
        # arrange
        cp = {
            'type': 'matchPort',
            'matches': {
                int(port): provider
            }
        }
        profile_strategy_fixture = replace(profile_strategy_fixture, child_provider=cp)

        # act/assert
        assert profile_strategy_fixture.determine_child_provider(port) == provider

    @pytest.mark.parametrize('address, provider', [('foo', 'bar'), ('1.2.3.4', 'baz'),
                                                   ('asdf-a7h5f8cndfy-74hf6', 'buzz'), ('asdf', 'qux')])
    def test_determine_child_provider_case_match_address(self, profile_strategy_fixture, address, provider):
        """Child provider determined correctly per address for type: 'matchAddress'"""
        # arrange
        cp = {
            'type': 'matchAddress',
            'matches': {
                '^foo$': 'bar',
                '^(?:[0-9]{1,3}\\.){3}[0-9]{1,3}$': 'baz',
                '^.*[0-9a-z]{10}-[0-9a-z]{5}$': 'buzz',
                '.*': 'qux'
            }
        }
        profile_strategy_fixture = replace(profile_strategy_fixture, child_provider=cp)

        # act/assert
        assert profile_strategy_fixture.determine_child_provider('dummy_mux', address) == provider

    def test_determine_child_provider_case_null_address(self, profile_strategy_fixture):
        """Child provider determined correctly for type: 'matchAddress' with address == None"""
        # arrange
        provider = 'foo'
        cp = {
            'type': 'matchAddress',
            'matches': {
                '.*': provider
            }
        }
        profile_strategy_fixture = replace(profile_strategy_fixture, child_provider=cp)

        # act/assert
        assert profile_strategy_fixture.determine_child_provider('dummy_mux', None) == provider

    # rewrite_service_name()
    def test_rewrite_service_name_case_no_rewrite(self, profile_strategy_fixture, node_fixture):
        """Do not rewrite service name if not configured as such"""
        # arrange
        profile_strategy_fixture = replace(profile_strategy_fixture, service_name_rewrites={})

        # act/assert
        assert 'foo' == profile_strategy_fixture.rewrite_service_name('foo', node_fixture)

    def test_rewrite_service_name_case_noninterpolated_rewrite(self, profile_strategy_fixture, node_fixture):
        """Rewrite service name - simple scenario with no interpolations"""
        # arrange
        rewrites = {'foo': 'bar'}
        profile_strategy_fixture = replace(profile_strategy_fixture, service_name_rewrites=rewrites)

        # act/assert
        assert 'bar' == profile_strategy_fixture.rewrite_service_name('foo', node_fixture)

    def test_rewrite_service_name_case_interpolated_rewrite(self, profile_strategy_fixture, node_fixture):
        """Rewrite service name with interpolations"""
        # arrange
        rewrites = {'foo': 'bar-$protocol_mux'}
        profile_strategy_fixture = replace(profile_strategy_fixture, service_name_rewrites=rewrites)
        node_fixture = replace(node_fixture, protocol_mux='baz')

        # act/assert
        assert 'bar-baz' == profile_strategy_fixture.rewrite_service_name('foo', node_fixture)


# init()
def test_init_case_inits_network(astrolabe_d, mocker):
    """Charlotte.init() spins up network"""
    # `astrolabe_d` referenced in test signature only for patching of the tmp dir - fixture unused in test function
    # arrange
    init_func = mocker.patch('astrolabe.profile_strategy.network.init')

    # act
    profile_strategy.init()

    # assert
    init_func.assert_called()


def test_init_case_wellformed_discoverstrategy_yaml(astrolabe_d, cli_args_mock, mocker):
    """Charlotte loads a well formed profile_strategy from yaml into memory"""
    # `astrolabe_d` referenced in test signature only for patching of the tmp dir - fixture unused in test function
    # arrange
    name, description, providers, protocol, provider_args, child_provider, filter, rewrites = (
        'Foo', 'Foo ProfileStrategy', ['bar'], 'BAZ', {'command': 'uptime'}, {'type': 'matchAll', 'provider': 'buz'},
        {'only': ['foo-service']}, {'ugly-foo': 'pretty-foo'}
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
{yaml.dump({'serviceNameFilter': filter})}
{yaml.dump({'serviceNameRewrites': rewrites})}
"""
    fake_profile_strategy_yaml_file = os.path.join(astrolabe_d, 'Foo.yaml')
    with open(fake_profile_strategy_yaml_file, 'w') as f:
        f.write(fake_profile_strategy_yaml)

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
    assert filter == parsed_cs.service_name_filter
    assert rewrites == parsed_cs.service_name_rewrites
    get_protocol_func.assert_called_once_with('BAZ')
