"""
Module Name: provider_aws

Description:
Provider for discovering nodes in AWS.  Expects runtime environment to be authenticated to AWS per aws cli.

Assumptions:
- All services exist in 1 and only 1 AWS account
- An authenticated AWS sessions exists in execution context using the default AWS authentication chain, or
using the user specific --aws-profile argument
- Instances of a service can be looked up in AWS by querying for user specified tag

Copyright:
Copyright 2024 Magellanbot, Inc

License:
SPDX-License-Identifier: Apache-2.0
"""

import sys
from typing import List

import boto3
from botocore.exceptions import ClientError
from termcolor import colored

from astrolabe import database, constants, logs
from astrolabe.node import Node, NodeTransport, NodeType
from astrolabe.network import Hint, PROTOCOL_TCP
from astrolabe.providers import ProviderInterface
from astrolabe.plugin_core import PluginArgParser
from astrolabe.profile_strategy import INVENTORY_PROFILE_STRATEGY_NAME, HINT_PROFILE_STRATEGY

TAG_NAME_POS = 0
TAG_VALUE_POS = 1


class ProviderAWS(ProviderInterface):
    def __init__(self):
        if constants.ARGS.aws_profile:
            boto3.setup_default_session(profile_name=constants.ARGS.aws_profile)
        self.ec2_client = boto3.client('ec2')
        self.rds_client = boto3.client('rds')
        self.elb_client = boto3.client('elbv2')
        self.asg_client = boto3.client('autoscaling')
        self.elasticache_client = boto3.client('elasticache')
        self.tag_filters = {tag_filter.split('=')[TAG_NAME_POS]: tag_filter.split('=')[TAG_VALUE_POS]
                            for tag_filter in constants.ARGS.aws_tag_filters}
        self._inventory_rds()
        self._inventory_elasticache()
        self._inventory_load_balancers()

    @staticmethod
    def ref() -> str:
        return 'aws'

    @staticmethod
    def register_cli_args(argparser: PluginArgParser):
        argparser.add_argument('--profile',  help='AWS Credentials file profile to use.  '
                                                  'This will override the AWS_PROFILE environment variable.')
        argparser.add_argument('--service-name-tag', required=True, metavar='TAG',
                               help='AWS tag associated with service name')
        argparser.add_argument('--tag-filters', nargs='*',  metavar='FILTER', default=[],
                               help='Additional AWS tags to filter on or services.  Specified in format: '
                                    '"TAG_NAME=VALUE" pairs')

    async def take_a_hint(self, hint: Hint) -> List[NodeTransport]:
        instance_address = await self._resolve_instance(hint.service_name)
        return [NodeTransport(
            profile_strategy_name=HINT_PROFILE_STRATEGY.name,
            provider=hint.provider,
            protocol=hint.protocol,
            protocol_mux=hint.protocol_mux,
            address=instance_address,
            debug_identifier=hint.service_name
        )]

    async def _resolve_instance(self, service_name: str) -> str:
        """
        Look up the instance address of this service in aws.  It takes the first ec2 instance which has the service name
        as the ec2 tag: $aws_tag

        :param service_name: specify the service name to look up
        :return: an IP address associated with the ec2 instance discovered
        """
        logs.logger.debug("Performing reverse AWS name lookup for %s", service_name)
        try:
            ec2 = boto3.client('ec2')
            filters = self._parse_filters(service_name)
            response = ec2.describe_instances(
                Filters=filters,
                MaxResults=5

            )
        except ClientError as exc:
            _die(exc)

        # parse name from response
        try:
            ipaddr = response['Reservations'][0]['Instances'][0]['PrivateIpAddress']
        except (KeyError, IndexError) as exc:
            print(colored("ec2 describe-instances response was insufficient for instance lookup", 'red'))
            print(colored(f"- {exc}", 'yellow'))
            constants.PP.pprint(colored(filters, 'yellow'))
            constants.PP.pprint(colored(response, 'yellow'))
            raise exc

        return ipaddr

    def _parse_filters(self, service_name: str) -> List[dict]:
        """
        Generate AWS filters for the instance from service name and CLI args

        :param service_name: the service name to filter on
        :return:
        """
        filters = [{
            'Name': 'instance-state-name',
            'Values': ['running']
        }, {
            'Name': f"tag:{constants.ARGS.aws_service_name_tag}",
            'Values': [service_name]
        }]
        for tag, value in self.tag_filters.items():
            filters.append({
                'Name': f"tag:{tag}",
                'Values': [value]
            })
        return filters

    def _inventory_rds(self):
        paginator = self.rds_client.get_paginator('describe_db_instances')
        for page in paginator.paginate():
            for instance in page['DBInstances']:
                rds_address = instance['Endpoint']['Address']
                name = instance['DBInstanceIdentifier']

                # Add instance information to the global dictionary
                node = Node(
                    node_type=NodeType.RESOURCE,
                    profile_strategy_name=INVENTORY_PROFILE_STRATEGY_NAME,
                    provider='aws',
                    service_name=name,
                    aliases=[rds_address]
                )
                node.set_profile_timestamp()
                database.save_node(node)
                logs.logger.info("Inventoried 1 AWS RDS node: %s", node.debug_id())

    def _inventory_elasticache(self):
        paginator = self.elasticache_client.get_paginator('describe_cache_clusters')
        for page in paginator.paginate(ShowCacheNodeInfo=True):
            for cluster in page['CacheClusters']:
                cluster_name = cluster['CacheClusterId']
                for node in cluster['CacheNodes']:
                    es_address = node['Endpoint']['Address']
                    node = Node(
                        node_type=NodeType.RESOURCE,
                        profile_strategy_name=INVENTORY_PROFILE_STRATEGY_NAME,
                        provider='aws',
                        service_name=cluster_name,
                        aliases=[es_address]
                    )
                    node.set_profile_timestamp()
                    database.save_node(node)
                    logs.logger.info("Inventoried 1 AWS ElastiCache node: %s", node.debug_id())

    # pylint:disable=too-many-locals,too-many-nested-blocks
    def _inventory_load_balancers(self):
        paginator = self.elb_client.get_paginator('describe_load_balancers')
        for page in paginator.paginate():
            for lb in page['LoadBalancers']:  # pylint:disable=invalid-name
                lb_address = lb['DNSName']
                name = lb['LoadBalancerName']

                # find the ASG(s) the load balancer sends requests to.  There is no
                #  direct link in AWS between load balancer and ASG, so we have to find
                #  ALB instances and then derive the ASG(s) from the instances!
                asg_nodes = {}
                target_groups = self.elb_client.describe_target_groups(LoadBalancerArn=lb['LoadBalancerArn'])
                for tgg in target_groups['TargetGroups']:
                    # ALB Target Group
                    tg_name = tgg['TargetGroupName']
                    tg_port = tgg['Port']
                    logs.logger.debug("  Target Group: %s", tg_name)
                    target_health = self.elb_client.describe_target_health(TargetGroupArn=tgg['TargetGroupArn'])
                    for target in target_health['TargetHealthDescriptions']:
                        # ALB EC2 Instances
                        instance_id = target['Target']['Id']
                        auto_scaling_instances = self.asg_client.describe_auto_scaling_instances(
                            InstanceIds=[instance_id]
                        )
                        asg_node = None
                        for asg_instance in auto_scaling_instances['AutoScalingInstances']:
                            # Create the ASG Node
                            if not asg_node:  # we only need this once
                                asg_name = asg_instance['AutoScalingGroupName']
                                asg_address = asg_name
                                asg_node = Node(
                                    address=asg_address,
                                    node_type=NodeType.DEPLOYMENT,
                                    profile_strategy_name=INVENTORY_PROFILE_STRATEGY_NAME,
                                    protocol=PROTOCOL_TCP,
                                    protocol_mux=tg_port,
                                    provider='aws',
                                    service_name=asg_name
                                )
                                asg_nodes[f"ASG_{asg_name}"] = asg_node
                                database.save_node(asg_node)
                                logs.logger.info("Inventoried 1 AWS ASG node: %s", asg_node.debug_id())
                            instance_info = self.ec2_client.describe_instances(InstanceIds=[instance_id])
                            public_ip = instance_info['Reservations'][0]['Instances'][0].get('PublicIpAddress')
                            # Create the EC2 Instance Node
                            ec2_node = Node(
                                address=public_ip,
                                node_type=NodeType.COMPUTE,
                                profile_strategy_name=INVENTORY_PROFILE_STRATEGY_NAME,
                                protocol=PROTOCOL_TCP,
                                protocol_mux=tg_port,
                                provider='ssh'
                            )
                            database.connect_nodes(asg_node, ec2_node)
                            database.save_node(ec2_node)
                            logs.logger.info("Inventoried 1 AWS EC2 node: %s", ec2_node.debug_id())

                # Create the ALB Node
                lb_node = Node(
                    node_type=NodeType.TRAFFIC_CONTROLLER,
                    profile_strategy_name=INVENTORY_PROFILE_STRATEGY_NAME,
                    provider='aws',
                    service_name=name,
                    aliases=[lb_address],
                    children=asg_nodes
                )
                database.save_node(lb_node)
                logs.logger.info("Inventoried 1 AWS ALB node: %s", lb_node.debug_id())


def _die(err):
    print(colored('AWS boto3 Authentication Failed!  Please check your aws credentials, have you set AWS_PROFILE?',
                  'red'))
    print(colored(f"- {err}", 'yellow'))
    sys.exit(1)
