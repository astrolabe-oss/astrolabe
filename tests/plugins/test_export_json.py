import json
import os
import pytest
from dataclasses import replace
from types import SimpleNamespace

from astrolabe import profile_strategy
from astrolabe import network
from astrolabe import constants
from astrolabe import node
from astrolabe.plugins import export_json


@pytest.fixture
def cli_args_fixture():
    # we are not using mocker to patch globals.ARGS because json.dump can't serialize a mock
    constants.ARGS = SimpleNamespace()
    constants.ARGS.max_depth = 100
    return constants.ARGS


@pytest.fixture
def tmp_json_dumpfile(tmp_path):
    return os.path.join(tmp_path, 'stub.json')


def test_load_case_args_primitives(tmp_path, mocker):
    """Test load for basic required pass through ARGS and primitive types"""
    mocker.patch('astrolabe.constants.ARGS', max_depth=100)
    max_depth = 42
    stub_tree = {"foo": ["bar"]}
    tmp_file = os.path.join(tmp_path, 'stub-load.json')
    stub_json = '''
{
  "args": {
    "max_depth": "%s",
    "skip_nonblocking_grandchildren": true
  },
  "tree": %s
}
''' % (max_depth, json.dumps(stub_tree))
    with open(tmp_file, 'w') as f:
        f.write(stub_json)

    # act
    tree = export_json.load(tmp_file)

    # assert
    assert stub_tree == tree
    assert constants.ARGS.max_depth == max_depth
    assert constants.ARGS.skip_nonblocking_grandchildren


def test_load_case_objects(cli_args_fixture, tmp_path):
    """Custom objects can be loaded from a json file. Apologies for the ungodly size of this unit test"""
    # cli_args_fixture fixture is called but not used simply in order to mock it in export_json.dump()
    tmp_file = os.path.join(tmp_path, 'stub-load.json')
    # - protocol
    proto_ref, proto_name, proto_blocking, proto_is_database = ('foo', 'bar', True, False)
    # - profile strategy
    ps_description, ps_name, ps_providers, ps_provider_args, ps_child_provider, ps_filter, ps_rewrites = \
        ('foo', 'bar', ['baz'], {'buzz': 'buzzbuzz'}, {'qux': True}, {'quux': True}, {'quz': True})
    # - node
    node_ref, node_prov, node_mux, node_hint, node_address, node_service_name, node_children, node_warn, node_err = \
        ('a_ref', 'a_prov', 'a_mux', True, 'an_add', 'a_name', {'foo': 'child'}, {'bar': True}, {'baz': True})
    stub_json = f"""
{{
  "args": {{
    "max_depth": 0,
    "skip_nonblocking_grandchildren": false
  }},
  "tree": {{
    "{node_ref}": {{
      "__type__": "Node",
      "provider": "{node_prov}",
      "protocol_mux": "{node_mux}",
      "from_hint": {str(node_hint).lower()},
      "address": "{node_address}",
      "service_name": "{node_service_name}",
      "children": {json.dumps(node_children)},
      "warnings": {json.dumps(node_warn)},
      "errors": {json.dumps(node_err)},
      "profile_strategy": {{
        "__type__": "ProfileStrategy",
        "description": "{ps_description}",
        "name": "{ps_name}",
        "providers": {json.dumps(ps_providers)},
        "provider_args": {json.dumps(ps_provider_args)},
        "child_provider": {json.dumps(ps_child_provider)},
        "service_name_filter": {json.dumps(ps_filter)},
        "service_name_rewrites": {json.dumps(ps_rewrites)},
        "protocol": {{
          "__type__": "Protocol",
          "ref": "{proto_ref}",
          "name": "{proto_name}",
          "blocking": {str(proto_blocking).lower()},
          "is_database": {str(proto_is_database).lower()}
        }}
      }},
      "protocol": {{
        "__type__": "Protocol",
        "ref": "{proto_ref}",
        "name": "{proto_name}",
        "blocking": {str(proto_blocking).lower()},
        "is_database": {str(proto_is_database).lower()}
      }}
    }}
  }}
}}
"""
    with open(tmp_file, 'w') as f:
        f.write(stub_json)

    # act
    tree = export_json.load(tmp_file)

    # assert
    # - Node()
    assert isinstance(tree[node_ref], node.Node)
    loaded_node = tree[node_ref]
    assert loaded_node.provider == node_prov
    assert loaded_node.protocol_mux == node_mux
    assert loaded_node.from_hint == node_hint
    assert loaded_node.address == node_address
    assert loaded_node.service_name == node_service_name
    assert loaded_node.children == node_children
    assert loaded_node.warnings == node_warn
    assert loaded_node.errors == node_err
    # - ProfileStrategy()
    assert isinstance(loaded_node.profile_strategy, profile_strategy.ProfileStrategy)
    loaded_cs = loaded_node.profile_strategy
    assert loaded_cs.description == ps_description
    assert loaded_cs.name == ps_name
    assert loaded_cs.providers == ps_providers
    assert loaded_cs.provider_args == ps_provider_args
    assert loaded_cs.child_provider == ps_child_provider
    assert loaded_cs.service_name_filter == ps_filter
    assert loaded_cs.service_name_rewrites == ps_rewrites
    # - Protocol
    assert isinstance(loaded_cs.protocol, network.Protocol)
    loaded_protocol = loaded_cs.protocol
    assert loaded_protocol.ref == proto_ref
    assert loaded_protocol.name == proto_name
    assert loaded_protocol.blocking == proto_blocking
    assert loaded_protocol.is_database == proto_is_database
    assert isinstance(loaded_node.protocol, network.Protocol)


def test_dump_case_args(tmp_path):
    """ARGS are dumped to disk along with the tree"""
    # arrange
    # we are not using mocker to patch globals.ARGS because json.dump can't serialize a mock
    constants.ARGS = SimpleNamespace()
    constants.ARGS.foo = 'bar'
    tree = {'baz': 'buz'}
    tmp_file = os.path.join(tmp_path, 'stub-dump.json')

    # act
    export_json.dump(tree, tmp_file)
    loaded = json.load(open(tmp_file))

    # assert
    assert loaded.get('args') == vars(constants.ARGS)
    assert loaded.get('tree') == tree


def test_dump_case_primitives(tmp_path, cli_args_fixture):
    """Primitive data types are dumped to disk"""
    # arrange
    tree = {
        'foo': 'bar',
        'baz': ['buzz'],
        'qux': {'quux': 'quuz'}
    }
    tmp_file = os.path.join(tmp_path, 'stub-dump.json')

    # act
    export_json.dump(tree, tmp_file)
    loaded = json.load(open(tmp_file))

    # assert
    assert loaded.get('tree') == tree


def test_dump_case_objects(cli_args_fixture, tmp_json_dumpfile, node_fixture, profile_strategy_fixture, protocol_fixture):
    """Custom objects are json dumped to disk. Apologies for the large size of this unit test"""
    # cli_args_fixture fixture is called but not used simply in order to mock it in export_json.dump()
    # arrange
    # - protocol
    proto_ref, proto_name, proto_blocking, proto_is_database = ('foo', 'bar', True, False)
    protocol = replace(protocol_fixture, ref=proto_ref, name=proto_name, blocking=proto_blocking,
                       is_database=proto_is_database)
    # - profile strategy
    ps_description, ps_name, ps_providers, ps_provider_args, ps_child_provider, ps_filter, ps_rewrites = \
        ('foo', 'bar', ['baz'], {'buzz': 'buzzbuzz'}, {'qux': True}, {'quux': True}, {'quz': True})
    cs = replace(profile_strategy_fixture, description=ps_description, name=ps_name, protocol=protocol,
                 providers=ps_providers, provider_args=ps_provider_args, child_provider=ps_child_provider,
                 service_name_filter=ps_filter, service_name_rewrites=ps_rewrites)
    # - node
    node_ref, provider, mux, from_hint, address, service_name, children, warnings, errors = \
        ('fake_ref', 'provider', 'bar_mux', True, 'baz_add', 'buz_name', {'qux': 'child'},
         {'quux_warn': True}, {'quuz_err': True})
    node_fixture.profile_strategy = cs
    node_fixture.provider = provider
    node_fixture.protocol = protocol
    node_fixture.protocol_mux = mux
    node_fixture.from_hint = from_hint
    node_fixture.address = address
    node_fixture.service_name = service_name
    node_fixture.children = children
    node_fixture.warnings = warnings
    node_fixture.errors = errors
    tree = {node_ref: node_fixture}

    # act
    export_json.dump(tree, tmp_json_dumpfile)
    loaded = json.load(open(tmp_json_dumpfile))
    loaded_tree = loaded.get('tree')
    node_dict = loaded_tree.get(node_ref)

    # assert
    # - node
    assert node_dict is not None
    assert provider == node_dict['provider']
    assert mux == node_dict['protocol_mux']
    assert from_hint == node_dict['from_hint']
    assert address == node_dict['address']
    assert service_name == node_dict['service_name']
    assert children == node_dict['children']
    assert warnings == node_dict['warnings']
    assert errors == node_dict['errors']
    # - protocol
    assert node_dict.get('protocol')
    assert node_dict['protocol']['ref'] == proto_ref
    assert node_dict['protocol']['name'] == proto_name
    assert node_dict['protocol']['blocking'] == proto_blocking
    assert node_dict['protocol']['is_database'] == proto_is_database
    # - profile strategy
    assert node_dict.get('profile_strategy')
    assert node_dict['profile_strategy']['description'] == ps_description
    assert node_dict['profile_strategy']['name'] == ps_name
    assert node_dict['profile_strategy']['protocol']['ref'] == protocol.ref
    assert node_dict['profile_strategy']['providers'] == ps_providers
    assert node_dict['profile_strategy']['provider_args'] == ps_provider_args
    assert node_dict['profile_strategy']['child_provider'] == ps_child_provider
    assert node_dict['profile_strategy']['service_name_filter'] == ps_filter
    assert node_dict['profile_strategy']['service_name_rewrites'] == ps_rewrites
