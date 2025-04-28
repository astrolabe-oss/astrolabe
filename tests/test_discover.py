"""
Notes:
    - `lookup_name` is stubbed with a dummy return value for many tests - because `discover` will not (should not)
        proceed to the `profile` portion of discovering if a name is not returned by `lookup_name`
    - "ps_mock" fixture is passed to many tests here and appears unused.  however it is a required fixture for tests
        to be valid since the fixture code itself will patch the profile_strategy object into the code flow in the test
"""
import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock
import pytest

from astrolabe.providers import TimeoutException
from astrolabe import discover, node, providers, constants

from tests import _fake_database


@pytest.fixture
def utcnow():
    return datetime.now(timezone.utc)


@pytest.fixture(autouse=True)
def patch_database_autouse(patch_database):  # pylint:disable=unused-argument
    pass


@pytest.fixture(autouse=True)
def clear_caches():
    """Clear discover.py caches between tests - otherwise our asserts for function calls may not pass"""
    discover.child_cache = {}
    discover.discovery_ancestors = {}


@pytest.fixture(autouse=True, scope="function")
def set_default_cli_args(cli_args_mock):
    cli_args_mock.timeout = 30
    cli_args_mock.connection_timeout = 1
    cli_args_mock.skip_sidecar = False
    cli_args_mock.obfuscate = False

    return cli_args_mock


@pytest.fixture(autouse=True)
def ps_mock_autouse(ps_mock) -> MagicMock:
    return ps_mock


@pytest.fixture
def hint_mock(protocol_fixture, mocker) -> MagicMock:
    hint_mock = mocker.patch('astrolabe.network.Hint', autospec=True)
    hint_mock.instance_provider = 'dummy_hint_provider'
    hint_mock.protocol = protocol_fixture
    mocker.patch('astrolabe.network.hints', [hint_mock])

    return hint_mock


# helpers
async def _wait_for_all_tasks_to_complete():
    """Wait for all tasks to complete in the event loop. Assumes that 1 task will remain incomplete - and that
    is the task for the async `test_...` function itself"""
    event_loop = asyncio.get_running_loop()
    while len(asyncio.all_tasks(event_loop)) > 1:
        await asyncio.sleep(0.1)  # we "fire and forget" in discover() and so have to "manually" "wait"


# discover::discover - stack processing
@pytest.mark.asyncio
async def test_discover_case_respects_profile_locking(tree, provider_mock):
    """If profile locking is not working... it will repeatedly profile the node instead
         of only once while it is locked!"""
    # arrange
    node1 = list(tree.values())[0]

    async def slow_open_connection(_):
        await asyncio.sleep(.1)
    provider_mock.open_connection.side_effect = slow_open_connection

    # act
    await discover.discover(tree, [])
    await _wait_for_all_tasks_to_complete()

    # assert
    assert provider_mock.open_connection.call_count == 1
    assert provider_mock.lookup_name.call_count == 1
    assert provider_mock.profile.call_count == 1
    assert provider_mock.sidecar.call_count == 1
    assert not node1.profile_locked()


# Discover stack processing
@pytest.mark.parametrize('exc', [
    None,
    providers.TimeoutException,
    asyncio.TimeoutError,
    discover.DiscoveryException,
    Exception
])
@pytest.mark.asyncio
async def test_discover_case_sets_profile_complete(tree, provider_mock, exc, utcnow):
    """Whether profile is success or raises an exception profile_complete() should always be marked.
       We never bubble up the exception to stop execution of the main program"""
    # arrange
    node1 = list(tree.values())[0]
    provider_mock.open_connection.side_effect = exc

    # pre-assert
    assert not node1.profile_complete(utcnow)

    # act
    await discover.discover(tree, [])
    await _wait_for_all_tasks_to_complete()

    # assert
    assert node1.profile_complete(utcnow)


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

    # act
    await discover.discover(tree, [])

    # assert
    provider_mock.open_connection.assert_called_once_with(list(tree.values())[0].address)
    provider_mock.lookup_name.assert_called_once_with(list(tree.values())[0].address, stub_connection)
    provider_mock.profile.assert_called_once_with(list(tree.values())[0], [ps_mock], stub_connection)


@pytest.mark.asyncio
async def test_discover_case_open_connection_handles_skip_protocol_mux(tree, provider_mock, mocker, utcnow):
    """If a node should be skipped due to protocol_mux, we do not even open the connection and we set an error."""
    # arrange
    skip_function = mocker.patch('astrolabe.network.skip_protocol_mux', return_value=True)

    # act
    await discover.discover(tree, [])

    # assert
    assert 'CONNECT_SKIPPED' in list(tree.values())[0].errors
    assert list(tree.values())[0].profile_complete(utcnow)
    assert list(tree.values())[0].get_profile_timestamp() is not None
    provider_mock.open_connection.assert_not_called()
    provider_mock.lookup_name.assert_not_called()
    provider_mock.profile.assert_not_called()
    skip_function.assert_called_once_with(list(tree.values())[0].protocol_mux)


@pytest.mark.asyncio
async def test_discover_case_open_connection_handles_timeout_exception(tree, provider_mock, utcnow):
    """Respects the contractual TimeoutException or ProviderInterface.  If thrown we set TIMEOUT error
    but do not stop discovering"""
    # arrange
    provider_mock.open_connection.side_effect = TimeoutException

    # act
    await discover.discover(tree, [])

    assert 'TIMEOUT' in list(tree.values())[0].errors
    assert list(tree.values())[0].profile_complete(utcnow)
    assert list(tree.values())[0].get_profile_timestamp() is not None
    provider_mock.lookup_name.assert_not_called()
    provider_mock.profile.assert_not_called()


@pytest.mark.asyncio
async def test_discover_case_open_connection_handles_timeout(tree, provider_mock, cli_args_mock):
    """A natural timeout during ProviderInterface::open_connections is also handled by setting TIMEOUT error"""
    # arrange
    cli_args_mock.connection_timeout = .1

    async def slow_open_connection(_):
        await asyncio.sleep(1)
    provider_mock.open_connection.side_effect = slow_open_connection

    # act
    await discover.discover(tree, [])

    assert 'TIMEOUT' in list(tree.values())[0].errors
    provider_mock.lookup_name.assert_not_called()
    provider_mock.profile.assert_not_called()


@pytest.mark.asyncio
async def test_discover_case_open_connection_handles_exceptions(tree, provider_mock):
    """Handle any exceptions thrown by ProviderInterface::open_connection.
       We never exit the main program"""
    # arrange
    provider_mock.open_connection.side_effect = Exception('BOOM')

    # act/assert
    await discover.discover(tree, [])
    await _wait_for_all_tasks_to_complete()


# Calls to ProviderInterface::lookup_name
@pytest.mark.asyncio
async def test_discover_case_lookup_name_uses_cache(tree, provider_mock, ps_mock, protocol_mock):
    """Validate the calls to lookup_name for the same address are cached.  We uses 3 levels of the tree
       to ensure that the 2nd time calls are made for a node of this address, that there has been async
       propagation time for caching"""
    # arrange
    name1 = 'foo_name1'
    node1 = list(tree.values())[0]
    node2 = node.NodeTransport('PS_NAME', provider_mock.ref, protocol_mock, 'whatever', 'foo_addy2')
    node2_child = node.NodeTransport('PS_NAME', provider_mock.ref, protocol_mock, node1.protocol_mux, node1.address)
    provider_mock.lookup_name.side_effect = [name1, 'node_2_service_name', name1]
    provider_mock.profile.side_effect = [[node2], [node2_child], []]
    ps_mock.providers = [provider_mock.ref()]

    # act
    await discover.discover(tree, [])
    await _wait_for_all_tasks_to_complete()

    # assert
    assert provider_mock.lookup_name.call_count == 2


@pytest.mark.asyncio
async def test_discover_case_lookup_name_handles_timeout(tree, provider_mock, cli_args_mock):
    """Timeout is handled during lookup_name and does not result in a sys.exit"""
    # arrange
    cli_args_mock.timeout = .1

    async def slow_lookup_name(address):  # pylint:disable=unused-argument  # it has to be this way
        await asyncio.sleep(1)
    provider_mock.lookup_name = slow_lookup_name

    # act/assert
    await discover.discover(tree, [])


@pytest.mark.asyncio
async def test_discover_case_lookup_name_handles_exceptions(tree, provider_mock):
    """Any exceptions thrown by lookup_name are handled and do not result in a sys.exit"""
    # arrange
    provider_mock.lookup_name.side_effect = Exception('BOOM')

    # act/assert
    await discover.discover(tree, [])


# pylint:disable=too-many-arguments,too-many-positional-arguments
# Calls to ProviderInterface::profile
@pytest.mark.asyncio
@pytest.mark.parametrize('name,profile_expected,warning', [(None, True, 'NAME_LOOKUP_FAILED'), ('foo', True, None)])
async def test_discover_case_profile_based_on_name(name, profile_expected, warning, tree, provider_mock, ps_mock):
    """Depending on whether provider.name_lookup() returns a name - we should or should not profile()"""
    # arrange
    provider_mock.lookup_name.return_value = name
    ps_mock.providers = [provider_mock.ref()]

    # act
    await discover.discover(tree, [])

    # assert
    assert provider_mock.profile.called == profile_expected
    if warning:
        assert warning in list(tree.values())[0].warnings


@pytest.mark.asyncio
async def test_discover_case_do_not_profile_node_with_errors(tree, provider_mock):
    """We should not profile for node with any arbitrary error"""
    # arrange
    provider_mock.lookup_name.return_value = 'dummy_name'
    list(tree.values())[0].errors = {'DUMMY': True}

    # act
    await discover.discover(tree, [])

    # assert
    provider_mock.profile.assert_not_called()


@pytest.mark.asyncio
async def test_discover_case_profile_handles_timeout(tree, provider_mock, cli_args_mock, ps_mock_autouse):
    """Timeout is respected during profile and results in a TIMEOUT error"""
    # arrange
    cli_args_mock.timeout = .1

    async def slow_profile(address, pfs, connection):  # pylint:disable=unused-argument  # it has to be this way
        await asyncio.sleep(1)
    provider_mock.lookup_name.return_value = 'dummy'
    provider_mock.profile.side_effect = slow_profile
    ps_mock_autouse.providers = [provider_mock.ref()]

    # act/assert
    await discover.discover(tree, [])

    assert 'TIMEOUT' in list(tree.values())[0].errors.keys()


@pytest.mark.asyncio
async def test_discover_case_profile_handles_exceptions(tree, provider_mock, cli_args_mock):
    """Any exceptions thrown by profile are handled and we do not exit the program"""
    # arrange
    cli_args_mock.timeout = .1
    provider_mock.lookup_name.return_value = 'dummy'
    provider_mock.open_connection.side_effect = Exception('BOOM')

    # act/assert
    await discover.discover(tree, [])


# handle Cycles
@pytest.mark.asyncio
async def test_discover_case_cycle(tree, provider_mock, utcnow):
    """Cycles should be detected, name lookup should still happen for them, but profile should not"""
    # arrange
    cycle_service_name = 'foops_i_did_it_again'
    provider_mock.lookup_name.return_value = cycle_service_name

    # act
    await discover.discover(tree, [cycle_service_name])

    # assert
    assert 'CYCLE' in list(tree.values())[0].errors
    assert list(tree.values())[0].profile_complete(utcnow)
    assert list(tree.values())[0].get_profile_timestamp() is not None
    provider_mock.lookup_name.assert_called_once()
    provider_mock.profile.assert_not_called()


@pytest.mark.parametrize("ip_addr,expected_public,desc", [
    # Public IP addresses
    ("52.84.167.93", True, "random public IP"),
    ("104.18.22.46", True, "random public IP"),
    ("52.84.167.93", True, "random public IP"),
    ("8.8.8.8", True, "public IP (Google DNS)"),
    ("0.0.0.0", True, "unspecified IP"),

    # Private IP addresses
    ("10.0.0.1", False, "private IP (10.x.x.x)"),
    ("172.16.0.1", False, "private IP (172.16-31.x.x)"),
    ("192.168.1.1", False, "private IP (192.168.x.x)"),

    # Special cases
    ("127.0.0.1", False, "loopback IP"),
    ("224.0.0.1", False, "multicast IP"),
    ("169.254.0.1", False, "link-local IP"),

    # Invalid IP
    ("not-an-ip", False, "invalid IP format"),
])
def test_create_node_ip_address_classification(mocker, ip_addr, expected_public, desc):
    """Tests the IP address classification logic through the create_node method"""
    # arrange
    mocker.patch('astrolabe.discover.providers.get_provider_by_ref')
    nt = mocker.MagicMock(address=ip_addr)

    # act
    _, node = discover.create_node(nt)

    # assert
    assert node.public_ip == expected_public, f"public_ip flag wrong for {desc}: {ip_addr}"


# def test_create_node_with_disabled_provider(mocker):
#     """Tests that create_node correctly handles disabled providers"""
#     # Mock constants.ARGS settings
#     mocker.patch('astrolabe.discover.constants.ARGS.obfuscate', False)
#     mocker.patch('astrolabe.discover.constants.ARGS.disable_providers', ["disabled-provider"])
#
#     # Mock provider
#     provider_mock = mocker.MagicMock()
#     provider_mock.is_container_platform.return_value = False
#     mocker.patch('astrolabe.discover.providers.get_provider_by_ref', return_value=provider_mock)
#
#     # Create NodeTransport with a disabled provider
#     transport = mocker.MagicMock(
#         profile_strategy_name="test-strategy",
#         protocol=mocker.MagicMock(ref="test-protocol"),
#         protocol_mux="test-mux",
#         provider="disabled-provider",
#         from_hint=False,
#         address="8.8.8.8",
#         debug_identifier="test-identifier",
#         metadata={},
#         node_type=mocker.MagicMock(),
#         num_connections=1
#     )
#
#     # Call the function being tested
#     node_ref, node = discover.create_node(transport)
#
#     # Should return empty ref and None node for disabled provider
#     assert node_ref == ""
#     assert node is None


@pytest.mark.asyncio
async def test_discover_case_service_name_rewrite_cycle_detected(tree, provider_mock, mocker):
    """Validate cycles are detected for rewritten service names"""
    # arrange
    cycle_service_name = 'foops_i_did_it_again'
    provider_mock.lookup_name.return_value = 'original_service_name'
    rsn_mock = mocker.patch('astrolabe.network.rewrite_service_name')
    rsn_mock.side_effect = None
    rsn_mock.return_value = cycle_service_name

    # act
    await discover.discover(tree, [cycle_service_name])

    # assert
    assert 'CYCLE' in list(tree.values())[0].errors


# Parsing of ProviderInterface::profile
# pylint:disable=too-many-locals
@pytest.mark.asyncio
@pytest.mark.parametrize('protocol_mux,address,debug_identifier,num_connections,warnings,errors', [
    ('foo_mux', 'bar_address', 'baz_name', 100, [], []),
    ('foo_mux', 'bar_address', 'baz_name', None, [], []),
    ('foo_mux', 'bar_address', None, None, [], []),
    ('foo_mux', 'bar_address', 'baz_name', 0, ['DEFUNCT'], []),
    # ('foo_mux', None, None, None, [], ['NULL_ADDRESS']),  # current known bug, address/alias required to save node!
])
async def test_discover_case_profile_results_parsed(protocol_mux, address, debug_identifier, num_connections, warnings,
                                                    errors, tree, provider_mock, ps_mock, protocol_mock):
    """Crawl results are parsed into Node objects.  We detect 0 connections as a "DEFUNCT" node.  `None` address
    is acceptable, but is detected as a "NULL_ADDRESS" node"""
    # arrange
    seed = list(tree.values())[0]
    child_nt = node.NodeTransport(
        'PS_NAME', provider_mock.ref(), protocol_mock, protocol_mux, address,
        debug_identifier=debug_identifier,
        num_connections=num_connections
    )
    provider_mock.lookup_name.side_effect = ['seed_name', 'child_name']
    provider_mock.profile.side_effect = [[child_nt], []]
    ps_mock.providers = [provider_mock.ref()]

    # act
    await discover.discover(tree, [])
    await _wait_for_all_tasks_to_complete()

    # assert
    children = _fake_database.get_connections(seed)
    assert 1 == len(children)
    child: node.Node = children[list(children)[0]]
    assert protocol_mux == child.protocol_mux
    assert address == child.address
    for warning in warnings:
        assert warning in child.warnings
    for error in errors:
        assert error in child.errors


# Recursive calls to discover::discover()
@pytest.mark.asyncio
async def test_discover_case_children_with_address_discovered(tree, provider_mock, ps_mock, protocol_mock):
    """Discovered children with an address are subsequently discovered """
    # arrange
    child_nt = node.NodeTransport('PS_NAME', provider_mock.ref(), protocol_mock, 'dummy_protocol_mux', 'dummy_address')
    provider_mock.lookup_name.side_effect = ['seed_name', 'child_name']
    provider_mock.profile.side_effect = [[child_nt], []]
    ps_mock.providers = [provider_mock.ref()]

    # act
    await discover.discover(tree, [])
    await _wait_for_all_tasks_to_complete()

    # assert
    children = _fake_database.get_connections(list(tree.values())[0])
    assert len(children) == 1
    child_node = list(children.values())[0]
    assert child_node.address == 'dummy_address'


@pytest.mark.asyncio
async def test_discover_case_children_without_address_not_profiled(tree, provider_mock, mocker, protocol_mock):
    """Discovered children without an address are not recursively profiled """
    # arrange
    child_nt = node.NodeTransport('PS_NAME', provider_mock.ref(), protocol_mock, 'dummy_protocol_mux')
    provider_mock.lookup_name.return_value = 'dummy'
    provider_mock.profile.return_value = [child_nt]
    # pylint:disable=protected-access
    discover_node_spy = mocker.patch('astrolabe.discover._discover_node', side_effect=discover._discover_node)

    await discover.discover(tree, [])
    await _wait_for_all_tasks_to_complete()
    # assert
    assert 1 == discover_node_spy.call_count


# Hints
@pytest.mark.asyncio
async def test_discover_case_hint_attributes_set(tree, provider_mock, hint_mock, mocker):
    """For hints used in discovering... attributes are correctly translated from the Hint the Node"""
    # arrange
    mocker.patch('astrolabe.network.hints', return_value=[hint_mock])
    hint_nt = node.NodeTransport('PS_NAME', constants.PROVIDER_HINT, hint_mock.protocol, 'dummy_protocol_mux',
                                 'dummy_address', from_hint=True, debug_identifier='dummy_debug_id')
    provider_mock.take_a_hint.side_effect = [[hint_nt], []]
    provider_mock.lookup_name.side_effect = ['dummy', None]
    providers_get_mock = mocker.patch('astrolabe.providers.get_provider_by_ref', return_value=provider_mock)

    # act
    await discover.discover(tree, [])
    await _wait_for_all_tasks_to_complete()

    # assert
    children = _fake_database.get_connections(list(tree.values())[0])
    child = list(children.values())[0]
    assert child.from_hint
    assert child.protocol == hint_mock.protocol
    assert child.service_name == hint_nt.debug_identifier
    providers_get_mock.assert_any_call(hint_mock.instance_provider)


@pytest.mark.asyncio
async def test_discover_case_hint_name_used(tree, provider_mock, hint_mock, mocker):
    """Hint `debug_identifier` field is respected in discovering
    (and overwritten by new name, not overwritten by None)"""
    # arrange
    mocker.patch('astrolabe.network.hints', return_value=[hint_mock])
    hint_nt = node.NodeTransport('PS_NAME', provider_mock.ref(), hint_mock.protocol, 'dummy_protocol_mux',
                                 'dummy_address', from_hint=True, debug_identifier='dummy_debug_id')
    provider_mock.take_a_hint.side_effect = [[hint_nt], []]
    provider_mock.lookup_name.side_effect = ['dummy', None]

    # act
    await discover.discover(tree, [])
    await _wait_for_all_tasks_to_complete()

    # assert
    parent_node = list(tree.values())[0]
    children = _fake_database.get_connections(parent_node)
    hint_child_node = list(children.values())[0]
    assert hint_child_node.service_name == hint_nt.debug_identifier


@pytest.mark.asyncio
async def test_discover_case_profile_skip_protocol_mux(tree, provider_mock, mocker, protocol_mock):
    """Children discovered on these muxes are neither included as children - nor discovered"""
    # arrange
    child_nt = node.NodeTransport('PS_NAME', provider_mock.ref(), protocol_mock, 'foo_mux', 'dummy_address')
    provider_mock.profile.return_value = [child_nt]
    # pylint:disable=protected-access
    discover_node_spy = mocker.patch('astrolabe.discover._discover_node', side_effect=discover._discover_node)
    mocker.patch('astrolabe.network.skip_protocol_mux', return_value=True)

    # act
    await discover.discover(tree, [])
    await _wait_for_all_tasks_to_complete()

    # assert
    test_node = list(tree.values())[0]
    children = _fake_database.get_connections(test_node)
    assert len(children) == 0
    assert discover_node_spy.call_count == 1


@pytest.mark.asyncio
async def test_discover_case_profile_skip_address(tree, provider_mock, mocker, protocol_mock):
    """Children discovered on these addresses are neither included as children - nor discovered"""
    # arrange
    child_nt = node.NodeTransport('PS_NAME', provider_mock.ref(), protocol_mock, 'foo_mux', 'dummy_address')
    provider_mock.profile.return_value = [child_nt]
    # pylint:disable=protected-access
    discover_node_spy = mocker.patch('astrolabe.discover._discover_node', side_effect=discover._discover_node)
    mocker.patch('astrolabe.network.skip_address', return_value=True)

    # act
    await discover.discover(tree, [])
    await _wait_for_all_tasks_to_complete()

    # assert
    assert len(list(tree.values())[0].children) == 0
    assert discover_node_spy.call_count == 1


# respect CLI args
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
    provider_mock.profile.assert_called_once_with(list(tree.values())[0], [], mocker.ANY)


@pytest.mark.asyncio
async def test_discover_case_respect_cli_disable_providers(tree, provider_mock, cli_args_mock, mocker, protocol_mock):
    """Children discovered which have been determined to use disabled providers - are neither included in the tree
    nor discovered"""
    # arrange
    disable_this_provider = 'foo_provider'
    cli_args_mock.disable_providers = [disable_this_provider]
    child_nt = node.NodeTransport('PS_NAME', disable_this_provider, protocol_mock, 'dummy_mux', 'dummy_address')
    provider_mock.lookup_name.return_value = 'bar_name'
    provider_mock.profile.return_value = [child_nt]
    discover_node_spy = mocker.patch('astrolabe.discover.discover', side_effect=discover.discover)

    # act
    await discover.discover(tree, [])
    await _wait_for_all_tasks_to_complete()

    # assert
    assert 0 == len(list(tree.values())[0].children)
    assert 1 == discover_node_spy.call_count


@pytest.mark.asyncio
async def test_discover_case_respect_cli_max_depth(tree, provider_mock, cli_args_mock, utcnow):
    """We should not profile if max-depth is exceeded"""
    # arrange
    cli_args_mock.max_depth = 0
    provider_mock.lookup_name.return_value = 'dummy_name'

    # act
    await discover.discover(tree, [])

    # assert
    provider_mock.profile.assert_not_called()
    assert list(tree.values())[0].profile_complete(utcnow)
    assert list(tree.values())[0].get_profile_timestamp() is not None


@pytest.mark.asyncio
async def test_discover_case_respect_cli_obfuscate(tree, provider_mock, cli_args_mock, ps_mock_autouse):
    """We need to test a child for protocol mux obfuscation since the tree is already populated with a fully hydrated
        Node - which is past the point of obfuscation"""
    # arrange
    cli_args_mock.obfuscate = True
    seed_service_name = 'actual_service_name_foo'
    child_protocol_mux = 'child_actual_protocol_mux'
    child_nt = node.NodeTransport('FAKE_PS', provider_mock.ref(), ps_mock_autouse.protocol, child_protocol_mux,
                                  'fake_address')
    provider_mock.lookup_name.return_value = seed_service_name
    provider_mock.lookup_name.return_value = 'dummy_service_name'
    provider_mock.profile.side_effect = [[child_nt], []]
    ps_mock_autouse.providers = [provider_mock.ref()]

    # act
    await discover.discover(tree, [])

    # assert
    seed: node.Node = list(tree.values())[0]
    children = _fake_database.get_connections(seed)
    child: node.Node = list(children.values())[0]
    assert seed.service_name != seed_service_name
    assert child.protocol_mux != child_protocol_mux


@pytest.mark.asyncio
@pytest.mark.parametrize('skip_sidecar', [True, False])
async def test_discover_case_respect_cli_skip_sidecar(tree, provider_mock, cli_args_mock, skip_sidecar):
    """Test that --skip-sidecar CLI argument prevents sidecar from being called"""
    # arrange
    cli_args_mock.skip_sidecar = True

    # act
    await discover.discover(tree, [])
    await _wait_for_all_tasks_to_complete()

    # assert
    assert provider_mock.sidecar.call_count == 0 if skip_sidecar else 1
    # discovery normal otherwise
    provider_mock.open_connection.assert_called_once()
    provider_mock.lookup_name.assert_called_once()
    provider_mock.profile.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.parametrize('seeds_only', [True, False])
async def test_discover_case_respect_cli_seeds_only(tree, provider_mock, cli_args_mock, mocker, protocol_mock,
                                                    node_fixture_factory, seeds_only):
    """Test that --seeds-only profiles seed nodes and their children, but not inventory nodes."""
    # Arrange
    cli_args_mock.seeds_only = seeds_only
    seed_node = list(tree.values())[0]

    # arrange child node
    child_nt = node.NodeTransport('PS_NAME', provider_mock.ref(), protocol_mock, 'dummy_protocol_mux', 'child_address')
    provider_mock.lookup_name.return_value = 'dummy_name'
    provider_mock.profile.return_value = [child_nt]

    # arrange inventory_node
    inventory_node = node_fixture_factory()
    inventory_node.provider = 'INV'
    inventory_node.address = 'inventory_node_address'
    _fake_database.save_node(inventory_node)

    # arrange spies
    # pylint:disable=protected-access
    discover_node_spy = mocker.patch('astrolabe.discover._discover_node', side_effect=discover._discover_node)

    # Act
    await discover.discover(tree, [])
    await _wait_for_all_tasks_to_complete()

    # Assert
    # Get addresses of nodes that were profiled
    profiled = [call[0][1].address for call in discover_node_spy.call_args_list]
    assert seed_node.address in profiled
    assert 'child_address' in profiled
    assert inventory_node.address not in profiled if seeds_only else inventory_node.address in profiled


# respect profile_strategy / network configurations
@pytest.mark.asyncio
async def test_discover_case_respect_ps_filter_service_name(tree, provider_mock, ps_mock, mocker):
    """We respect when a service name is configured to be skipped by a specific profile strategy"""
    # arrange
    ps_mock.filter_service_name.return_value = True
    provider_mock.lookup_name.return_value = 'bar_name'

    # act
    await discover.discover(tree, [])

    # assert
    ps_mock.filter_service_name.assert_called_once_with(list(tree.values())[0].service_name)
    provider_mock.profile.assert_called_once_with(list(tree.values())[0], [], mocker.ANY)


@pytest.mark.asyncio
async def test_discover_case_respect_network_service_name_rewrite(tree, provider_mock, mocker):
    """Validate service_name_rewrites are called and used"""
    # arrange
    service_name = 'foo_name'
    rewritten_service_name = 'bar_name'
    provider_mock.lookup_name.return_value = service_name
    rsn_mock = mocker.patch('astrolabe.network.rewrite_service_name')
    rsn_mock.side_effect = None
    rsn_mock.return_value = rewritten_service_name

    # act
    await discover.discover(tree, [])

    # assert
    assert list(tree.values())[0].service_name == rewritten_service_name


@pytest.mark.asyncio
async def test_discover_case_respect_network_skip_protocol_mux(tree, provider_mock, mocker, utcnow):
    """Skip protocol mux is respected for network"""
    # arrange
    skip_function = mocker.patch('astrolabe.network.skip_protocol_mux', return_value=True)

    # act
    await discover.discover(tree, [])

    # assert
    provider_mock.open_connection.assert_not_called()
    provider_mock.lookup_name.assert_not_called()
    provider_mock.profile.assert_not_called()
    skip_function.assert_called_once_with(list(tree.values())[0].protocol_mux)
    assert list(tree.values())[0].profile_complete(utcnow)
    assert list(tree.values())[0].get_profile_timestamp() is not None


@pytest.mark.asyncio
async def test_discover_case_respect_network_skip_address(tree, provider_mock, mocker, utcnow):
    """Skip address is respected for network"""
    # arrange
    skip_function = mocker.patch('astrolabe.network.skip_address', return_value=True)

    # act
    await discover.discover(tree, [])

    # assert
    provider_mock.open_connection.assert_not_called()
    provider_mock.lookup_name.assert_not_called()
    provider_mock.profile.assert_not_called()
    skip_function.assert_called_once_with(list(tree.values())[0].address)
    assert list(tree.values())[0].profile_complete(utcnow)
    assert list(tree.values())[0].get_profile_timestamp() is not None


@pytest.mark.asyncio
async def test_discover_case_respect_network_skip_service_name(tree, provider_mock, mocker, utcnow):
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
    assert list(tree.values())[0].profile_complete(utcnow)
    assert list(tree.values())[0].get_profile_timestamp() is not None
