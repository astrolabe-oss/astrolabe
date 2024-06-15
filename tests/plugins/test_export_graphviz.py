import re
from typing import Union
import pytest
from dataclasses import replace

import astrolabe.plugins.export_graphviz
from astrolabe import constants
from astrolabe.plugins import export_graphviz


@pytest.fixture(autouse=True)
def set_default_rankdir(cli_args_mock):
    cli_args_mock.export_graphviz_rankdir = astrolabe.plugins.export_graphviz.GRAPHVIZ_RANKDIR_LEFT_TO_RIGHT


@pytest.mark.parametrize('rankdir', [astrolabe.plugins.export_graphviz.GRAPHVIZ_RANKDIR_LEFT_TO_RIGHT,
                                     astrolabe.plugins.export_graphviz.GRAPHVIZ_RANKDIR_TOP_TO_BOTTOM])
def test_export_tree_case_respect_cli_rankdir_options(cli_args_mock, rankdir, tree_named, capsys):
    # arrange
    cli_args_mock.export_graphviz_rankdir = rankdir

    # act
    export_graphviz.export_tree(tree_named, True)
    captured = capsys.readouterr()

    # assert
    assert f"graph [dpi=300 rankdir={rankdir}]" in captured.out


@pytest.mark.parametrize('skip_nonblocking_grandchildren,expected_rankdir',
                         [(False, astrolabe.plugins.export_graphviz.GRAPHVIZ_RANKDIR_TOP_TO_BOTTOM),
                          (True, astrolabe.plugins.export_graphviz.GRAPHVIZ_RANKDIR_LEFT_TO_RIGHT)])
def test_export_tree_case_respect_cli_rankdir_auto(skip_nonblocking_grandchildren, expected_rankdir, cli_args_mock,
                                                   tree_named, capsys):
    # arrange
    cli_args_mock.export_graphviz_rankdir = astrolabe.plugins.export_graphviz.GRAPHVIZ_RANKDIR_AUTO
    cli_args_mock.skip_nonblocking_grandchildren = skip_nonblocking_grandchildren

    # act
    export_graphviz.export_tree(tree_named, True)
    captured = capsys.readouterr()

    # assert
    assert f"graph [dpi=300 rankdir={expected_rankdir}]" in captured.out


@pytest.mark.parametrize('highlighted_service', ['child_service_name', 'parent_service_name'])
def test_export_tree_case_respect_cli_highlight_services(highlighted_service, tree, node_fixture_factory, cli_args_mock,
                                                         capsys):
    """Validate blocking child shows regular nondashed, non bold line when it is not blocking from top"""
    # arrange
    cli_args_mock.export_graphviz_highlight_services = [highlighted_service]
    child = replace(node_fixture_factory(), service_name='child_service_name')
    parent = list(tree.values())[0]
    parent.service_name = 'parent_service_name'
    parent.children = {'bar_service_ref': child}

    # act
    export_graphviz.export_tree(tree, True)
    captured = capsys.readouterr()
    print(captured)

    # assert
    assert f"color=\"yellow:black:yellow\"" in captured.out


@pytest.mark.parametrize('include_provider', [True, False])
def test_export_tree_case_node_has_service_name(tree_named, capsys, cli_args_mock, include_provider):
    """single node - not from hint, with service name, no children, no errs/warns"""
    # arrange/act
    cli_args_mock.export_graphviz_node_include_provider = include_provider
    export_graphviz.export_tree(tree_named, True)
    n = tree_named[list(tree_named)[0]]
    captured = capsys.readouterr()
    node_line = _grep_head_1(n.service_name, captured.out)

    # assert
    if include_provider:
        assert f"\t\"{n.service_name} ({n.provider})\" [style=bold]" == node_line
    else:
        assert f"\t{n.service_name} [style=bold]" == node_line


@pytest.mark.parametrize('include_provider', [True, False])
def test_export_tree_case_node_no_service_name(tree, capsys, cli_args_mock, include_provider):
    """single node - not from hint, no service name, no children, no errs/warns"""
    # arrange/act
    cli_args_mock.export_graphviz_node_include_provider = include_provider
    export_graphviz.export_tree(tree, True)
    n_ref = list(tree)[0]
    n = tree[n_ref]
    captured = capsys.readouterr()

    # assert
    if include_provider:
        assert f"UNKNOWN\n({n_ref}) ({n.provider})\" [style=bold]" in captured.out
    else:
        assert f"UNKNOWN\n({n_ref})\" [style=bold]" in captured.out


def test_export_tree_case_node_is_database(tree_named, capsys):
    """Database node exported as such"""
    # arrange
    tn = tree_named
    n = list(tn.values())[0]
    n.protocol = replace(n.protocol, is_database=True)

    # act
    export_graphviz.export_tree(tn, True)
    captured = capsys.readouterr()

    # assert
    assert _grep_head_1(rf"\t\"?{n.service_name}", captured.out)


def test_export_tree_case_node_is_containerized(tree_named, capsys):
    """Containerized node exported as such"""
    # arrange
    tn = tree_named
    n = list(tn.values())[0]
    n.containerized = True

    # act
    export_graphviz.export_tree(tn, True)
    captured = capsys.readouterr()
    node_line = _grep_head_1(rf"\t\"?{n.service_name}", captured.out)

    # assert
    assert node_line
    assert "[shape=septagon style=bold]" in node_line


def test_export_tree_case_node_errors(tree_named, capsys):
    """Node with errors exported as such"""
    # arrange
    tn = tree_named
    n = list(tn.values())[0]
    n.errors = {'FOO': True}

    # act
    export_graphviz.export_tree(tn, True)
    captured = capsys.readouterr()
    node_line = _grep_head_1(n.service_name, captured.out)

    # assert
    assert node_line
    assert "[color=red style=bold]" in node_line


def test_export_tree_case_node_warnings(tree_named, capsys):
    """Node with warnings exported as such"""
    # arrange
    tn = tree_named
    n = list(tn.values())[0]
    n.warnings = {'FOO': True}

    # act
    export_graphviz.export_tree(tn, True)
    captured = capsys.readouterr()
    node_line = _grep_head_1(n.service_name, captured.out)

    # assert
    assert node_line
    assert "[color=darkorange style=bold]" in node_line


def test_export_tree_case_node_name_cleaned(tree, capsys):
    """Test that the node name is cleaned during export"""
    # arrange
    n = list(tree.values())[0]
    n.service_name = '"foo:bar#baz"'

    # act
    export_graphviz.export_tree(tree, True)
    captured = capsys.readouterr()
    node_line = _grep_head_1("foo_bar_baz", captured.out)

    # assert
    assert node_line
    assert node_line.lstrip("\t\"").startswith("foo_bar_baz")


def test_export_tree_case_edge_blocking_child(tree, node_fixture_factory, dummy_protocol_ref, capsys):
    """Validate blocking child shows regular nondashed, non bold line when it is not blocking from top"""
    # arrange
    parent = list(tree.values())[0]
    child = replace(node_fixture_factory(), service_name='intermediary_child')
    child.protocol = replace(child.protocol, blocking=False)
    parent.children = {'intermediary_child': child}
    final_child = replace(node_fixture_factory(), service_name='final_child')
    final_child.protocol = replace(child.protocol, blocking=True)
    child.children = {'final_child': final_child}

    # act
    export_graphviz.export_tree(tree, True)
    captured = capsys.readouterr()
    edge_line = _grep_head_1(rf"{child.service_name}.*->.*{final_child.service_name}", captured.out)

    # assert
    assert f"[label={dummy_protocol_ref}" in edge_line
    assert "color=\"\" style=\"\"]" in edge_line


def test_export_tree_case_edge_blocking_from_top_child(tree, node_fixture, capsys):
    """Validate attributes for a blocking from top child/edge in the graph"""
    # arrange
    parent = list(tree.values())[0]
    parent.service_name = 'foo'
    child = replace(node_fixture, service_name='bar')
    child.protocol = replace(child.protocol, ref='BAZ')
    parent.children = {'buzz': child}

    # act
    export_graphviz.export_tree(tree, True)
    captured = capsys.readouterr()
    edge_line = _grep_head_1(rf"{parent.service_name}.*->.*{child.service_name}", captured.out)

    # assert
    assert _grep_head_1(rf"{parent.service_name}(?!.*->)", captured.out)
    assert _grep_head_1(rf"(?<!-> \"){child.service_name}", captured.out)  # w/ protocol
    assert _grep_head_1(rf"(?<!-> ){child.service_name}", captured.out)  # w/out protocol
    assert "style=bold]" in edge_line


def test_export_tree_case_edge_blocking_from_top_once_child(tree_named, node_fixture_factory, dummy_protocol_ref, capsys):
    """
    Case where a child is blocking, but it shows up twice in the graph and is only annotated as blocking
    from top in the 1 scenario where it is - and regular blocking (but not from top) in the other
    """
    # arrange
    tn = tree_named
    parent, blocking_service_name, nonblocking_service_name = (list(tn.values())[0], 'foo', 'bar')
    blocking_child = replace(node_fixture_factory(), service_name=blocking_service_name)
    blocking_child.protocol = replace(blocking_child.protocol, blocking=True)
    nonblocking_child = replace(node_fixture_factory(), service_name=nonblocking_service_name)
    nonblocking_child.protocol = replace(blocking_child.protocol, blocking=False)
    parent.children = {'blocking_child': blocking_child, 'nonblocking_child': nonblocking_child}
    nonblocking_child.children = {'blocking_child': blocking_child}

    # act
    export_graphviz.export_tree(tn, True)
    captured = capsys.readouterr()

    # assert
    assert _grep_head_1(rf"{parent.service_name}.*->.*{blocking_service_name}.*style=bold", captured.out)
    assert _grep_head_1(rf"{nonblocking_service_name}.*->.*{blocking_service_name}.*style=\"\"", captured.out)


def test_export_tree_case_edge_child_nonblocking(tree_named, node_fixture, capsys):
    """Nonblocking chihld shown as dashed edge"""
    # arrange
    child_node, child_protocol_ref = (replace(node_fixture, service_name='dummy_child'), 'DUM')
    child_node.protocol = replace(child_node.protocol, ref=child_protocol_ref, blocking=False)
    tn = tree_named
    n = list(tn.values())[0]
    n.children = {'child_service_ref': child_node}

    # act
    export_graphviz.export_tree(tn, True)
    captured = capsys.readouterr()

    # assert
    assert _grep_head_1(rf"{n.service_name}.*->.*{child_node.service_name}.*style=\",dashed", captured.out)


def test_export_tree_case_edge_child_defunct_hidden(tree, node_fixture, cli_args_mock, capsys):
    """Defunct child hidden per ARGS"""
    # arrange
    cli_args_mock.hide_defunct = True
    child_node = replace(node_fixture, service_name='child_service', warnings={'DEFUNCT': True})
    list(tree.values())[0].children = {'child_service_ref': child_node}

    # act
    export_graphviz.export_tree(tree, True)
    captured = capsys.readouterr()

    # assert
    assert child_node.service_name not in captured.out
    assert f" -> {child_node.service_name}" not in captured.out


def test_export_tree_case_edge_child_defunct_shown(tree_named, node_fixture, cli_args_mock, capsys):
    """Defunct child shown correctly - also validates `warnings` are shown correctly"""
    # arrange
    cli_args_mock.hide_defunct = False
    child_node = replace(node_fixture, service_name='child_service', warnings={'DEFUNCT': True})
    tn = tree_named
    n = list(tn.values())[0]
    n.children = {'child_service_ref': child_node}

    # act
    export_graphviz.export_tree(tn, True)
    captured = capsys.readouterr()
    edge_line = _grep_head_1(rf"{n.service_name}.*->.*{child_node.service_name}", captured.out)

    # assert
    assert edge_line
    assert f"[label=\"{child_node.protocol.ref} (DEFUNCT)" in edge_line
    assert "color=darkorange" in edge_line
    assert "penwidth=3" in edge_line
    assert "style=\"bold,dotted,filled" in edge_line


def test_export_tree_case_edge_child_errors(tree_named, node_fixture, capsys):
    """Child with errors shown correctly"""
    # arrange
    child_node = replace(node_fixture, service_name='child_service', errors={'FOO': True})
    tn = tree_named
    n = list(tn.values())[0]
    n.children = {'child_service_ref': child_node}

    # act
    export_graphviz.export_tree(tn, True)
    captured = capsys.readouterr()
    node_line = _grep_head_1(rf"\t\"?{child_node.service_name}", captured.out)
    edge_line = _grep_head_1(rf"{n.service_name}.*->.*{child_node.service_name}", captured.out)

    # assert
    assert node_line
    assert "color=red" in node_line
    assert "style=bold" in node_line
    assert edge_line
    assert "color=red" in edge_line
    assert "style=bold" in edge_line


def test_export_tree_case_edge_child_hint(tree_named, node_fixture, capsys):
    """Child from_hint shown correctly"""
    # arrange
    child_node = replace(node_fixture, service_name='child_service', from_hint=True)
    tn = tree_named
    n = list(tn.values())[0]
    n.children = {'child_service_ref': child_node}

    # act
    export_graphviz.export_tree(tn, True)
    captured = capsys.readouterr()
    edge_line = _grep_head_1(rf"{n.service_name}.*->.*{child_node.service_name}", captured.out)

    # assert
    assert _grep_head_1(rf"\t\"?{child_node.service_name}", captured.out)
    assert edge_line
    assert f"[label=\"{child_node.protocol.ref} (HINT)" in edge_line
    assert "color=\":blue\"" in edge_line
    assert "penwidth=3" in edge_line
    assert "style=bold" in edge_line


@pytest.mark.parametrize('containerized,shape_string', [(False, ''), (True, 'shape=septagon ')])
def test_export_tree_case_node_hint_merged(containerized, shape_string, tree_named, protocol_fixture,
                                           node_fixture_factory, capsys):
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
    child_node_hint.containerized = containerized
    tn = tree_named
    n = list(tn.values())[0]
    n.children = {'discovered': child_node_discovered, 'hinted': child_node_hint}

    # act
    export_graphviz.export_tree(tn, True)
    captured = capsys.readouterr()
    child_node_line = _grep_head_1(f"\t\"?{child_node_hint.service_name}", captured.out)
    edge_line = _grep_head_1(rf"{n.service_name}.*->.*{child_node_hint.service_name}", captured.out)

    # assert
    assert 'UNKNOWN' not in captured.out
    assert child_node_line
    assert "color=red" in child_node_line
    assert shape_string in child_node_line
    assert "style=bold" in child_node_line
    assert edge_line
    assert f"({error},HINT)\"" in edge_line
    assert "color=\"red:blue\"" in edge_line
    assert "penwidth=3" in edge_line
    assert "style=bold" in edge_line


def test_export_tree_case_node_nonhint_not_merged(tree_named, protocol_fixture, node_fixture_factory, capsys):
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
    child_2 = replace(node_fixture_factory(), service_name=child_2_name)
    child_2.protocol = protocol_fixture
    child_2.protocol_mux = protocol_mux_1
    child_3 = replace(node_fixture_factory(), service_name=child_3_name)
    child_3.protocol = protocol_fixture
    child_3.protocol_mux = protocol_mux_2

    list(tree_named.values())[0].children = {'child1': child_1, 'child2': child_2, 'child3': child_3}

    # act
    export_graphviz.export_tree(tree_named, True)
    captured = capsys.readouterr()

    # assert
    assert _grep_head_1(f"\t\"?{child_1_name}", captured.out)
    assert _grep_head_1(f"\t\"?{child_2_name}", captured.out)
    assert _grep_head_1(f"\t\"?{child_3_name}", captured.out)


def _grep_head_1(pattern: str, lines: str) -> Union[str, bool]:
    """it's like bash `echo $lines | grep $pattern | head -n 1` but in python"""
    return next((line for line in lines.split("\n") if re.search(pattern, line)), None) or False
