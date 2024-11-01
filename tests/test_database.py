import datetime
import pytest

from corelib import platdb

from astrolabe.node import Node, NodeType
from astrolabe import database


@pytest.fixture
def mock_compute_node(protocol_fixture):
    return Node(
        address='1.2.3.4',
        containerized=False,
        node_type=NodeType.COMPUTE,
        profile_strategy_name='Seed',
        protocol=protocol_fixture,
        protocol_mux='mock_mux',
        provider='mock_provider',
        service_name='mock_compute',
        _profile_lock_time=datetime.datetime.now(datetime.timezone.utc),
        _profile_timestamp=datetime.datetime.now(datetime.timezone.utc)
    )


@pytest.fixture
def mock_compute_node_without_type(protocol_fixture):
    """This is the same as the mock_compute_node fixture except that this
    fixture does not assign anything to the node_type attribute so it will
    be None. 

    A new node object had to be created because Node does not support item
    edits.
    """
    return Node(
        address='1.2.3.4',
        containerized=False,
        profile_strategy_name='Seed',
        protocol=protocol_fixture,
        protocol_mux='mock_mux',
        provider='mock_provider',
        service_name='mock_compute',
        _profile_lock_time=datetime.datetime.now(datetime.timezone.utc),
        _profile_timestamp=datetime.datetime.now(datetime.timezone.utc)
    )


@pytest.fixture
def mock_deployment_node(protocol_fixture):
    return Node(
        address='1.2.3.4',
        node_type=NodeType.DEPLOYMENT,
        profile_strategy_name='Seed',
        protocol=protocol_fixture,
        protocol_mux='mock_mux',
        provider='mock_provider',
        service_name='mock_compute',
        _profile_lock_time=datetime.datetime.now(datetime.timezone.utc),
        _profile_timestamp=datetime.datetime.now(datetime.timezone.utc)
    )


@pytest.mark.parametrize('node_fixture,node_type', [
    ('mock_compute_node', NodeType.COMPUTE),
    ('mock_compute_node_without_type', NodeType.COMPUTE),
    ('mock_deployment_node', NodeType.DEPLOYMENT)
])
def test_node_to_neomodel(request, node_fixture, node_type):
    node = request.getfixturevalue(node_fixture)

    obj = database.save_node(node)

    assert obj.node_type == node_type


def test_neomodel_to_node():
    attrs = {
        "name": "new_compute1",
        "platform": "k8s",
        "address": "pod-1234nv",
        "protocol": "HTTP",
        "protocol_multiplexor": "80"
    }

    mock_compute = platdb.Compute(**attrs)

    node = database.neomodel_to_node(mock_compute)

    assert node
    assert isinstance(node, Node)
