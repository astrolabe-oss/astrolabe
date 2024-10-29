import pytest

from astrolabe import providers, node, constants


@pytest.fixture(autouse=True)
def disable_builtin_providers(builtin_providers, cli_args_mock):
    cli_args_mock.disable_providers = builtin_providers


@pytest.fixture
def provider_interface():
    return providers.ProviderInterface()


class TestProviderInterface:
    @pytest.mark.asyncio
    async def test_open_connection(self, provider_interface):
        """Default behavior of provider is an acceptable return of None for connection.  It is optional"""
        # arrange/act/assert
        assert await provider_interface.open_connection('dummy') is None

    @pytest.mark.asyncio
    async def test_lookup_name(self, provider_interface):
        """Default behavior of provider is an acceptable return of None for name lookup.  It is optional"""
        # arrange/act/assert
        assert await provider_interface.lookup_name('dummy', None) is None

    @pytest.mark.asyncio
    async def test_take_a_hint(self, provider_interface, mocker):
        """Default behavior of provider is an acceptable return of [] for hint taking.  It is optional"""
        # arrange
        mock_hint = mocker.patch('astrolabe.network.Hint')

        # act/assert
        assert [] == await provider_interface.take_a_hint(mock_hint)

    @pytest.mark.asyncio
    async def test_profile(self, provider_interface, mocker):
        """Default behavior of provider is an acceptable return of [] for discovering.  It is optional"""

        # arrange/act/assert
        assert [] == await provider_interface.profile('dummy', None, mocker.MagicMock())


def test_init_case_builtin_providers_disableable(cli_args_mock, builtin_providers):
    # arrange
    cli_args_mock.disable_providers = builtin_providers

    # act/assert
    providers.register_providers()
    for provider in builtin_providers:
        with pytest.raises(SystemExit) as e_info:
            providers.get_provider_by_ref(provider)
        assert 1 == e_info.value.code


@pytest.mark.parametrize('profile_strategy_response', ['', 'foo bar'])
def test_parse_profile_strategy_response_case_no_data_lines(profile_strategy_response, profile_strategy_fixture):
    # arrange/act/assert
    assert providers.parse_profile_strategy_response(profile_strategy_response, '',
                                                     profile_strategy_fixture) == []


def test_parse_profile_strategy_response_case_no_mux(profile_strategy_fixture):
    # arrange
    protocol_mux = 'foo'
    profile_strategy_response = f"address\n{protocol_mux}"

    # act/assert
    with pytest.raises(providers.CreateNodeTransportException):
        providers.parse_profile_strategy_response(profile_strategy_response, '', profile_strategy_fixture)


def test_parse_profile_strategy_response_case_mux_only(ps_mock):
    # arrange
    protocol_mux = 'foo'
    profile_strategy_response = f"mux\n{protocol_mux}"
    provider = 'FAKE'
    ps_mock.determine_child_provider.return_value = provider
    expected = [node.NodeTransport(ps_mock.name, provider, ps_mock.protocol, protocol_mux)]

    # act/assert
    res = providers.parse_profile_strategy_response(profile_strategy_response, '', ps_mock)
    assert res == expected


def test_parse_profile_strategy_response_case_all_fields(ps_mock):
    # arrange
    metadata_1_key, metadata_1_val = 'pet', 'dog'
    mux, address, _id, conns, metadata = 'foo', 'bar', 'baz', '100', f'{metadata_1_key}={metadata_1_val}'
    profile_strategy_response = f"mux address id conns metadata\n" \
                                f"{mux} {address} {_id} {conns} {metadata}"
    provider = 'FAKE'
    ps_mock.determine_child_provider.return_value = provider
    expected = [node.NodeTransport(ps_mock.name, provider, ps_mock.protocol, mux, address,
                                   False, _id, int(conns), {metadata_1_key: metadata_1_val})]

    # act/assert
    res = providers.parse_profile_strategy_response(profile_strategy_response, '', ps_mock)
    assert res == expected


@pytest.mark.parametrize('provider,from_hint', [(constants.PROVIDER_HINT, True), ('FAKE', False)])
def test_parse_profile_strategy_response_case_hint(ps_mock, provider, from_hint):
    # arrange
    protocol_mux = 'foo'
    profile_strategy_response = f"mux\n{protocol_mux}"
    ps_mock.providers = [provider]

    # act/assert
    res = providers.parse_profile_strategy_response(profile_strategy_response, '', ps_mock)
    assert res[0].from_hint == from_hint
