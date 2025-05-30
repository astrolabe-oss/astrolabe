from dataclasses import replace
from typing import Dict
import asyncio
import sys

import pytest

from astrolabe.plugins import export_ascii
from astrolabe.node import Node
from tests import _fake_database


@pytest.fixture(autouse=True)
def patch_database_autouse(patch_database):  # pylint:disable=unused-argument
    pass


@pytest.fixture(autouse=True)
def set_default_cli_args(cli_args_mock):
    cli_args_mock.export_ascii_verbose = False
    cli_args_mock.debug = False


async def _helper_export_tree_with_timeout(tree: Dict[str, Node]) -> None:
    await asyncio.wait_for(export_ascii.export_tree(tree, [], sys.stdout), .1)


@pytest.fixture
def mock_termcolor_colored(mocker):
    mock = mocker.patch('astrolabe.plugins.export_ascii.colored', autospec=True)
    mock.side_effect = lambda text, color, force_color: 'foo'
    return mock


def test_colored_force(mock_termcolor_colored):
    test_text = "Hello, World!"
    test_color = "red"
    _ = export_ascii.colored_force(test_text, test_color)
    # Assert that termcolor_colored was called with the correct arguments
    mock_termcolor_colored.assert_called_once_with(test_text, test_color, force_color=True)


@pytest.mark.asyncio
async def test_export_tree_case_seed(tree_stubbed, capsys):
    """Test a single seed node is printed correctly - no errors or edge cases"""
    # arrange
    seed = tree_stubbed[list(tree_stubbed)[0]]
    seed.set_profile_timestamp()

    # act
    await _helper_export_tree_with_timeout(tree_stubbed)
    captured = capsys.readouterr()

    # assert
    assert f"\n{seed.service_name} [{seed.node_type.name}] ({seed.provider}:{seed.node_name})\n" == captured.out


@pytest.mark.asyncio
async def test_export_tree_case_child(tree_stubbed_with_child, capsys):
    """Test a single child node is printed correctly - no errors or edge cases"""
    # arrange
    seed = tree_stubbed_with_child[list(tree_stubbed_with_child)[0]]
    child = list(_fake_database.get_connections(seed).values())[0]

    # act
    await _helper_export_tree_with_timeout(tree_stubbed_with_child)
    captured = capsys.readouterr()

    # assert
    expected = ("\n"
                f"{seed.service_name} [{seed.node_type.name}] ({seed.provider}:{seed.node_name})\n"
                f" └--{child.protocol.ref}--> {child.service_name} [{child.node_type.name}] ({child.provider}:{child.node_name})\n")  # noqa: E501  pylint:disable=line-too-long
    assert expected == captured.out


# wait_for: wait for service name to print
@pytest.mark.asyncio
async def test_export_tree_case_discover_not_complete(tree_stubbed, capsys, mocker):
    """export should not happen for a node unless `profile_complete()` returns True"""
    # arrange
    seed = tree_stubbed[list(tree_stubbed)[0]]
    mocker.patch.object(seed, 'profile_complete', return_value=False)

    # act/assert
    with pytest.raises(asyncio.TimeoutError):
        await _helper_export_tree_with_timeout(tree_stubbed)
    captured = capsys.readouterr()
    assert seed.service_name not in captured


@pytest.mark.asyncio
async def test_export_tree_case_children_namelookup_incomplete(tree_stubbed_with_child, capsys, mocker):
    """export should not happen for any children until all children names have been looked up"""
    # arrange
    seed = tree_stubbed_with_child[list(tree_stubbed_with_child)[0]]
    child = list(_fake_database.get_connections(seed).values())[0]
    another_child = replace(child, service_name='another_child')
    _fake_database.connect_nodes(seed, another_child)
    mocker.patch.object(child, 'profile_complete', return_value=True)
    mocker.patch.object(another_child, 'profile_complete', return_value=True)
    mocker.patch.object(child, 'name_lookup_complete', return_value=True)
    mocker.patch.object(another_child, 'name_lookup_complete', return_value=False)

    # act/assert
    with pytest.raises(asyncio.TimeoutError):
        await _helper_export_tree_with_timeout(tree_stubbed_with_child)
    captured = capsys.readouterr()
    assert seed.service_name in captured.out
    assert child.service_name not in captured.out
    assert another_child.service_name not in captured.out


@pytest.mark.asyncio
@pytest.mark.parametrize('error', ['NULL_ADDRESS', 'TIMEOUT', 'AWS_LOOKUP_FAILED'])
async def test_export_tree_case_child_errors(error, tree_stubbed_with_child, capsys):
    """A node with errors and no service name is displayed correctly"""
    # arrange
    seed = tree_stubbed_with_child[list(tree_stubbed_with_child)[0]]
    child = list(_fake_database.get_connections(seed).values())[0]

    child.service_name = None
    child.errors = {error: True}

    # act
    await _helper_export_tree_with_timeout(tree_stubbed_with_child)
    captured = capsys.readouterr()

    # assert
    expected = f" └--{child.protocol.ref}--? \x1b[31m{{ERR:{error}}} \x1b[0m{child.address} [{child.node_type.name}] ({child.provider}:{child.node_name})"  # noqa: E501  pylint:disable=line-too-long
    assert expected in captured.out


@pytest.mark.asyncio
async def test_export_tree_case_child_warning_cycle(tree_stubbed_with_child, capsys):
    """A node with a CYCLE warning is displayed correctly"""
    # arrange
    seed = tree_stubbed_with_child[list(tree_stubbed_with_child)[0]]
    child = list(_fake_database.get_connections(seed).values())[0]
    child.errors = {'CYCLE': True}

    # act
    await _helper_export_tree_with_timeout(tree_stubbed_with_child)
    captured = capsys.readouterr()

    # assert
    assert f" <--{child.protocol.ref}--> \x1b[31m{{ERR:CYCLE}} \x1b[0m{child.service_name}" in captured.out


@pytest.mark.asyncio
async def test_export_tree_case_child_warning_defunct(cli_args_mock, tree_stubbed_with_child, capsys):
    """A node with a DEFUNCT warning is displayed correctly"""
    # arrange
    cli_args_mock.hide_defunct = False
    seed = tree_stubbed_with_child[list(tree_stubbed_with_child)[0]]
    child = list(_fake_database.get_connections(seed).values())[0]
    child.warnings = {'DEFUNCT': True}

    # act
    await _helper_export_tree_with_timeout(tree_stubbed_with_child)
    captured = capsys.readouterr()

    # assert
    assert f" └--{child.protocol.ref}--x \x1b[33m{{WARN:DEFUNCT}} \x1b[0m{child.service_name}" in captured.out


@pytest.mark.asyncio
async def test_export_tree_case_hide_defunct(cli_args_mock, tree_stubbed_with_child, capsys):
    """A node with a DEFUNCT warning is displayed correctly"""
    # arrange
    cli_args_mock.hide_defunct = True
    seed = tree_stubbed_with_child[list(tree_stubbed_with_child)[0]]
    child = list(_fake_database.get_connections(seed).values())[0]
    child.warnings = {'DEFUNCT': True}

    # act
    await _helper_export_tree_with_timeout(tree_stubbed_with_child)
    captured = capsys.readouterr()

    # assert
    assert 'DEFUNCT' not in captured.out


@pytest.mark.asyncio
async def test_export_tree_case_respect_cli_max_depth(cli_args_mock, tree_stubbed_with_child, capsys):
    """--max-depth arg is respected"""
    # arrange
    cli_args_mock.max_depth = 0
    seed = tree_stubbed_with_child[list(tree_stubbed_with_child)[0]]
    child = list(_fake_database.get_connections(seed).values())[0]
    child.service_name = 'DEPTH_1'

    # act
    await _helper_export_tree_with_timeout(tree_stubbed_with_child)
    captured = capsys.readouterr()

    # assert
    assert child.service_name not in captured.out


@pytest.mark.asyncio
async def test_export_tree_case_respect_cli_seeds_only(cli_args_mock, tree_stubbed_with_child, capsys, mocker):
    """seed and child are both printed even if seed is not profiled due to --seeds-only flag"""
    # arrange
    cli_args_mock.seeds_only = True
    seed = tree_stubbed_with_child[list(tree_stubbed_with_child)[0]]
    child = list(_fake_database.get_connections(seed).values())[0]
    mocker.patch.object(child, 'profile_complete', return_value=False)

    # act
    await _helper_export_tree_with_timeout(tree_stubbed_with_child)
    captured = capsys.readouterr()

    # assert
    assert child.service_name in captured.out


@pytest.mark.asyncio
async def test_export_tree_case_last_child(tree_stubbed_with_child, node_fixture, capsys):
    """A single node with multiple children, the last child printed is slightly different"""
    # arrange
    seed = tree_stubbed_with_child[list(tree_stubbed_with_child)[0]]
    child = list(_fake_database.get_connections(seed).values())[0]
    last_child = replace(node_fixture, service_name='last_child_service', address='last_child_address', children={})
    _fake_database.connect_nodes(seed, last_child)

    # act
    await _helper_export_tree_with_timeout(tree_stubbed_with_child)
    captured = capsys.readouterr()

    # assert
    assert f"|--{child.protocol.ref}--> {child.service_name}" in captured.out
    assert f"└--{last_child.protocol.ref}--> {last_child.service_name} " in captured.out


@pytest.mark.asyncio
async def test_export_tree_case_merged_nodes(tree_stubbed_with_child, capsys):
    """A single node with multiple children, the last child printed is slightly different"""
    # arrange
    seed = tree_stubbed_with_child[list(tree_stubbed_with_child)[0]]
    child = list(_fake_database.get_connections(seed).values())[0]
    redundant_child = replace(child, address='asdf-zxc', protocol_mux='some_other_mux')
    _fake_database.connect_nodes(seed, redundant_child)
    # - we have to capture this now because export_tree will mutate these objects!

    # act
    await _helper_export_tree_with_timeout(tree_stubbed_with_child)
    captured = capsys.readouterr()

    # assert
    assert f"--> {child.service_name} [{child.node_type.name}] ({child.provider}:{child.node_name})" in captured.out


## TODO: Commenting test, for now.  This is a fairly complex display feature ... when ascii is no longer
#        an important exporter...
# @pytest.mark.asyncio
# async def test_export_tree_case_node_hint_merged(tree_named, protocol_fixture, node_fixture_factory, capsys):
#     """Tests that two child nodes which are on the same protocol/mux are merged together if 1 is a hint"""
#     # arrange
#     protocol_ref, protocol_mux, error, service_name = ('FOO', 'barbaz', 'BUZZ', 'qux')
#     protocol_fixture = replace(protocol_fixture, ref=protocol_ref)
#     child_node_discovered = replace(node_fixture_factory(), service_name=None, errors={error: True})
#     child_node_discovered.protocol = protocol_fixture
#     child_node_discovered.protocol_mux = protocol_mux
#     child_node_hint = replace(node_fixture_factory(), service_name=service_name, from_hint=True)
#     child_node_hint.protocol = protocol_fixture
#     child_node_hint.protocol_mux = protocol_mux
#     tree = tree_named
#     the_node = list(tree.values())[0]
#     _fake_database.connect_nodes(the_node, child_node_discovered)
#     _fake_database.connect_nodes(the_node, child_node_hint)
#     the_node.set_profile_timestamp()
#     child_node_discovered.set_profile_timestamp()
#     child_node_hint.set_profile_timestamp()
#
#     # act
#     await _helper_export_tree_with_timeout(tree)
#     captured = capsys.readouterr()
#
#     # assert
#     assert 'UNKNOWN' not in captured.out
#     assert f"\x1b[36m{{INFO:FROM_HINT}} \x1b[0m\x1b[31m{{ERR:{error}}} \x1b[0m{service_name}" in captured.out


## TODO: Commenting test, for now.  This is a fairly complex display feature ... when ascii is no longer
#        an important exporter...
# @pytest.mark.asyncio
# async def test_export_tree_case_node_nonhint_not_merged(tree_named, protocol_fixture, node_fixture_factory, capsys):
#     """
#     Ensures that 2 children on the same protocol/mux are not accidentally merged into one
#     Ensures that 2 children not on the same protocol/mux are not accidentally merged into one
#     """
#     # arrange
#     protocol_ref, protocol_mux_1, protocol_mux_2, child_1_name, child_2_name, child_3_name = \
#         ('FOO', 'barbaz', 'buzzqux', 'quxx', 'quz', 'clorge')
#     protocol_fixture = replace(protocol_fixture, ref=protocol_ref)
#     child_1 = replace(node_fixture_factory(), service_name=child_1_name)
#     child_1.protocol = protocol_fixture
#     child_1.protocol_mux = protocol_mux_1
#     child_1.set_profile_timestamp()
#     child_2 = replace(node_fixture_factory(), service_name=child_2_name)
#     child_2.protocol = protocol_fixture
#     child_2.protocol_mux = protocol_mux_1
#     child_2.set_profile_timestamp()
#     child_3 = replace(node_fixture_factory(), service_name=child_3_name)
#     child_3.protocol = protocol_fixture
#     child_3.protocol_mux = protocol_mux_2
#     child_3.set_profile_timestamp()
#
#     parent_node = list(tree_named.values())[0]
#     _fake_database.connect_nodes(parent_node, child_1)
#     _fake_database.connect_nodes(parent_node, child_2)
#     _fake_database.connect_nodes(parent_node, child_3)
#     parent_node.set_profile_timestamp()
#
#     # act
#     await _helper_export_tree_with_timeout(tree_named)
#     captured = capsys.readouterr()
#
#     assert child_1_name in captured.out
#     assert child_2_name in captured.out
#     assert child_3_name in captured.out
