from astrolabe.plugins import export_text

from tests import _fake_database


def test_export_tree(tree_stubbed_with_child, capsys, patch_database):  # pylint:disable=unused-argument
    # arrange/act
    export_text.export_tree(tree_stubbed_with_child)
    captured = capsys.readouterr()
    parent = list(tree_stubbed_with_child.values())[0]
    child = list(_fake_database.get_connections(parent).values())[0]

    # assert
    assert (f"{parent.service_name} ({parent.node_name})"
            f" --[{child.protocol.ref}:{child.protocol_mux}]--> "
            f"{child.service_name} ({child.node_name})") \
           in captured.out
