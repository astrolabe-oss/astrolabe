# pylint: disable=unused-argument,too-many-arguments,too-many-positional-arguments
"""Unit tests for the ProviderAWS class"""
import pytest
from astrolabe.node import NodeType
from astrolabe import database
from astrolabe.plugins.provider_aws import ProviderAWS


@pytest.fixture
def app_name():
    """The application name used in the test"""
    return "test-app"


@pytest.fixture
def lb_dns_name():
    """The load balancer DNS name used in the test"""
    return "test-lb-123456789.us-west-2.elb.amazonaws.com"


@pytest.fixture
def asg_name():
    """The auto scaling group name used in the test"""
    return "test-asg"


@pytest.fixture
def public_ip():
    """The public IP address used in the test"""
    return '54.123.45.67'


@pytest.fixture
def private_ip():
    """The private IP address used in the test"""
    return '10.0.0.123'


@pytest.fixture
def mock_boto3_setup(mocker):
    """Mock boto3.setup_default_session to prevent real AWS calls"""
    return mocker.patch('boto3.setup_default_session')


@pytest.fixture
def mock_elb_client(mocker, lb_dns_name, app_name):
    """Create a mock ELB client with appropriate responses"""
    mock_client = mocker.MagicMock()

    # Mock ELB paginator
    mock_paginator = mocker.MagicMock()
    mock_paginator.paginate.return_value = [{
        'LoadBalancers': [{
            'LoadBalancerArn':
                'arn:aws:elasticloadbalancing:us-west-2:123456789012:loadbalancer/app/test-lb/50dc6c495c0c9188',
            'DNSName': lb_dns_name,
            'LoadBalancerName': 'test-lb'
        }]
    }]
    mock_client.get_paginator.return_value = mock_paginator

    # Mock ELB describe_listeners
    mock_client.describe_listeners.return_value = {
        'Listeners': [{
            'Port': 80
        }]
    }

    # Mock ELB describe_tags
    mock_client.describe_tags.return_value = {
        'TagDescriptions': [{
            'Tags': [{
                'Key': 'AppName',
                'Value': app_name
            }]
        }]
    }

    # Mock ELB describe_target_groups
    mock_client.describe_target_groups.return_value = {
        'TargetGroups': [{
            'TargetGroupName': 'test-tg',
            'Port': 8080,
            'TargetGroupArn': 'arn:aws:elasticloadbalancing:us-west-2:123456789012:targetgroup/test-tg/73e2d6bc24d8a067'
        }]
    }

    # Mock ELB describe_target_health
    mock_client.describe_target_health.return_value = {
        'TargetHealthDescriptions': [{
            'Target': {
                'Id': 'i-1234567890abcdef0'
            }
        }]
    }

    return mock_client


@pytest.fixture
def mock_ec2_client(mocker, public_ip, private_ip):
    """Create a mock EC2 client with appropriate responses"""
    mock_client = mocker.MagicMock()

    # Mock EC2 describe_instances
    mock_client.describe_instances.return_value = {
        'Reservations': [{
            'Instances': [{
                'PublicIpAddress': public_ip,
                'PrivateIpAddress': private_ip
            }]
        }]
    }

    return mock_client


@pytest.fixture
def mock_asg_client(mocker, asg_name):
    """Create a mock ASG client with appropriate responses"""
    mock_client = mocker.MagicMock()

    # Mock ASG describe_auto_scaling_instances
    mock_client.describe_auto_scaling_instances.return_value = {
        'AutoScalingInstances': [{
            'AutoScalingGroupName': asg_name
        }]
    }

    return mock_client


@pytest.fixture
def mock_rds_client(mocker):
    """Create a mock RDS client"""
    return mocker.MagicMock()


@pytest.fixture
def mock_elasticache_client(mocker):
    """Create a mock ElastiCache client"""
    return mocker.MagicMock()


@pytest.fixture
def mock_boto3_client(mocker, mock_elb_client, mock_ec2_client,
                      mock_asg_client, mock_rds_client, mock_elasticache_client):
    """Mock boto3.client to return appropriate mocks for each service"""
    mock_client = mocker.patch('boto3.client')

    def get_client(service_name, **kwargs):
        if service_name == 'elbv2':
            return mock_elb_client
        elif service_name == 'ec2':
            return mock_ec2_client
        elif service_name == 'autoscaling':
            return mock_asg_client
        elif service_name == 'rds':
            return mock_rds_client
        elif service_name == 'elasticache':
            return mock_elasticache_client
        return mocker.MagicMock()

    mock_client.side_effect = get_client

    return mock_client


class TestProviderAWS:
    """Test cases for AWS provider functionality"""

    @pytest.mark.parametrize('instance_has_private_ip', [True, False])
    def test_inventory_load_balancers_private_ip_flag_true(self, patch_database, cli_args_mock,
                                                           mock_boto3_setup, mock_boto3_client, private_ip,
                                                           public_ip, instance_has_private_ip):
        """Test that private IP is used when the aws_use_private_ips flag is set to True"""
        # Arrange
        cli_args_mock.aws_use_private_ips = True
        provider = ProviderAWS()
        if not instance_has_private_ip:
            mock_ec2 = provider.ec2_client
            del mock_ec2.describe_instances.return_value['Reservations'][0]['Instances'][0]['PrivateIpAddress']

        # Act
        provider._inventory_load_balancers()  # pylint:disable=protected-access

        # Assert
        expected_ipaddr = private_ip if instance_has_private_ip else public_ip
        ec2_node = database.get_node_by_address(expected_ipaddr)
        assert ec2_node is not None, f"EC2 node with {expected_ipaddr} should have been created"
        assert ec2_node.node_type == NodeType.COMPUTE, "Node should be a compute node"

    def test_inventory_load_balancers_private_ip_flag_false(self, patch_database, cli_args_mock,
                                                            mock_boto3_setup, mock_boto3_client, public_ip):
        """Test that public IP is used when the aws_use_private_ips flag is set to False"""
        # Arrange
        cli_args_mock.aws_use_private_ips = False
        provider = ProviderAWS()

        # Act
        provider._inventory_load_balancers()  # pylint:disable=protected-access

        # Assert
        ec2_node = database.get_node_by_address(public_ip)
        assert ec2_node is not None, f"EC2 node with public IP {public_ip} should have been created"
        assert ec2_node.node_type == NodeType.COMPUTE, "Node should be a compute node"

    def test_app_name_tag_assigned_to_nodes(self, patch_database, cli_args_mock,
                                            mock_boto3_setup, mock_boto3_client,
                                            app_name, lb_dns_name, asg_name):
        """Test that app_name_tag is properly assigned to TRAFFIC_CONTROLLER and DEPLOYMENT nodes"""
        # Arrange
        cli_args_mock.aws_app_name_tag = 'AppName'
        cli_args_mock.aws_use_private_ips = False
        provider = ProviderAWS()

        # Act
        provider._inventory_load_balancers()  # pylint:disable=protected-access

        # Assert
        dns_lookup_nodes = dict(database.get_nodes_pending_dnslookup())

        assert lb_dns_name in dns_lookup_nodes, \
            f"Traffic controller with DNS name {lb_dns_name} should be in DNS lookup nodes"

        traffic_controller = dns_lookup_nodes[lb_dns_name]
        assert traffic_controller.service_name == app_name, \
            f"TRAFFIC_CONTROLLER node should have service_name={app_name}"

        # Find the deployment node by address (ASG name)
        deployment_node = database.get_node_by_address(asg_name)
        assert deployment_node is not None, f"DEPLOYMENT node with address={asg_name} should exist"
        assert deployment_node.service_name == app_name, f"DEPLOYMENT node should have service_name={app_name}"

    def test_app_name_tag_missing_in_aws_response(self, patch_database, cli_args_mock,
                                                  mock_boto3_setup, mock_boto3_client,
                                                  lb_dns_name, asg_name):
        """Test that nodes are created without service_name when tag is missing in AWS response"""
        # Arrange
        cli_args_mock.aws_app_name_tag = 'AppName'
        cli_args_mock.aws_use_private_ips = False
        provider = ProviderAWS()
        elb_client = provider.elb_client
        elb_client.describe_tags.return_value = {'TagDescriptions': [{'Tags': []}]}

        # Act
        provider._inventory_load_balancers()  # pylint:disable=protected-access

        # Assert
        dns_lookup_nodes = dict(database.get_nodes_pending_dnslookup())
        assert lb_dns_name in dns_lookup_nodes, \
            f"Traffic controller with DNS name {lb_dns_name} should be in DNS lookup nodes"
        traffic_controller = dns_lookup_nodes[lb_dns_name]
        assert traffic_controller.service_name is None, \
            "TRAFFIC_CONTROLLER node should not have service_name when tag is missing"

        # Find the deployment node by address (ASG name)
        deployment_node = database.get_node_by_address(asg_name)
        assert deployment_node is not None, f"DEPLOYMENT node with address={asg_name} should exist"
        assert not hasattr(deployment_node, 'service_name') or deployment_node.service_name is None, \
            "DEPLOYMENT node should not have service_name when tag is missing"

    def test_inventory_load_balancers_missing_port(self, patch_database, cli_args_mock,
                                                   mock_boto3_setup, mock_boto3_client,
                                                   lb_dns_name, asg_name, public_ip):
        """Test that the code handles a target group without a Port attribute"""
        # Arrange
        cli_args_mock.aws_app_name_tag = 'AppName'
        cli_args_mock.aws_use_private_ips = False
        provider = ProviderAWS()

        # Modify the ELB client response to remove the Port from the target group
        elb_client = provider.elb_client
        elb_client.describe_target_groups.return_value = {
            'TargetGroups': [{
                'TargetGroupName': 'test-tg',
                # Port is intentionally missing
                'TargetGroupArn': 'arn:aws:elasticloadbalancing:us-west-2:123456789012:targetgroup/test-tg/73e2d6bc24d8a067'
            }]
        }

        # Act
        # This should not raise a KeyError if fixed correctly
        provider._inventory_load_balancers()

        # Assert
        # Verify that the nodes were still created, even without a port
        dns_lookup_nodes = dict(database.get_nodes_pending_dnslookup())
        assert lb_dns_name in dns_lookup_nodes, "Traffic controller should still be created"

        # Find the deployment node
        deployment_node = database.get_node_by_address(asg_name)
        assert deployment_node is not None, "Deployment node should still be created"

        # Find the compute node using its IP address
        compute_node = database.get_node_by_address(public_ip)
        assert compute_node is not None, "Compute node should still be created"

        # The compute node should have protocol_mux set to None or a default value
        assert compute_node.protocol_mux is None or isinstance(compute_node.protocol_mux, int), \
            "Compute node should have protocol_mux set to None or a default value"