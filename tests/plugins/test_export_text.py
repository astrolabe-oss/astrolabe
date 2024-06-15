from astrolabe.plugins import export_text


def test_export_tree(tree_stubbed_with_child, capsys):
    # arrange/act
    export_text.export_tree(tree_stubbed_with_child)
    captured = capsys.readouterr()
    parent = list(tree_stubbed_with_child.values())[0]
    child = list(parent.children.values())[0]

    # assert
    assert f"{parent.service_name} --[{child.protocol.ref}]--> {child.service_name} ({parent.protocol_mux})" \
           in captured.out
