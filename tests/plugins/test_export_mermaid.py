from dataclasses import replace

import pytest

from astrolabe.plugins import export_mermaid
from astrolabe.plugins.export_mermaid import MERMAID_LR, MERMAID_TB, MERMAID_AUTO
from tests import _fake_database


@pytest.fixture(autouse=True)
def patch_database_autouse(patch_database):  # pylint:disable=unused-argument
    pass


@pytest.fixture(autouse=True)
def set_default_cli_args(cli_args_mock):
    cli_args_mock.debug = False
    cli_args_mock.export_mermaid_direction = MERMAID_AUTO


@pytest.mark.parametrize('direction', [MERMAID_LR, MERMAID_TB])
def test_export_tree_case_respect_cli_direction(cli_args_mock, direction, tree_stubbed):
    # arrange
    cli_args_mock.export_mermaid_direction = direction

    # act
    output = export_mermaid.export_tree(tree_stubbed)
    output_lines = output.splitlines()

    # assert
    assert f"graph {direction}" in output_lines


def test_export_tree_case_respect_cli_direction_auto(cli_args_mock, tree_stubbed):
    # arrange
    cli_args_mock.export_mermaid_direction = MERMAID_AUTO

    # act
    output = export_mermaid.export_tree(tree_stubbed)
    output_lines = output.splitlines()

    # assert
    assert f"graph {MERMAID_TB}" in output_lines


def test_export_tree_case_node_has_service_name(tree_named):
    """single node - not from hint, with service name, no children, no errs/warns"""
    # arrange
    node = tree_named[list(tree_named)[0]]
    node.set_profile_timestamp()
    node_id = f"{node.service_name}-{node.node_name}-{node.provider}"

    # act
    output_lines = export_mermaid.export_tree(tree_named).splitlines()

    # assert
    assert f"    {node_id}[{node_id}]" in output_lines


def test_export_tree_case_node_no_service_name(tree):
    """single node - not from hint, no service name, no children, no errs/warns"""
    # arrange
    node = tree[list(tree)[0]]
    node_id = f"UNKNOWN-{node.node_name}-{node.provider}"

    # act
    output_lines = export_mermaid.export_tree(tree).splitlines()

    # assert
    assert f"    {node_id}[{node_id}]" in output_lines


def test_export_tree_case_node_is_database(tree_named):
    """Database node exported as such"""
    # arrange
    node = list(tree_named.values())[0]
    node.protocol = replace(node.protocol, is_database=True)
    node_id = f"{node.service_name}-{node.node_name}-{node.provider}"

    # act
    output_lines = export_mermaid.export_tree(tree_named).splitlines()

    # assert
    assert f"    {node_id}[({node_id})]" in output_lines


def test_export_tree_case_node_is_containerized(tree_named):
    """Containerized node exported as such"""
    # arrange
    node = list(tree_named.values())[0]
    node.containerized = True
    node_id = f"{node.service_name}-{node.node_name}-{node.provider}"

    # act
    output_lines = export_mermaid.export_tree(tree_named).splitlines()

    # assert
    assert f"    {node_id}" + "{{" + node_id + "}}" in output_lines


def test_export_tree_case_node_warns(tree_named):
    """Node with warnings exported as such"""
    # arrange
    node = list(tree_named.values())[0]
    node.warnings = {'FOO': True}
    node_id = f"{node.service_name}-{node.node_name}-{node.provider}"

    # act
    output_lines = export_mermaid.export_tree(tree_named).splitlines()

    # assert
    assert f"    class {node_id} warning" in output_lines


def test_export_tree_case_node_errors(tree_named):
    """Node with errors exported as such"""
    # arrange
    node = list(tree_named.values())[0]
    node.errors = {'FOO': True}
    node_id = f"{node.service_name}-{node.node_name}-{node.provider}"

    # act
    output_lines = export_mermaid.export_tree(tree_named).splitlines()

    # assert
    assert f"    class {node_id} error" in output_lines


def test_export_tree_case_node_defunct(tree_named):
    """Node with errors exported as such"""
    # arrange
    node = list(tree_named.values())[0]
    node.warnings = {'DEFUNCT': True}
    node_id = f"{node.service_name}-{node.node_name}-{node.provider}"

    # act
    output_lines = export_mermaid.export_tree(tree_named).splitlines()

    # assert
    assert f"    class {node_id} defunct" in output_lines


def test_export_tree_case_node_name_cleaned(tree):
    """Test that the node name is cleaned during export"""
    # arrange
    node = list(tree.values())[0]
    node.service_name = '"foo:bar#baz"'
    cleaned_name = "foo_bar_baz"
    node_id = f"{cleaned_name}-{node.node_name}-{node.provider}"

    # act
    output_lines = export_mermaid.export_tree(tree).splitlines()

    # assert
    node_line = next((line for line in output_lines if cleaned_name in line), None)
    assert node_line is not None
    assert node_line.lstrip().startswith(f"{node_id}")


@pytest.mark.parametrize('blocking', (True, False))
def test_export_tree_case_edge_blocking_child(tree_stubbed_with_child, dummy_protocol_ref, blocking):
    """Validate blocking child shows regular nondashed, non-bold line when it is not blocking from top"""
    # arrange
    parent = list(tree_stubbed_with_child.values())[0]
    child = list(_fake_database.get_connections(parent).values())[0]
    child.protocol = replace(child.protocol, blocking=blocking)

    # act
    output_lines = export_mermaid.export_tree(tree_stubbed_with_child).splitlines()
    edge_line = next((line for line in output_lines if '>' in line), None)

    # assert
    assert edge_line is not None
    if blocking:
        assert f"--{dummy_protocol_ref}-->" in edge_line
    else:
        assert f"-.{dummy_protocol_ref}.->" in edge_line
