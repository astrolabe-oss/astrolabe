# Neo4jConnection seem like they are unused arguments but they are the
# DB connection objects that were yielded to the function.
# pylint: disable=unused-argument

import pytest

from neomodel import db

from astrolabe.platdb import (Neo4jConnection,
                              Application,
                              Compute,
                              Deployment)


@pytest.fixture(scope="module")
def neo4j_connection():
    uri = "bolt://localhost:17687"
    username = "neo4j"
    password = "guruai11"
    driver = Neo4jConnection(uri=uri, auth=(username, password))
    driver.open()
    yield driver
    driver.close()


@pytest.fixture(autouse=True)
def clear_database(neo4j_connection):
    db.cypher_query("MATCH (n) DETACH DELETE n")


def create_mock_service(name):
    return {
        'name': name,
        'platform': 'k8s',
        'address': '1.2.3.4',
        'protocol': 'HTTP',
        'protocol_multiplexor': '80'
    }


@pytest.fixture
def mock_complex_graph(neo4j_connection):
    """Complex as in it has children. This is not just testing obj types.

    Applications and Computes are connected based off numbers, 
    so app1 -> compute1 etc. 
    """
    # Nodes
    app1 = Application(**{'name': 'app1'}).save()
    app2 = Application(**{'name': 'app2'}).save()
    compute1 = Compute(**create_mock_service('compute1')).save()
    compute2 = Compute(**create_mock_service('compute2')).save()
    deployment1 = Deployment(**{'address': 'addy1', 'cluster': 'aws_vpc_id'}).save()
    deployment2 = Deployment(**{'address': 'addy2', 'cluster': 'eks-cluster'}).save()

    # Connections
    deployment1.computes.connect(compute1)
    deployment1.application.connect(app1)

    deployment2.computes.connect(compute2)
    deployment2.application.connect(app2)
