from dataclasses import replace
from typing import Dict
import asyncio
import sys

import pytest

from astrolabe.plugins import export_ascii
from astrolabe.node import Node


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
    assert f"\n{seed.service_name} [{seed.protocol_mux}]\n" == captured.out


@pytest.mark.asyncio
async def test_export_tree_case_child(tree_stubbed_with_child, capsys):
    """Test a single child node is printed correctly - no errors or edge cases"""
    # arrange
    seed = tree_stubbed_with_child[list(tree_stubbed_with_child)[0]]
    child = seed.children[list(seed.children)[0]]

    # act
    await _helper_export_tree_with_timeout(tree_stubbed_with_child)
    captured = capsys.readouterr()

    # assert
    expected = ("\n"
                f"{seed.service_name} [{seed.protocol_mux}]\n"
                f" └--{child.protocol.ref}--> {child.service_name} [port:{child.protocol_mux}]\n")
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
    child = seed.children[list(seed.children)[0]]
    another_child = replace(child, service_name='another_child')
    seed.children['last_child'] = another_child
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
    child = seed.children[list(seed.children)[0]]

    child.service_name = None
    child.errors = {error: True}

    # act
    await _helper_export_tree_with_timeout(tree_stubbed_with_child)
    captured = capsys.readouterr()

    # assert
    assert f" └--{child.protocol.ref}--? \x1b[31m{{ERR:{error}}} \x1b[0m{child.address} [port:{child.protocol_mux}]" \
           in captured.out


@pytest.mark.asyncio
async def test_export_tree_case_child_warning_cycle(tree_stubbed_with_child, capsys):
    """A node with a CYCLE warning is displayed correctly"""
    # arrange
    seed = tree_stubbed_with_child[list(tree_stubbed_with_child)[0]]
    child = seed.children[list(seed.children)[0]]
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
    child = seed.children[list(seed.children)[0]]
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
    child = seed.children[list(seed.children)[0]]
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
    child = seed.children[list(seed.children)[0]]
    child.service_name = 'DEPTH_1'

    # act
    await _helper_export_tree_with_timeout(tree_stubbed_with_child)
    captured = capsys.readouterr()

    # assert
    assert child.service_name not in captured.out


@pytest.mark.asyncio
async def test_export_tree_case_last_child(tree_stubbed_with_child, node_fixture, capsys):
    """A single node with multiple children, the last child printed is slightly different"""
    # arrange
    seed = tree_stubbed_with_child[list(tree_stubbed_with_child)[0]]
    child = seed.children[list(seed.children)[0]]
    last_child = replace(node_fixture, service_name='last_child_service', address='last_child_address', children={})
    seed.children['last_child'] = last_child

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
    child = seed.children[list(seed.children)[0]]
    redundant_child = replace(child, protocol_mux='some_other_mux')
    seed.children['redundant_child'] = redundant_child
    # - we have to capture this now because export_tree will mutate these objects!
    expected_merged_mux = f"{child.protocol_mux},{redundant_child.protocol_mux}"

    # act
    await _helper_export_tree_with_timeout(tree_stubbed_with_child)
    captured = capsys.readouterr()

    # assert
    assert f"--> {child.service_name} [port:{expected_merged_mux}]" in captured.out


@pytest.mark.asyncio
async def test_export_tree_case_node_hint_merged(tree_named, protocol_fixture, node_fixture_factory, capsys):
    """Tests that two child nodes which are on the same protocol/mux are merged together if 1 is a hint"""
    # arrange
    protocol_ref, protocol_mux, error, service_name = ('FOO', 'barbaz', 'BUZZ', 'qux')
    protocol_fixture = replace(protocol_fixture, ref=protocol_ref)
    child_node_discovered = replace(node_fixture_factory(), service_name=None, errors={error: True})
    child_node_discovered.protocol = protocol_fixture
    child_node_discovered.protocol_mux = protocol_mux
    child_node_hint = replace(node_fixture_factory(), service_name=service_name, from_hint=True)
    child_node_hint.protocol = protocol_fixture
    child_node_hint.protocol_mux = protocol_mux
    tree = tree_named
    list(tree.values())[0].children = {'discovered': child_node_discovered, 'hinted': child_node_hint}
    list(tree.values())[0].set_profile_timestamp()
    child_node_discovered.set_profile_timestamp()
    child_node_hint.set_profile_timestamp()

    # act
    await _helper_export_tree_with_timeout(tree)
    captured = capsys.readouterr()

    # assert
    assert 'UNKNOWN' not in captured.out
    assert f"\x1b[36m{{INFO:FROM_HINT}} \x1b[0m\x1b[31m{{ERR:{error}}} \x1b[0m{service_name}" in captured.out


@pytest.mark.asyncio
async def test_export_tree_case_node_nonhint_not_merged(tree_named, protocol_fixture, node_fixture_factory, capsys):
    """
    Ensures that 2 children on the same protocol/mux are not accidentally merged into one
    Ensures that 2 children not on the same protocol/mux are not accidentally merged into one
    """
    # arrange
    protocol_ref, protocol_mux_1, protocol_mux_2, child_1_name, child_2_name, child_3_name = \
        ('FOO', 'barbaz', 'buzzqux', 'quxx', 'quz', 'clorge')
    protocol_fixture = replace(protocol_fixture, ref=protocol_ref)
    child_1 = replace(node_fixture_factory(), service_name=child_1_name)
    child_1.protocol = protocol_fixture
    child_1.protocol_mux = protocol_mux_1
    child_1.set_profile_timestamp()
    child_2 = replace(node_fixture_factory(), service_name=child_2_name)
    child_2.protocol = protocol_fixture
    child_2.protocol_mux = protocol_mux_1
    child_2.set_profile_timestamp()
    child_3 = replace(node_fixture_factory(), service_name=child_3_name)
    child_3.protocol = protocol_fixture
    child_3.protocol_mux = protocol_mux_2
    child_3.set_profile_timestamp()

    list(tree_named.values())[0].children = {'child1': child_1, 'child2': child_2, 'child3': child_3}
    list(tree_named.values())[0].set_profile_timestamp()

    # act
    await _helper_export_tree_with_timeout(tree_named)
    captured = capsys.readouterr()

    assert child_1_name in captured.out
    assert child_2_name in captured.out
    assert child_3_name in captured.out
