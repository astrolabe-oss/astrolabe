import os
import pytest

from astrolabe import network


def _write_stub_web_yaml(astrolabe_d: str, contents: str) -> None:
    """Helper method to write contents to the stub web.yaml file"""
    file = os.path.join(astrolabe_d, 'network.yaml')
    with open(file, 'w', encoding='utf8') as open_file:
        open_file.write(contents)


def test_init_case_success(astrolabe_d, core_astrolabe_d):
    """Network files are initialized from both astrolabe.d directories"""
    # arrange
    fake_protocol_web_yaml = """
---
protocols:
  FOO:
    name: "FOO"
    blocking: true
"""
    _write_stub_web_yaml(astrolabe_d, fake_protocol_web_yaml)
    fake_protocol_web_yaml = """
---
protocols:
  BAR:
    name: "BAR"
    blocking: true
"""
    _write_stub_web_yaml(core_astrolabe_d, fake_protocol_web_yaml)

    # act
    network.init()

    assert network.get_protocol("FOO")
    assert network.get_protocol("BAR")


def test_init_case_malformed_web_yaml(astrolabe_d):
    """Malformed yaml is caught in initializing network"""
    # arrange
    fake_protocol_web_yaml = """
 ---
 :!!#$T%!##
 protocols:
"""
    _write_stub_web_yaml(astrolabe_d, fake_protocol_web_yaml)

    # act
    with pytest.raises(network.WebYamlException) as e_info:
        network.init()

    # assert
    assert 'Unable to load' in str(e_info)


def test_init_case_malformed_protocol(astrolabe_d):
    """Well-formed yaml, malformed protocol schema is caught"""
    # arrange
    fake_protocol_web_yaml = """
---
protocols:
  FOO:
    nomnom: "bar"
"""
    _write_stub_web_yaml(astrolabe_d, fake_protocol_web_yaml)

    # act
    with pytest.raises(network.WebYamlException) as e_info:
        network.init()

    # assert
    assert 'protocols malformed' in str(e_info)


def test_init_case_default_tcp_protocol(astrolabe_d):
    """No user defined protocols still result in TCP protocol defined"""
    # arrange
    fake_protocol_web_yaml = """
---
foo: bar
"""
    _write_stub_web_yaml(astrolabe_d, fake_protocol_web_yaml)

    # act
    network.init()

    # assert
    assert network.get_protocol("TCP")


@pytest.mark.parametrize('protocol_ref,blocking,is_database', [('FOO', True, True), ('BAR', True, False),
                                                               ('BAZ', False, False)])
def test_get_protocol(astrolabe_d, protocol_ref, blocking, is_database):
    """We are able get a parsed protocol from profile_strategy which was loaded from disk"""
    # Technically an integration test that tests the interaction of init() and get_protocol()
    # arrange
    fake_protocol_web_yaml = f"""
---
protocols:
  {protocol_ref}:
    name: "{protocol_ref.capitalize()}"
    blocking: {str(blocking).lower()}
    is_database: {str(is_database).lower()}
"""
    _write_stub_web_yaml(astrolabe_d, fake_protocol_web_yaml)

    # act
    network.init()
    protocol = network.get_protocol(protocol_ref)

    # assert
    assert protocol_ref == protocol.ref
    assert blocking == protocol.blocking
    assert is_database == protocol.is_database


@pytest.mark.parametrize('test, should_skip', [
    ('1.2.3.4', True),
    ('mypod-xyz', True),
    ('1.2.3', False),
    ('2.3.4', False),
    ('2.3', False),
    ('mypod-xy', False),
    ('xyz', False),
    ('-', False),
    ('pod', False)
])
def test_skip_address(astrolabe_d, mocker, test, should_skip):
    """We are able to correctly match a address skip loaded from disk"""
    # Technically an integration test that tests the interaction of init() and skip_service_name()
    # arrange
    mocker.patch('astrolabe.network._validate', return_value=None)
    hint_web_yaml = """
skips:
  addresses:
    - "1.2.3.4"
    - "mypod-xyz"
"""
    _write_stub_web_yaml(astrolabe_d, hint_web_yaml)

    # act
    network.init()

    # assert
    assert network.skip_address(test) == should_skip


def test_skip_address_ignored_cidr():
    assert network.skip_address("169.254.169.254")
    assert not network.skip_address("169.254.169.1")


@pytest.mark.parametrize("test, should_skip", [
    ('bar', True),
    ('barf', True),
    ('foo', True),
    ('foo-service', True),
    ('food-service', True),
    ('a-fool-service', True),
    ('oof-service', False),
    ('fo', False),
    ('cats', False)
])
def test_skip_service_name(astrolabe_d, mocker, test, should_skip):
    """We are able to correctly match a service_name skip loaded from disk"""
    # Technically an integration test that tests the interaction of init() and skip_service_name()
    # arrange
    mocker.patch('astrolabe.network._validate', return_value=None)
    hint_web_yaml = """
skips:
  service_names:
    - "foo"
    - "bar"
"""
    _write_stub_web_yaml(astrolabe_d, hint_web_yaml)

    # act
    network.init()

    # assert
    assert network.skip_service_name(test) == should_skip


@pytest.mark.parametrize("test, should_skip", [
    ('bar', True),
    ('barf', True),
    ('foo', True),
    ('foo-service', True),
    ('food-service', True),
    ('a-fool-service', True),
    ('oof-service', False),
    ('fo', False),
    ('cats', False)
])
def test_skip_protocol_mux(astrolabe_d, mocker, test, should_skip):
    """We are able to correctly match a protocol_mux skip loaded from disk"""
    # Technically an integration test that tests the interaction of init() and skip_protocol_mux()
    # arrange
    mocker.patch('astrolabe.network._validate', return_value=None)
    hint_web_yaml = """
skips:
  service_names:
    - "foo"
    - "bar"
"""
    _write_stub_web_yaml(astrolabe_d, hint_web_yaml)

    # act
    network.init()

    # assert
    assert network.skip_service_name(test) == should_skip


def test_skip_protocol_mux_cli_arg(cli_args_mock):
    skip_this_protocol_mux = 'foo_mux'
    cli_args_mock.skip_protocol_muxes = [skip_this_protocol_mux]

    assert network.skip_protocol_mux(skip_this_protocol_mux)


def test_hints(astrolabe_d, mocker):
    """We are able to correctly get hints that were parsed from disk"""
    # Technically an integration test that tests the interaction of init() and hints()
    # arrange
    upstream, downstream, protocol, protocol_dummy, mux, provider, instance_provider = \
        ('foo-service', 'bar-service', 'BAZ', 'baz-dummy', 'buz', 'qux', 'quux')
    mocker.patch('astrolabe.network._validate', return_value=None)
    get_protocl_func = mocker.patch('astrolabe.network.get_protocol', return_value=protocol_dummy)
    hint_web_yaml = f"""
hints:
  {upstream}:
    - service_name: "{downstream}"
      protocol: "{protocol}"
      protocol_mux: "{mux}"
      provider: "{provider}"
      instance_provider: "{instance_provider}"
"""
    _write_stub_web_yaml(astrolabe_d, hint_web_yaml)

    # act
    network.init()
    hints = network.hints(upstream)

    # assert
    assert len(hints) == 1
    hint = hints[0]
    assert hint.service_name == downstream
    assert hint.protocol == protocol_dummy
    get_protocl_func.assert_called_once_with(protocol)
    assert hint.protocol_mux == mux
    assert hint.instance_provider == instance_provider
