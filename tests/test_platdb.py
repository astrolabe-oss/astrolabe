# Need to disable this for the DoesNotExist exceptions. I think the 
# neomodels work by creating this dynamically so pylint does not really 
# deal with it right.
# pylint: disable=no-member

# Neo4jConnection seem like they are unused arguments but they are the
# DB connection objects that were yielded to the function.
# pylint: disable=unused-argument

import datetime

import pytest

from neomodel import ZeroOrMore

from astrolabe.platdb import (PlatDBNode,
                              StructuredNode,
                              Application,
                              CDN,
                              Compute,
                              Deployment,
                              EgressController,
                              Insights,
                              Repo,
                              Resource,
                              TrafficController)

neo4j_db_fixtures = [
    (Application, {"name": "app1"}, {"name": "new_app1"}),
    (CDN, {"name": "cdn1"}, {"name": "new_cdn1"}),
    (Compute, {
        "platform": "ec2",
        "address": "1.2.3.4",
        "protocol": "TCP",
        "protocol_multiplexor": "80"
    }, {
        "name": "new_compute1",
        "platform": "k8s",
        "address": "pod-1234nv",
        "protocol": "HTTP",
        "protocol_multiplexor": "80"
    }),
    (Deployment, {
        "deployment_type": "auto_scaling_group",
        "address": "1.2.3.4",
        "protocol": "TCP",
        "protocol_multiplexor": "80"
    }, {
        "deployment_type": "target_group",
        "address": "5.6.7.8",
        "protocol": "HTTP",
        "protocol_multiplexor": "443"
    }),
    (EgressController, {"name": "egress1"}, {"name": "new_egress1"}),
    (Insights, {
        "attribute_name": "attr1",
        "recommendation": "recommendation1",
        "starting_state": "state1",
        "upgraded_state": "state2"
    }, {
        "attribute_name": "new_attr1",
        "recommendation": "new_recommendation1",
        "starting_state": "new_state1",
        "upgraded_state": "new_state2"
    }),
    (Repo, {"name": "repo1"}, {"name": "new_repo1"}),
    (Resource, {
        "name": "resource1",
        "address": "1.2.3.4",
        "protocol": "TCP",
        "protocol_multiplexor": "80"
    }, {
        "name": "new_resource1",
        "address": "5.6.7.8",
        "protocol": "HTTP",
        "protocol_multiplexor": "443"
    }),
    (TrafficController, {
        "address": "1.2.3.4",
        "name": "access1",
        "protocol": "TCP",
        "protocol_multiplexor": "80"
    }, {
        "address": "5.6.7.8",
        "name": "new_access1",
        "protocol": "HTTP",
        "protocol_multiplexor": "443"
    })
]

def test_delete_by_attributes_object_does_not_exist(mocker):
    # arrange
    mock_nodes = mocker.patch.object(StructuredNode, "nodes")
    attributes = {"name": "nonexistant"}
    mock_nodes.get.side_effect = PlatDBNode.DoesNotExist(msg=None)

    # act
    result = PlatDBNode.delete_by_attributes(attributes=attributes)

    # assert
    assert result is False


def test_delete_by_attributes_object_exists(mocker):
    # arrange
    attributes = {}

    mock_obj = mocker.Mock(spec=PlatDBNode)
    mock_obj.name = "a name"
    mock_obj.delete.return_value = True

    mock_nodes = mocker.patch.object(StructuredNode, "nodes")
    mock_nodes.get.return_value = mock_obj

    mock_delete = mocker.patch.object(StructuredNode, "delete",
                                      return_value=True)

    # act
    result = PlatDBNode.delete_by_attributes(attributes=attributes)

    # assert
    mock_delete.assert_called_once()
    assert result is True


def test_update_object_does_not_exist(mocker):
    # arrange
    attributes = {"name": "app1"}
    new_attributes = {"name": "new_app1"}

    mock_nodes = mocker.patch.object(StructuredNode, "nodes")
    mock_nodes.get.side_effect = PlatDBNode.DoesNotExist(msg=None)

    # act
    result = PlatDBNode.update(attributes, new_attributes)

    # assert
    assert result is None


def test_update_object_exists(mocker):
    # arrange
    name_orig, data_orig, rel_orig = "app1", 5, "app2"
    name_update, data_update, rel_update = "app1", 10, "app10"
    node_orig = {"name": name_orig, "data": data_orig, "relationship": rel_orig}
    node_update = {"name": name_update, "data": data_update, "relationship": rel_update}

    mock_obj = mocker.Mock(spec=PlatDBNode)
    mock_obj.name = name_orig
    mock_obj.data = data_orig
    mock_obj.relationship = rel_orig
    mock_obj.save.side_effect = lambda x: None

    mock_nodes = mocker.patch.object(StructuredNode, "nodes")
    mock_nodes.get.side_effect = mock_obj

    # act
    obj = PlatDBNode.update(node_orig, node_update)

    # assert
    assert obj.name == name_update
    assert obj.data == data_update
    assert obj.relationship == rel_update


def test_insights_save(mocker):
    # arrange
    insight = Insights()
    mocker.patch.object(PlatDBNode, "save")

    # act
    insight.save()

    # assert
    assert isinstance(insight.updated, datetime.datetime)
    assert isinstance(insight.updated.year, int)
    assert isinstance(insight.updated.month, int)
    assert isinstance(insight.updated.day, int)
    assert insight.updated.tzinfo is datetime.timezone.utc


@pytest.mark.parametrize('cls,attrs,updated_attrs', neo4j_db_fixtures)
def test_platdb_node_to_dict_for_all_classes(mocker, cls, attrs, updated_attrs):
    obj = cls(**attrs)
    rel = []

    mocker.patch.object(ZeroOrMore, 'all', return_value=rel)

    platdb_ht = obj.platdbnode_to_dict()

    for key, value in platdb_ht.items():
        if key in attrs:
            assert value == attrs[key]
        elif key in attrs:
            # This could be a relationship or a None object if it was a 
            # class value that was left blank
            assert value in (rel, None), f'key: {key}, value: {value}'
