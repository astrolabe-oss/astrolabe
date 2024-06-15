"""
Notes:
    - `lookup_name` is stubbed with a dummy return value for many tests - because `discover` will not (should not) proceed
        to the `profile` portion of discovering if a name is not returned by `lookup_name`
    - "ps_mock" fixture is passed to many tests here and appears unused.  however it is a required fixture for tests
        to be valid since the fixture code itself will patch the profile_strategy object into the code flow in the test
"""
from astrolabe import discover, node
from astrolabe.providers import TimeoutException

import asyncio
import pytest
from unittest.mock import MagicMock


@pytest.fixture(autouse=True)
def clear_caches():
    """Clear discover.py caches between tests - otherwise our asserts for function calls may not pass"""
    discover.service_name_cache = {}
    discover.child_cache = {}


@pytest.fixture(autouse=True)
def set_default_timeout(builtin_providers, cli_args_mock):
    cli_args_mock.timeout = 30


@pytest.fixture
def mock_provider_ref() -> str:
    return 'mock_provider'


@pytest.fixture
def provider_mock(mocker, mock_provider_ref) -> MagicMock:
    provider_mock = mocker.patch('astrolabe.providers.ProviderInterface', autospec=True)
    provider_mock.ref.return_value = mock_provider_ref
    mocker.patch('astrolabe.providers.get_provider_by_ref', return_value=provider_mock)

    return provider_mock


@pytest.fixture
def ps_mock(protocol_fixture, mocker, mock_provider_ref) -> MagicMock:
    """it is a required fixture to include, whether or not it is used explicitly, in or to mock profile"""
    ps_mock = mocker.patch('astrolabe.profile_strategy.ProfileStrategy', autospec=True)
    mocker.patch('astrolabe.profile_strategy.profile_strategies', [ps_mock])
    ps_mock.rewrite_service_name.side_effect = lambda x, y: x
    ps_mock.filter_service_name.return_value = False
    ps_mock.protocol = protocol_fixture
    ps_mock.provider_args = {}
    ps_mock.providers = [mock_provider_ref]

    return ps_mock


@pytest.fixture
def protocol_mock(mocker, dummy_protocol_ref) -> MagicMock:
    protocol_mock = mocker.patch('astrolabe.network.Protocol')
    protocol_mock.ref = dummy_protocol_ref

    return protocol_mock


@pytest.fixture
def hint_mock(protocol_fixture, mocker) -> MagicMock:
    hint_mock = mocker.patch('astrolabe.network.Hint', autospec=True)
    hint_mock.instance_provider = 'dummy_hint_provider'
    hint_mock.protocol = protocol_fixture
    mocker.patch('astrolabe.network.hints', [hint_mock])

    return hint_mock


@pytest.fixture(autouse=True)
def set_default_cli_args(cli_args_mock):
    cli_args_mock.obfuscate = False


# helpers
async def _wait_for_all_tasks_to_complete():
    """Wait for all tasks to complete in the event loop. Assumes that 1 task will remain incomplete - and that
    is the task for the async `test_...` function itself"""
    event_loop = asyncio.get_running_loop()
    while len(asyncio.all_tasks(event_loop)) > 1:
        await asyncio.sleep(0.1)  # we "fire and forget" in discover() and so have to "manually" "wait"


# Calls to ProviderInterface::open_connection
@pytest.mark.asyncio
async def test_discover_case_connection_opened_and_passed(tree, provider_mock, ps_mock):
    """Crawling a single node tree - connection is opened and passed to both lookup_name and profile"""
    # arrange
    # mock provider
    stub_connection = 'foo_connection'
    provider_mock.open_connection.return_value = stub_connection
    provider_mock.lookup_name.return_value = 'bar_name'
    # mock profile strategy
    stub_provider_args = {'baz': 'buz'}
    ps_mock.provider_args = stub_provider_args
    ps_mock.providers = [provider_mock.ref()]

    # act
    await discover.discover(tree, [])

    # assert
    provider_mock.open_connection.assert_called_once_with(list(tree.values())[0].address)
    provider_mock.lookup_name.assert_called_once_with(list(tree.values())[0].address, stub_connection)
    provider_mock.profile.assert_called_once_with(list(tree.values())[0].address, stub_connection,
                                                  **stub_provider_args)


@pytest.mark.asyncio
async def test_discover_case_open_connection_handles_skip_protocol_mux(tree, provider_mock, ps_mock, mocker):
    """If a node should be skipped due to protocol_mux, we do not even open the connection and we set an error."""
    # arrange
    skip_function = mocker.patch('astrolabe.network.skip_protocol_mux', return_value=True)

    # act
    await discover.discover(tree, [])

    # assert
    assert 'CONNECT_SKIPPED' in list(tree.values())[0].errors
    provider_mock.open_connection.assert_not_called()
    provider_mock.lookup_name.assert_not_called()
    provider_mock.profile.assert_not_called()
    skip_function.assert_called_once_with(list(tree.values())[0].protocol_mux)


@pytest.mark.asyncio
async def test_discover_case_open_connection_handles_timeout_exception(tree, provider_mock, ps_mock):
    """Respects the contractual TimeoutException or ProviderInterface.  If thrown we set TIMEOUT error
    but do not stop discovering"""
    # arrange
    provider_mock.open_connection.side_effect = TimeoutException

    # act
    await discover.discover(tree, [])

    assert 'TIMEOUT' in list(tree.values())[0].errors
    provider_mock.lookup_name.assert_not_called()
    provider_mock.profile.assert_not_called()


@pytest.mark.asyncio
async def test_discover_case_open_connection_handles_timeout(tree, provider_mock, ps_mock, cli_args_mock, mocker):
    """A natural timeout during ProviderInterface::open_connections is also handled by setting TIMEOUT error"""
    # arrange
    cli_args_mock.timeout = .1

    async def slow_open_connection(_):
        await asyncio.sleep(1)
    provider_mock.open_connection.side_effect = slow_open_connection

    # act
    await discover.discover(tree, [])

    assert 'TIMEOUT' in list(tree.values())[0].errors
    provider_mock.lookup_name.assert_not_called()
    provider_mock.profile.assert_not_called()


@pytest.mark.asyncio
async def test_discover_case_open_connection_handles_exceptions(tree, provider_mock, ps_mock):
    """Handle any other exceptions thrown by ProviderInterface::open_connection by exiting the program"""
    # arrange
    provider_mock.open_connection.side_effect = Exception('BOOM')

    # act/assert
    with pytest.raises(SystemExit):
        await discover.discover(tree, [])


# Calls to ProviderInterface::lookup_name
@pytest.mark.asyncio
async def test_discover_case_lookup_name_uses_cache(tree, node_fixture_factory, provider_mock):
    """Validate the calls to lookup_name for the same address are cached"""
    # arrange
    address = 'use_this_address_twice'
    node2 = node_fixture_factory()
    node2.address = address
    tree['dummy2'] = node2
    list(tree.values())[0].address = address

    # act
    await discover.discover(tree, [])

    # assert
    provider_mock.lookup_name.assert_called_once()


@pytest.mark.asyncio
async def test_discover_case_lookup_name_handles_timeout(tree, provider_mock, ps_mock, cli_args_mock, mocker):
    """Timeout is handled during lookup_name and results in a sys.exit"""
    # arrange
    cli_args_mock.timeout = .1

    async def slow_lookup_name(address):
        await asyncio.sleep(1)
    provider_mock.lookup_name = slow_lookup_name

    # act/assert
    with pytest.raises(SystemExit):
        await discover.discover(tree, [])


@pytest.mark.asyncio
async def test_discover_case_lookup_name_handles_exceptions(tree, provider_mock, ps_mock):
    """Any exceptions thrown by lookup_name are handled by exiting the program"""
    # arrange
    provider_mock.lookup_name.side_effect = Exception('BOOM')

    # act/assert
    with pytest.raises(SystemExit):
        await discover.discover(tree, [])


# Calls to ProviderInterface::profile
@pytest.mark.asyncio
@pytest.mark.parametrize('name,profile_expected,error', [(None, False, 'NAME_LOOKUP_FAILED'), ('foo', True, None)])
async def test_discover_case_profile_based_on_name(name, profile_expected, error, tree, provider_mock, ps_mock):
    """Depending on whether provider.name_lookup() returns a name - we should or should not profile()"""
    # arrange
    provider_mock.lookup_name.return_value = name
    ps_mock.providers = [provider_mock.ref()]

    # act
    await discover.discover(tree, [])

    # assert
    assert provider_mock.profile.called == profile_expected
    if error:
        assert error in list(tree.values())[0].errors


@pytest.mark.asyncio
@pytest.mark.parametrize('attr', ['warnings', 'errors'])
async def test_discover_case_do_not_profile_node_with_warns_errors(attr, tree, provider_mock, ps_mock):
    """We should not profile for node with any arbitrary warning or error"""
    # arrange
    provider_mock.lookup_name.return_value = 'dummy_name'
    setattr(list(tree.values())[0], attr, {'DUMMY': True})

    # act
    await discover.discover(tree, [])

    # assert
    provider_mock.profile.assert_not_called()


@pytest.mark.asyncio
async def test_discover_case_profile_uses_cache(tree, node_fixture_factory, provider_mock, ps_mock):
    """Validate the calls to profile for the same address are cached.  Caching is only guaranteed for
    different branches in the tree since siblings execute concurrently - and so we have to test a tree with more
    depth > 1"""
    # arrange
    repeated_service_name = 'double_name'
    singleton_service_name = 'single_name'
    node2 = node_fixture_factory()
    node2.address = 'foo'  # must be different than list(tree.values())[0].address to avoid caching
    node2_child = node.NodeTransport('foo_mux', 'bar_address')
    tree['dummy2'] = node2
    provider_mock.lookup_name.side_effect = [repeated_service_name, singleton_service_name, repeated_service_name]
    provider_mock.profile.side_effect = [[], [node2_child], []]
    ps_mock.providers = [provider_mock.ref()]

    # act
    await discover.discover(tree, [])
    await _wait_for_all_tasks_to_complete()

    # assert
    assert 2 == provider_mock.profile.call_count


@pytest.mark.asyncio
async def test_discover_case_profile_handles_timeout(tree, provider_mock, ps_mock, cli_args_mock, mocker):
    """Timeout is respected during profile and results in a sys.exit"""
    # arrange
    cli_args_mock.timeout = .1

    async def slow_profile(address, connection):
        await asyncio.sleep(1)
    provider_mock.lookup_name.return_value = 'dummy'
    provider_mock.profile.side_effect = slow_profile
    ps_mock.providers = [provider_mock.ref()]

    # act/assert
    with pytest.raises(SystemExit) as e:
        await discover.discover(tree, [])

    assert True


@pytest.mark.asyncio
async def test_discover_case_profile_handles_exceptions(tree, provider_mock, ps_mock, cli_args_mock, mocker):
    """Any exceptions thrown by profile are handled by exiting the program"""
    # arrange
    cli_args_mock.timeout = .1
    provider_mock.lookup_name.return_value = 'dummy'
    provider_mock.open_connection.side_effect = Exception('BOOM')

    # act/assert
    with pytest.raises(SystemExit):
        await discover.discover(tree, [])


# handle Cycles
@pytest.mark.asyncio
async def test_discover_case_cycle(tree, provider_mock, ps_mock):
    """Cycles should be detected, name lookup should still happen for them, but profile should not"""
    # arrange
    cycle_service_name = 'foops_i_did_it_again'
    provider_mock.lookup_name.return_value = cycle_service_name

    # act
    await discover.discover(tree, [cycle_service_name])

    # assert
    assert 'CYCLE' in list(tree.values())[0].warnings
    provider_mock.lookup_name.assert_called_once()
    provider_mock.profile.assert_not_called()


@pytest.mark.asyncio
async def test_discover_case_service_name_rewrite_cycle_detected(tree, provider_mock, ps_mock):
    """Validate cycles are detected for rewritten service names"""
    # arrange
    cycle_service_name = 'foops_i_did_it_again'
    provider_mock.lookup_name.return_value = 'original_service_name'
    list(tree.values())[0].profile_strategy = ps_mock
    ps_mock.rewrite_service_name.side_effect = None
    ps_mock.rewrite_service_name.return_value = cycle_service_name

    # act
    await discover.discover(tree, [cycle_service_name])

    # assert
    assert 'CYCLE' in list(tree.values())[0].warnings


# Parsing of ProviderInterface::profile
@pytest.mark.asyncio
@pytest.mark.parametrize('protocol_mux,address,debug_identifier,num_connections,warnings,errors', [
    ('foo_mux', 'bar_address', 'baz_name', 100, [], []),
    ('foo_mux', 'bar_address', 'baz_name', None, [], []),
    ('foo_mux', 'bar_address', None, None, [], []),
    ('foo_mux', 'bar_address', 'baz_name', 0, ['DEFUNCT'], []),
    ('foo_mux', None, None, None, [], ['NULL_ADDRESS']),
])
async def test_discover_case_profile_results_parsed(protocol_mux, address, debug_identifier, num_connections, warnings,
                                                    errors, tree, provider_mock, ps_mock):
    """Crawl results are parsed into Node objects.  We detect 0 connections as a "DEFUNCT" node.  `None` address
    is acceptable, but is detected as a "NULL_ADDRESS" node"""
    # arrange
    seed = list(tree.values())[0]
    child_nt = node.NodeTransport(protocol_mux, address, debug_identifier, num_connections)
    provider_mock.lookup_name.side_effect = ['seed_name', 'child_name']
    provider_mock.profile.side_effect = [[child_nt], []]
    ps_mock.providers = [provider_mock.ref()]

    # act
    await discover.discover(tree, [])
    await _wait_for_all_tasks_to_complete()

    # assert
    assert 1 == len(seed.children)
    child: node.Node = seed.children[list(seed.children)[0]]
    assert protocol_mux == child.protocol_mux
    assert address == child.address
    for warning in warnings:
        assert warning in child.warnings
    for error in errors:
        assert error in child.errors


# Recursive calls to discover::discover()
@pytest.mark.asyncio
async def test_discover_case_children_with_address_discovered(tree, provider_mock, ps_mock, mocker):
    """Discovered children with an address are recursively discovered """
    # arrange
    child_nt = node.NodeTransport('dummy_protocol_mux', 'dummy_address')
    provider_mock.lookup_name.side_effect = ['seed_name', 'child_name']
    provider_mock.profile.side_effect = [[child_nt], []]
    ps_mock.providers = [provider_mock.ref()]
    discover_spy = mocker.patch('astrolabe.discover.discover', side_effect=discover.discover)

    # act
    await discover.discover(tree, [])
    await _wait_for_all_tasks_to_complete()

    # assert
    assert 2 == discover_spy.call_count
    child_node = discover_spy.await_args.args[0][list(discover_spy.await_args.args[0])[0]]
    assert 'dummy_address' == child_node.address
    assert list(tree.values())[0].service_name == discover_spy.await_args.args[1][0]


@pytest.mark.asyncio
async def test_discover_case_children_without_address_not_profiled(tree, provider_mock, ps_mock, mocker):
    """Discovered children without an address are not recursively profiled """
    # arrange
    child_nt = node.NodeTransport('dummy_protocol_mux', None)
    provider_mock.lookup_name.return_value = 'dummy'
    provider_mock.profile.return_value = [child_nt]
    discover_spy = mocker.patch('astrolabe.discover.discover', side_effect=discover.discover)

    # act
    await discover.discover(tree, [])
    await _wait_for_all_tasks_to_complete()

    # assert
    assert 1 == discover_spy.call_count


# Hints
@pytest.mark.asyncio
async def test_discover_case_hint_attributes_set(tree, provider_mock, hint_mock, mocker):
    """For hints used in discovering... attributes are correctly translated from the Hint the Node"""
    # arrange
    mocker.patch('astrolabe.network.hints', return_value=[hint_mock])
    hint_nt = node.NodeTransport('dummy_protocol_mux', 'dummy_address', 'dummy_debug_id')
    provider_mock.take_a_hint.return_value = [hint_nt]
    provider_mock.lookup_name.side_effect = ['dummy', None]
    providers_get_mock = mocker.patch('astrolabe.providers.get_provider_by_ref', return_value=provider_mock)

    # act
    await discover.discover(tree, [])
    await _wait_for_all_tasks_to_complete()

    # assert
    assert list(list(tree.values())[0].children.values())[0].from_hint
    assert list(list(tree.values())[0].children.values())[0].protocol == hint_mock.protocol
    assert list(list(tree.values())[0].children.values())[0].service_name == hint_nt.debug_identifier
    providers_get_mock.assert_any_call(hint_mock.instance_provider)


@pytest.mark.asyncio
async def test_discover_case_hint_name_used(tree, provider_mock, hint_mock, mocker):
    """Hint `debug_identifier` field is respected in discovering
    (and overwritten by new name, not overwritten by None)"""
    # arrange
    mocker.patch('astrolabe.network.hints', return_value=[hint_mock])
    hint_nt = node.NodeTransport('dummy_protocol_mux', 'dummy_address', 'dummy_debug_id')
    provider_mock.take_a_hint.return_value = [hint_nt]
    provider_mock.lookup_name.side_effect = ['dummy', None]

    # act
    await discover.discover(tree, [])
    await _wait_for_all_tasks_to_complete()

    # assert
    assert list(list(tree.values())[0].children.values())[0].service_name == hint_nt.debug_identifier


# respect CLI args
@pytest.mark.asyncio
async def test_discover_case_respect_cli_skip_protocol_mux(tree, provider_mock, ps_mock, cli_args_mock, mocker):
    """Children discovered on these muxes are neither included in the tree - nor discovered"""
    # arrange
    skip_this_protocol_mux = 'foo_mux'
    cli_args_mock.skip_protocol_muxes = [skip_this_protocol_mux]
    child_nt = node.NodeTransport(skip_this_protocol_mux, 'dummy_address')
    provider_mock.lookup_name.return_value = 'bar_name'
    provider_mock.profile.return_value = [child_nt]
    discover_spy = mocker.patch('astrolabe.discover.discover', side_effect=discover.discover)

    # act
    await discover.discover(tree, [])
    await _wait_for_all_tasks_to_complete()

    # assert
    assert 0 == len(list(tree.values())[0].children)
    assert 1 == discover_spy.call_count


@pytest.mark.asyncio
async def test_discover_case_respect_cli_skip_protocols(tree, provider_mock, ps_mock, cli_args_mock, mocker):
    """Crawling of protocols configured to be "skipped" does not happen at all."""
    # arrange
    skip_this_protocol = 'FOO'
    cli_args_mock.skip_protocols = [skip_this_protocol]
    ps_mock.protocol = mocker.patch('astrolabe.network.Protocol', autospec=True)
    ps_mock.protocol.ref = skip_this_protocol
    provider_mock.lookup_name.return_value = 'bar_name'

    # act
    await discover.discover(tree, [])
    # assert
    provider_mock.profile.assert_not_called()


@pytest.mark.asyncio
async def test_discover_case_respect_cli_disable_providers(tree, provider_mock, ps_mock, cli_args_mock, mocker):
    """Children discovered which have been determined to use disabled providers - are neither included in the tree
    nor discovered"""
    # arrange
    disable_this_provider = 'foo_provider'
    cli_args_mock.disable_providers = [disable_this_provider]
    child_nt = node.NodeTransport('dummy_mux', 'dummy_address')
    provider_mock.lookup_name.return_value = 'bar_name'
    provider_mock.profile.return_value = [child_nt]
    ps_mock.determine_child_provider.return_value = disable_this_provider
    discover_spy = mocker.patch('astrolabe.discover.discover', side_effect=discover.discover)

    # act
    await discover.discover(tree, [])
    await _wait_for_all_tasks_to_complete()

    # assert
    assert 0 == len(list(tree.values())[0].children)
    assert 1 == discover_spy.call_count


@pytest.mark.asyncio
@pytest.mark.parametrize('child_blocking,grandchild_blocking,discoveries_expected,downstream_discoveries_expected',
                         [(False, False, 2, 1), (True, False, 2, 2)])
async def test_discover_case_respect_cli_skip_nonblocking_grandchildren(child_blocking, grandchild_blocking,
                                                                        discoveries_expected,
                                                                        downstream_discoveries_expected,
                                                                        tree, provider_mock, protocol_mock, ps_mock,
                                                                        cli_args_mock, mocker):
    """When --skip-nonblocking-grandchildren is specified, include nonblocking children of the seed, but nowhere else"""
    # arrange
    cli_args_mock.skip_nonblocking_grandchildren = True
    child_nt = node.NodeTransport('dummy_protocol_mux', 'dummy_address')
    grandchild_nt = node.NodeTransport('dummy_protocol_mux_gc', 'dummy_address_gc')
    provider_mock.lookup_name.side_effect = ['seed_name', 'child_name', 'grandchild_name']
    provider_mock.profile.side_effect = [[child_nt], [grandchild_nt], []]
    type(protocol_mock).blocking = mocker.PropertyMock(side_effect=[True, child_blocking, grandchild_blocking])
    ps_mock.protocol = protocol_mock
    discover_spy = mocker.patch('astrolabe.discover.discover', side_effect=discover.discover)

    # act
    await discover.discover(tree, [])
    await _wait_for_all_tasks_to_complete()

    # assert
    assert discover_spy.call_count == discoveries_expected
    assert provider_mock.profile.call_count == downstream_discoveries_expected


@pytest.mark.asyncio
async def test_discover_case_respect_cli_max_depth(tree, node_fixture, provider_mock, ps_mock, cli_args_mock):
    """We should not profile if max-depth is exceeded"""
    # arrange
    cli_args_mock.max_depth = 0
    provider_mock.lookup_name.return_value = 'dummy_name'

    # act
    await discover.discover(tree, [])

    # assert
    provider_mock.profile.assert_not_called()


@pytest.mark.asyncio
async def test_discover_case_respect_cli_obfuscate(tree, node_fixture, ps_mock, provider_mock, cli_args_mock):
    """We need to test a child for protocol mux obfuscation since the tree is already populated with a fully hydrated
        Node - which is past the point of obfuscation"""
    # arrange
    cli_args_mock.obfuscate = True
    seed_service_name = 'actual_service_name_foo'
    child_protocol_mux = 'child_actual_protocol_mux'
    child_nt = node.NodeTransport(child_protocol_mux)
    provider_mock.lookup_name.return_value = seed_service_name
    provider_mock.lookup_name.return_value = 'dummy_service_name'
    provider_mock.profile.side_effect = [[child_nt], []]
    ps_mock.providers = [provider_mock.ref()]

    # act
    await discover.discover(tree, [])

    # assert
    seed: node.Node = list(tree.values())[0]
    child: node.Node = seed.children[list(seed.children)[0]]
    assert seed.service_name != seed_service_name
    assert child.protocol_mux != child_protocol_mux


# respect profile_strategy / network configurations
@pytest.mark.asyncio
async def test_discover_case_respect_ps_filter_service_name(tree, provider_mock, ps_mock):
    """We respect when a service name is configured to be skipped by a specific profile strategy"""
    # arrange
    ps_mock.filter_service_name.return_value = True
    provider_mock.lookup_name.return_value = 'bar_name'

    # act
    await discover.discover(tree, [])

    # assert
    ps_mock.filter_service_name.assert_called_once_with(list(tree.values())[0].service_name)
    provider_mock.profile.assert_not_called()


@pytest.mark.asyncio
async def test_discover_case_respect_ps_service_name_rewrite(tree, provider_mock, ps_mock):
    """Validate service_name_rewrites are called and used"""
    # arrange
    service_name = 'foo_name'
    rewritten_service_name = 'bar_name'
    provider_mock.lookup_name.return_value = service_name
    list(tree.values())[0].profile_strategy = ps_mock
    ps_mock.rewrite_service_name.side_effect = None
    ps_mock.rewrite_service_name.return_value = rewritten_service_name

    # act
    await discover.discover(tree, [])

    # assert
    assert list(tree.values())[0].service_name == rewritten_service_name


@pytest.mark.asyncio
async def test_discover_case_respect_network_skip(tree, provider_mock, ps_mock, mocker):
    """Skip service name is respected for network"""
    # arrange
    service_name = 'foo_name'
    provider_mock.lookup_name.return_value = service_name
    skip_function = mocker.patch('astrolabe.network.skip_service_name', return_value=True)

    # act
    await discover.discover(tree, [])

    # assert
    provider_mock.lookup_name.assert_called_once()
    provider_mock.profile.assert_not_called()
    skip_function.assert_called_once_with(service_name)
