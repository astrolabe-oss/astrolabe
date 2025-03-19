# pylint: disable=unused-argument,too-many-arguments,too-many-positional-arguments

import datetime

import neomodel
import pytest


from astrolabe.node import Node, NodeType
from astrolabe import database, platdb


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


@pytest.fixture(autouse=True)
def mock_neo4j_connection_open(mocker):
    return mocker.patch.object(database.platdb.Neo4jConnection, 'open', return_value=None)


@pytest.fixture(autouse=True)
def mock_neo4j_replace(mocker):
    return mocker.patch.object(neomodel.RelationshipManager, 'replace', return_value=None)


@pytest.fixture(autouse=True)
def mock_neo4j_connect(mocker):
    return mocker.patch.object(neomodel.RelationshipManager, 'connect', return_value=None)


@pytest.fixture
def mock_application_create_or_update(mocker):
    mock_application = platdb.Application(name="fixture_app")
    return mocker.patch.object(platdb.Application, 'create_or_update', return_value=[mock_application])


@pytest.fixture
def mock_compute_create_or_update(mocker):
    fake_compute = mocker.Mock(spec=platdb.Compute)
    fake_compute.name = "fixture_compute"
    fake_compute.platform = "k8s"
    fake_compute.address = "1.2.3.4"

    return mocker.patch.object(platdb.Compute, 'create_or_update', return_value=[fake_compute])


@pytest.fixture
def mock_deployment_create_or_update(mocker):
    fake_deployment = platdb.Deployment(name="fixture_deployment", address="1.2.3.4")
    return mocker.patch.object(platdb.Deployment, 'create_or_update', return_value=[fake_deployment])


@pytest.mark.parametrize('node_fixture,node_type', [
    ('mock_compute_node', NodeType.COMPUTE),
    ('mock_compute_node_without_type', NodeType.COMPUTE),
    ('mock_deployment_node', NodeType.DEPLOYMENT)
])
def test_node_to_neomodel(
    request, 
    node_fixture, 
    node_type, 
    mock_neo4j_connection_open, 
    mock_application_create_or_update,
    mock_compute_create_or_update,
    mock_deployment_create_or_update,
):
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

    node = database._neomodel_to_node(mock_compute)  # pylint:disable=protected-access

    assert node
    assert isinstance(node, Node)
