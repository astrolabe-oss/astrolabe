import asyncio
import os
import pytest
from dataclasses import replace
from typing import Dict, List

from astrolabe.profile_strategy import ProfileStrategy
from astrolabe.network import Protocol
from astrolabe.node import Node


@pytest.fixture(autouse=True)
def cli_args_mock(mocker):
    args = mocker.patch('astrolabe.constants.ARGS', autospec=True)
    args.max_depth = 100
    return args


@pytest.fixture
def dummy_protocol_ref():
    return 'DUM'


@pytest.fixture
def profile_strategy_fixture() -> ProfileStrategy:
    return ProfileStrategy('', '', None, '', {}, {}, {}, {})


@pytest.fixture
def protocol_fixture(dummy_protocol_ref) -> Protocol:
    return Protocol(dummy_protocol_ref, '', True, False)


@pytest.fixture
def node_fixture_factory(profile_strategy_fixture, protocol_fixture) -> callable:
    def _factory() -> Node:
        nonlocal profile_strategy_fixture, protocol_fixture
        profile_strategy_fixture = replace(profile_strategy_fixture, protocol=protocol_fixture)
        return Node(
            address='1.2.3.4',
            profile_strategy=profile_strategy_fixture,
            protocol=protocol_fixture,
            protocol_mux='dummy_mux',
            provider='dummy_provider',
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
    child.address = '5.6.7.8'
    seed.children = {'child_node': child}

    return tree_stubbed


@pytest.fixture
def tree_named(tree):
    """single node tree fixture - where the node has the service_name field filled out"""
    list(tree.values())[0].service_name = 'dummy'

    return tree


@pytest.fixture()
def astrolabe_d(tmp_path, mocker) -> str:
    """Return temp profile_strategy dir {str}, also making tmp dir on the filesystem and patching globals.ASTROLABE_DIR
    autouse=True so that this is mocked out for all module tests
    """
    astrolabe_d = os.path.join(tmp_path, 'astrolabe.d')
    os.mkdir(astrolabe_d)
    mocker.patch('astrolabe.profile_strategy.constants.ASTROLABE_DIR', astrolabe_d)

    return astrolabe_d


@pytest.fixture
def builtin_providers() -> List[str]:
    return ['ssh', 'k8s', 'aws']


@pytest.fixture
async def get_event_loop():
    return asyncio.get_running_loop()
