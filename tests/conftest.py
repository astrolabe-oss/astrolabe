import asyncio
from pathlib import Path
from dataclasses import replace
from typing import Dict, List
from unittest.mock import MagicMock

import pytest

from astrolabe.profile_strategy import ProfileStrategy
from astrolabe.network import Protocol
from astrolabe.node import Node

from tests import _fake_database


@pytest.fixture
def patch_database(mocker):
    mocker.patch('astrolabe.database.save_node', side_effect=_fake_database.save_node)
    mocker.patch('astrolabe.database.connect_nodes', side_effect=_fake_database.connect_nodes)
    mocker.patch('astrolabe.database.get_connections', side_effect=_fake_database.get_connections)
    mocker.patch('astrolabe.database.get_nodes_unprofiled', side_effect=_fake_database.get_nodes_unprofiled)
    mocker.patch('astrolabe.database.get_node_by_address', side_effect=_fake_database.get_node_by_address)
    mocker.patch('astrolabe.database.get_nodes_pending_dnslookup', side_effect=_fake_database.get_nodes_pending_dnslookup)  # NOQA
    mocker.patch('astrolabe.database.node_is_k8s_load_balancer', side_effect=_fake_database.node_is_k8s_load_balancer)
    mocker.patch('astrolabe.database.node_is_k8s_service', side_effect=_fake_database.node_is_k8s_service)
    _fake_database._node_index_by_address = {}  # pylint:disable=protected-access
    _fake_database._node_index_by_dnsname = {}  # pylint:disable=protected-access
    _fake_database._node_primary_index = {}  # pylint:disable=protected-access


@pytest.fixture(autouse=True)
def cli_args_mock(mocker):
    args = mocker.patch('astrolabe.constants.ARGS', autospec=True)
    args.max_depth = 100
    args.seeds_only = False
    return args


@pytest.fixture
def dummy_protocol_ref():
    return 'DUM'


@pytest.fixture
def mock_provider_ref() -> str:
    return 'mock_provider'


@pytest.fixture
def protocol_mock(mocker, dummy_protocol_ref) -> MagicMock:
    protocol_mock = mocker.patch('astrolabe.network.Protocol')
    protocol_mock.ref = dummy_protocol_ref

    return protocol_mock


@pytest.fixture
def profile_strategy_fixture() -> ProfileStrategy:
    return ProfileStrategy('', '', None, '', {'shell_command': 'foo'}, {}, {}, {})


@pytest.fixture
def ps_mock(protocol_fixture, mocker, mock_provider_ref) -> MagicMock:
    """it is a required fixture to include, whether or not it is used explicitly, in or to mock profile"""
    ps_mock = mocker.patch('astrolabe.profile_strategy.ProfileStrategy', autospec=True)
    mocker.patch('astrolabe.profile_strategy.profile_strategies', [ps_mock])
    ps_mock.name = 'FAKE'
    ps_mock.filter_service_name.return_value = False
    ps_mock.protocol = protocol_fixture
    ps_mock.provider_args = {}
    ps_mock.providers = [mock_provider_ref]

    return ps_mock


@pytest.fixture
def protocol_fixture(dummy_protocol_ref) -> Protocol:
    return Protocol(dummy_protocol_ref, '', True, False)


@pytest.fixture
def node_fixture_factory(protocol_fixture, provider_mock) -> callable:
    def _factory() -> Node:
        nonlocal protocol_fixture
        return Node(
            address='1.2.3.4',
            profile_strategy_name='bar',
            protocol=protocol_fixture,
            protocol_mux='dummy_mux',
            provider=provider_mock.ref(),
            from_hint=False
        )
    return _factory


@pytest.fixture
def node_fixture(node_fixture_factory) -> Node:
    return node_fixture_factory()


@pytest.fixture
def tree(node_fixture, cli_args_mock) -> Dict[str, Node]:
    seed_noderef = 'dummy'
    tree = {seed_noderef: node_fixture}
    cli_args_mock.seeds = [seed_noderef]

    return tree


@pytest.fixture
def tree_stubbed(tree) -> Dict[str, Node]:
    """Tree with seed node having basic attributes stubbed"""
    list(tree.values())[0].service_name = 'foo'
    list(tree.values())[0].address = '1.2.3.4'

    return tree


@pytest.fixture
def tree_stubbed_with_child(tree_stubbed, node_fixture) -> Dict[str, Node]:
    """Stubbed tree, with 1 child added with basic characteristics stubbed"""
    # arrange
    seed = tree_stubbed[list(tree_stubbed)[0]]
    child = replace(node_fixture, service_name='bar')
    child.service_name = 'baz'
    child.children = {}
    child.set_profile_timestamp()
    child.address = '5.6.7.8'
    _fake_database.connect_nodes(seed, child)
    seed.set_profile_timestamp()

    return tree_stubbed


@pytest.fixture
def tree_named(tree):
    """single node tree fixture - where the node has the service_name field filled out"""
    list(tree.values())[0].node_name = 'dummy_node'
    list(tree.values())[0].service_name = 'dummy_service'

    return tree


@pytest.fixture()
def astrolabe_d(tmp_path, mocker) -> Path:
    """Return temp profile_strategy dir {str}, also making tmp dir on the filesystem and patching globals.ASTROLABE_DIR
    autouse=True so that this is mocked out for all module tests
    """
    astrolabe_d = tmp_path / 'astrolabe.d'
    astrolabe_d.mkdir()
    mocker.patch('astrolabe.profile_strategy.config.ASTROLABE_DIR', astrolabe_d)

    return astrolabe_d


@pytest.fixture()
def core_astrolabe_d(tmp_path, mocker) -> Path:
    """Return temp profile_strategy dir {str}, also making tmp dir on the filesystem and patching globals.ASTROLABE_DIR
    autouse=True so that this is mocked out for all module tests
    """
    core_astrolabe_d = tmp_path / 'core' / 'astrolabe.d'
    core_astrolabe_d.mkdir(parents=True)
    mocker.patch('astrolabe.profile_strategy.config.CORE_ASTROLABE_DIR', core_astrolabe_d)

    return core_astrolabe_d


@pytest.fixture
def builtin_providers() -> List[str]:
    return ['ssh', 'k8s', 'aws']


@pytest.fixture
def provider_mock(mocker, mock_provider_ref) -> MagicMock:
    provider_mock = mocker.patch('astrolabe.providers.ProviderInterface', autospec=True)
    provider_mock.ref.return_value = mock_provider_ref
    mocker.patch('astrolabe.providers.get_provider_by_ref', return_value=provider_mock)

    return provider_mock


@pytest.fixture
async def get_event_loop():
    return asyncio.get_running_loop()
