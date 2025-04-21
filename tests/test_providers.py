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


@pytest.mark.asyncio
@pytest.mark.parametrize('seeds_only_flag, skip_inventory_flag', [
    (True, False),
    (False, False),
    (True, True),
    (False, True)
])
async def test_perform_inventory_case_respect_cli_seeds_only(cli_args_mock, mocker,
                                                             seeds_only_flag, skip_inventory_flag):
    """
    When --seeds-only is set to True, perform_inventory should skip calling provider.inventory().
    When --seeds-only is False, perform_inventory should call provider.inventory() for each enabled provider.
    """
    # arrange
    cli_args_mock.seeds_only = seeds_only_flag
    cli_args_mock.skip_inventory = skip_inventory_flag
    cli_args_mock.disable_providers = []

    # Create a mock provider
    mock_provider = mocker.MagicMock(spec=providers.ProviderInterface)
    mock_provider.ref.return_value = "mock_provider"

    # Mock the registry to return our mock provider
    mock_get_registered = mocker.patch.object(
        providers._provider_registry,  # pylint:disable=protected-access
        'get_registered_plugins',
        return_value=[mock_provider]
    )

    # act
    await providers.perform_inventory()

    # assert
    if seeds_only_flag or skip_inventory_flag:
        mock_get_registered.assert_not_called()
        mock_provider.inventory.assert_not_called()
    else:
        mock_get_registered.assert_called_once()
        mock_provider.inventory.assert_called_once()


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
