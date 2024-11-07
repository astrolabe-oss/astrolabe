from astrolabe.plugins import export_text

from tests import _fake_database


def test_export_tree(tree_stubbed_with_child, capsys, patch_database):  # pylint:disable=unused-argument
    # arrange/act
    export_text.export_tree(tree_stubbed_with_child)
    captured = capsys.readouterr()
    parent = list(tree_stubbed_with_child.values())[0]
    child = list(_fake_database.get_connections(parent).values())[0]

    # assert
    assert f"{parent.service_name} --[{child.protocol.ref}]--> {child.service_name} ({parent.protocol_mux})" \
           in captured.out
