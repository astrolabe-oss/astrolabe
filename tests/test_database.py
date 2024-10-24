import copy
import datetime
import pytest

from astrolabe.node import Node, NodeType
from astrolabe import database
from corelib import platdb

@pytest.fixture
def mock_compute_node(profile_strategy_fixture, protocol_fixture):
    return Node(
        address='1.2.3.4',
        containerized=False,
        node_type=NodeType.COMPUTE,
        profile_strategy=profile_strategy_fixture,
        protocol=protocol_fixture,
        protocol_mux='mock_mux',
        provider='mock_provider',
        service_name='mock_compute',
        _profile_lock_time=datetime.datetime.now(datetime.timezone.utc),
        _profile_timestamp=datetime.datetime.now(datetime.timezone.utc)
    )

@pytest.fixture
def mock_compute_node_without_type(profile_strategy_fixture, protocol_fixture):
    """This is the same as the mock_compute_node fixture except that this
    fixture does not assign anything to the node_type attribute so it will
    be None. 

    A new node object had to be created because Node does not support item
    edits.
    """
    return Node(
        address='1.2.3.4',
        containerized=False,
        profile_strategy=profile_strategy_fixture,
        protocol=protocol_fixture,
        protocol_mux='mock_mux',
        provider='mock_provider',
        service_name='mock_compute',
        _profile_lock_time=datetime.datetime.now(datetime.timezone.utc),
        _profile_timestamp=datetime.datetime.now(datetime.timezone.utc)
    )

@pytest.fixture
def mock_deployment_node(profile_strategy_fixture, protocol_fixture):
    return Node(
        address='1.2.3.4',
        node_type=NodeType.DEPLOYMENT,
        profile_strategy=profile_strategy_fixture,
        protocol=protocol_fixture,
        protocol_mux='mock_mux',
        provider='mock_provider',
        service_name='mock_compute',
        _profile_lock_time=datetime.datetime.now(datetime.timezone.utc),
        _profile_timestamp=datetime.datetime.now(datetime.timezone.utc)
    )

@pytest.mark.parametrize('node_fixture,node_type', [
    ('mock_compute_node', platdb.Compute),
    ('mock_compute_node_without_type', platdb.Compute),
    ('mock_deployment_node', platdb.Deployment)
])
def test_node_to_neomodel(request, node_fixture, node_type):
    node = request.getfixturevalue(node_fixture)

    obj = database._node_to_neomodel(node)

    assert isinstance(obj, node_type)

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

    print(node)


def test_new_get_node_by_address():
    node = database._new_get_node_by_address("52.4.186.106")

    print(node)

def test_new_get_nodes_pending_dnslookup():
    results = database.get_nodes_pending_dnslookup()

def test_node_is_k8s_load_balancer():
    results = database._new_node_is_k8s_load_balancer("50.19.90.170")

def test_new_get_nodes_unprofiled():
    results = database.get_nodes_unprofiled()

    print(results)

    