#!/usr/bin/env python3
"""
Neo4j Data Generator for Network Topology

This script connects to a Neo4j database and populates it with synthetic data
for network topology visualization. Configuration is done through environment
variables or a .env file.
"""

import os
import random
import string
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Tuple, Optional, Any

from dotenv import load_dotenv
load_dotenv()  # Load environment variables before db init

from astrolabe import database, network
from astrolabe.node import Node, NodeType
from astrolabe.network import PROTOCOL_TCP



# Data generation settings
NUM_EKS_CLUSTERS = int(os.getenv("NUM_EKS_CLUSTERS", "3"))
NUM_AWS_VPCS = int(os.getenv("NUM_AWS_VPCS", "1"))
NUM_APPLICATIONS = int(os.getenv("NUM_APPLICATIONS", "20"))
NUM_DEPLOYMENTS_PER_APP = int(os.getenv("NUM_DEPLOYMENTS_PER_APP", "2"))
NUM_COMPUTES_PER_DEPLOYMENT = int(os.getenv("NUM_COMPUTES_PER_DEPLOYMENT", "2"))
DEPLOYMENTS_HAVE_CANARIES = os.getenv("DEPLOYMENTS_HAVE_CANARIES", "false").lower() == "true"
MULTI_CLUSTER_DEPLOYMENTS = os.getenv("MULTI_CLUSTER_DEPLOYMENTS", "true").lower() == "true"
NUM_PUBLIC_IP_NODES = int(os.getenv("NUM_PUBLIC_IP_NODES", "10"))
PERCENT_UNKNOWN_CLUSTER = int(os.getenv("PERCENT_UNKNOWN_CLUSTER", "20"))

# Make sure NUM_PUBLIC_IP_NODES is not greater than total nodes
MAX_POSSIBLE_NODES = NUM_APPLICATIONS * NUM_DEPLOYMENTS_PER_APP * NUM_COMPUTES_PER_DEPLOYMENT
if NUM_PUBLIC_IP_NODES > MAX_POSSIBLE_NODES:
    NUM_PUBLIC_IP_NODES = MAX_POSSIBLE_NODES


class AstrolabeDataGenerator:
    """Class for generating and inserting network topology data into Neo4j using Astrolabe components"""

    def __init__(self):
        # Initialize Astrolabe's database connection
        database.init()

        self.app_names = []
        self.deployment_names = {}
        self.cluster_names = []
        self.vpc_names = []
        self.resource_names = []
        # Statistics for compute nodes creation
        self.compute_count = 0
        self.public_ips_assigned = 0
        self.unknown_clusters_assigned = 0
        self.compute_nodes = []
        # Statistics for traffic controller creation
        self.tc_count = 0
        self.tc_nodes = []
        # Store all nodes for relationship creation
        self.all_nodes = {}

    def close(self) -> None:
        """Close the Neo4j connection"""
        database.close()

    def generate_random_name(self, prefix: str) -> str:
        """Generate a random name with the given prefix"""
        adjectives = ["fast", "secure", "scalable", "dynamic", "agile", "flexible", "robust",
                    "efficient", "powerful", "advanced", "smart", "innovative", "responsive",
                    "reliable", "stable", "seamless", "intuitive", "precise", "optimal", "vibrant"]
        nouns = ["service", "system", "platform", "engine", "framework", "tool", "module",
                "component", "solution", "application", "processor", "manager", "controller",
                "handler", "adapter", "connector", "gateway", "bridge", "router", "proxy"]

        return f"{prefix}-{random.choice(adjectives)}-{random.choice(nouns)}"

    def generate_ip_address(self, vpc_index: int = 0, private: bool = True) -> str:
        """Generate a random IP address"""
        if private:
            return f"10.{vpc_index}.{random.randint(0, 255)}.{random.randint(1, 254)}"
        else:
            return f"54.{random.randint(0, 255)}.{random.randint(0, 255)}.{random.randint(1, 254)}"

    def generate_timestamps(self) -> float:
        """Generate a timestamp with random offset for variability"""
        now = time.time()  # Current time in seconds (Unix timestamp)
        return now - random.uniform(0, 86400)  # Random offset up to 1 day

    def initialize_configurations(self) -> None:
        """Initialize data structures with names and references"""
        # Generate EKS cluster names
        for i in range(NUM_EKS_CLUSTERS):
            region = "west" if i % 2 == 0 else "east"
            env = "dev" if i % 3 == 0 else "prod"
            self.cluster_names.append(f"eks-{region}-{i+1}-{env}")

        # Generate VPC names
        for i in range(NUM_AWS_VPCS):
            region = "west" if i % 2 == 0 else "east"
            env = "prod" if i < NUM_AWS_VPCS / 2 else "dev"
            self.vpc_names.append(f"us-{region}-vpc-{env}")

        # Generate application names
        for i in range(NUM_APPLICATIONS):
            kebab_name = self.generate_random_name("app")
            camel_name = ''.join(word.capitalize() for word in kebab_name.split('-'))
            self.app_names.append((kebab_name, camel_name))
            self.deployment_names[kebab_name] = []

            # Generate deployment names for each application
            for j in range(NUM_DEPLOYMENTS_PER_APP):
                if j == 0:
                    deployment_name = f"{kebab_name}-main"
                else:
                    deployment_name = f"{kebab_name}-shard-{j}"
                self.deployment_names[kebab_name].append(deployment_name)

                # Add canary deployment if enabled
                if DEPLOYMENTS_HAVE_CANARIES and j == 0:
                    self.deployment_names[kebab_name].append(f"{kebab_name}-canary")

        # Generate resource names for shared services
        self.resource_names = [
            "aws-s3", "aws-dynamodb", "aws-sqs", "postgres-main",
            "redis-main", "elasticsearch-main"
        ]

        # Add app-specific cache resources
        for app_kebab, _ in self.app_names:
            self.resource_names.append(f"{app_kebab}-cache")


    def create_deployments(self) -> None:
        """Create Deployment nodes and connect them to Applications"""
        print("Creating deployments...")

        # Calculate how many compute nodes should have unknown clusters
        total_computes = sum(len(deployments) * NUM_COMPUTES_PER_DEPLOYMENT
                           for deployments in self.deployment_names.values())
        unknown_cluster_target = int(total_computes * PERCENT_UNKNOWN_CLUSTER / 100)

        # Reset compute node and traffic controller statistics
        self.compute_count = 0
        self.public_ips_assigned = 0
        self.unknown_clusters_assigned = 0
        self.compute_nodes = []
        self.tc_count = 0
        self.tc_nodes = []

        # Track public IP nodes that need connections
        self.public_ip_nodes_by_deployment = {}

        deployment_count = 0
        for i, (kebab_name, _) in enumerate(self.app_names):
            for j, deployment_name in enumerate(self.deployment_names[kebab_name]):
                # Determine which cluster to deploy to
                if MULTI_CLUSTER_DEPLOYMENTS:
                    # If multi-cluster, distribute deployments across clusters
                    cluster_index = (i + j) % NUM_EKS_CLUSTERS
                else:
                    # If single-cluster, use the app index to determine cluster
                    cluster_index = i % NUM_EKS_CLUSTERS

                cluster = self.cluster_names[cluster_index]

                # Check if this is a canary deployment
                is_canary = "canary" in deployment_name

                # Generate address and other properties
                address = self.generate_ip_address(vpc_index=cluster_index)
                protocol_multiplexor = str(random.randint(30000, 32767))

                # Create deployment node
                deployment_node = Node(
                    profile_strategy_name="Inventory",
                    provider="k8s",
                    node_name=deployment_name,
                    service_name=kebab_name,
                    node_type=NodeType.DEPLOYMENT,
                    protocol=PROTOCOL_TCP,
                    protocol_mux=protocol_multiplexor,
                    address=address,
                    public_ip=False,
                    cluster=cluster
                )

                # Set profile timestamp
                deployment_node.set_profile_timestamp()

                # Save the node to the database
                saved_deployment = database.save_node(deployment_node)

                # Store the node for later use in creating relationships
                self.all_nodes[deployment_name] = saved_deployment

                # Note: The deployment is automatically connected to its application
                # when it's saved because it has a service_name set

                # Create compute nodes for this deployment
                for pod_index in range(NUM_COMPUTES_PER_DEPLOYMENT):
                    self._create_compute_node(
                        app_kebab=kebab_name,
                        deployment_name=deployment_name,
                        cluster=cluster,
                        pod_index=pod_index,
                        unknown_cluster_target=unknown_cluster_target
                    )

                # Ensure all public IP nodes for this deployment are connected to at least one non-public IP node
                self._connect_public_ip_nodes(deployment_name)

                # Create traffic controller if this is a main deployment
                if "main" in deployment_name:
                    self._create_traffic_controller(
                        app_kebab=kebab_name,
                        deployment_name=deployment_name,
                        cluster=cluster
                    )

                deployment_count += 1

        print(f"Created {deployment_count} deployments and connected them to applications")
        print(f"Created {self.compute_count} compute nodes with {self.public_ips_assigned} public IPs")
        print(f"Assigned {self.unknown_clusters_assigned} compute nodes to unknown clusters")
        print(f"Created {self.tc_count} traffic controllers and connected them to deployments")

    def _create_compute_node(self, app_kebab: str, deployment_name: str, cluster: str, 
                            pod_index: int, unknown_cluster_target: int) -> None:
        """Create a single compute node and connect it to a deployment

        Args:
            app_kebab: The application name in kebab format
            deployment_name: The name of the deployment this node belongs to
            cluster: The EKS cluster this node belongs to
            pod_index: The index of this pod within the deployment
            unknown_cluster_target: Target number of nodes with unknown clusters
        """
        pod_name = f"{deployment_name}-pod-{pod_index+1}"

        # Determine if this pod should have a public IP
        has_public_ip = self.public_ips_assigned < NUM_PUBLIC_IP_NODES and random.random() < 0.5
        if has_public_ip:
            address = self.generate_ip_address(private=False)
            self.public_ips_assigned += 1
        else:
            address = pod_name  # Use pod name as address

        # Determine if this pod should have an unknown cluster
        if self.unknown_clusters_assigned < unknown_cluster_target and random.random() < 0.3:
            pod_cluster = "unknown"
            self.unknown_clusters_assigned += 1
        else:
            pod_cluster = cluster

        # Create compute node
        compute_node = Node(
            profile_strategy_name="Inventory",
            provider="k8s",
            node_name=pod_name,
            service_name=app_kebab,
            node_type=NodeType.COMPUTE,
            protocol=PROTOCOL_TCP,
            protocol_mux="8080",
            address=address,
            public_ip=has_public_ip,
            cluster=pod_cluster,
            containerized=True
        )

        # Set profile timestamp
        compute_node.set_profile_timestamp()

        # Save the node to the database
        saved_compute = database.save_node(compute_node)

        # Store the node for later use in creating relationships
        self.all_nodes[pod_name] = saved_compute
        self.compute_nodes.append(saved_compute)

        # Connect the compute node to its deployment only if it doesn't have a public IP
        # Compute nodes with public_ip=true should only be connected via CALLS from other compute nodes
        deployment_node = self.all_nodes[deployment_name]
        if not has_public_ip:
            database.connect_nodes(deployment_node, saved_compute)

            # Find any public IP compute nodes for this deployment and connect from this node
            for node in self.compute_nodes:
                if (node.service_name == app_kebab and 
                    node.public_ip and 
                    node.node_name.startswith(deployment_name)):
                    database.connect_nodes(saved_compute, node)
        else:
            # Track this public IP node for later connection
            if deployment_name not in self.public_ip_nodes_by_deployment:
                self.public_ip_nodes_by_deployment[deployment_name] = []
            self.public_ip_nodes_by_deployment[deployment_name].append(saved_compute)

        self.compute_count += 1

    def _connect_public_ip_nodes(self, deployment_name: str) -> None:
        """Ensure all public IP nodes for a deployment are connected to at least one non-public IP node

        Args:
            deployment_name: The name of the deployment to check
        """
        if deployment_name not in self.public_ip_nodes_by_deployment:
            return

        # Find all non-public IP compute nodes for this deployment
        non_public_ip_nodes = [
            node for node in self.compute_nodes 
            if node.node_name.startswith(deployment_name) and not node.public_ip
        ]

        if not non_public_ip_nodes:
            # If there are no non-public IP nodes, we can't connect the public IP nodes
            # This should be rare given our random assignment of public IPs
            return

        # Connect each public IP node to a random non-public IP node
        for public_ip_node in self.public_ip_nodes_by_deployment[deployment_name]:
            non_public_ip_node = random.choice(non_public_ip_nodes)
            database.connect_nodes(non_public_ip_node, public_ip_node)

        # Clear the list of public IP nodes for this deployment
        self.public_ip_nodes_by_deployment[deployment_name] = []


    def _create_traffic_controller(self, app_kebab: str, deployment_name: str, cluster: str) -> None:
        """Create a single traffic controller and connect it to relevant deployments

        Args:
            app_kebab: The application name in kebab format
            deployment_name: The name of the main deployment this TC is for
            cluster: The EKS cluster this TC belongs to
        """
        # Generate TC name based on app and region
        tc_name = f"{app_kebab}-nlb"
        if "east" in cluster:
            tc_name += "-east"

        # Generate address
        cluster_index = self.cluster_names.index(cluster)
        address = self.generate_ip_address(vpc_index=cluster_index+10)  # Use different subnet

        # Generate DNS names
        region = "us-west-1" if "west" in cluster else "us-east-1"
        random_suffix = ''.join(random.choices(string.digits, k=4))
        dns_name = f"k8s-{app_kebab}-main-{random_suffix}.elb.{region}.amazonaws.com"

        # Create traffic controller node
        tc_node = Node(
            profile_strategy_name="Inventory",
            provider="k8s",
            node_name=tc_name,
            service_name=app_kebab,
            node_type=NodeType.TRAFFIC_CONTROLLER,
            protocol=PROTOCOL_TCP,
            protocol_mux="80",
            address=address,
            public_ip=False,
            cluster=cluster,
            aliases=[dns_name]
        )

        # Set profile timestamp
        tc_node.set_profile_timestamp()

        # Save the node to the database
        saved_tc = database.save_node(tc_node)

        # Store the node for later use in creating relationships
        self.all_nodes[tc_name] = saved_tc
        self.tc_nodes.append(saved_tc)

        # Connect the traffic controller to the main deployment
        main_deployment = self.all_nodes[deployment_name]
        database.connect_nodes(saved_tc, main_deployment)

        # Connect to canary deployment if it exists
        canary_name = deployment_name.replace("main", "canary")
        if canary_name in self.deployment_names[app_kebab]:
            canary_deployment = self.all_nodes[canary_name]
            database.connect_nodes(saved_tc, canary_deployment)

        self.tc_count += 1

    def create_resources(self) -> None:
        """Create Resource nodes for external services and databases"""
        print("Creating resources...")

        # Define standard resources
        standard_resources = [
            # AWS external services
            {
                "name": "aws-s3",
                "address": "s3.amazonaws.com",
                "dns_names": ["s3.amazonaws.com"],
                "protocol_multiplexor": "443",
                "public_ip": False,
                "cluster": None,
                "provider": "aws"
            },
            {
                "name": "aws-dynamodb",
                "address": "dynamodb.us-west-1.amazonaws.com",
                "dns_names": ["dynamodb.us-west-1.amazonaws.com"],
                "protocol_multiplexor": "443",
                "public_ip": False,
                "cluster": None,
                "provider": "aws"
            },
            {
                "name": "aws-sqs",
                "address": "sqs.us-east-1.amazonaws.com",
                "dns_names": ["sqs.us-east-1.amazonaws.com"],
                "protocol_multiplexor": "443",
                "public_ip": False,
                "cluster": None,
                "provider": "aws"
            },
            # Database resources
            {
                "name": "postgres-main",
                "address": "postgres-main.internal",
                "dns_names": ["postgres-main.internal"],
                "protocol_multiplexor": "5432",
                "public_ip": False,
                "cluster": "shared-services",
                "provider": "k8s"
            },
            {
                "name": "redis-main",
                "address": "redis-main.internal",
                "dns_names": ["redis-main.internal"],
                "protocol_multiplexor": "6379",
                "public_ip": False,
                "cluster": "shared-services",
                "provider": "k8s"
            },
            {
                "name": "elasticsearch-main",
                "address": "elasticsearch-main.internal",
                "dns_names": ["elasticsearch-main.internal"],
                "protocol_multiplexor": "9200",
                "public_ip": False,
                "cluster": "shared-services",
                "provider": "k8s"
            }
        ]

        # Create standard resources
        resource_count = 0
        for resource_data in standard_resources:
            resource_node = Node(
                profile_strategy_name="Inventory",
                provider=resource_data["provider"],
                node_name=resource_data["name"],
                node_type=NodeType.RESOURCE,
                protocol=PROTOCOL_TCP,
                protocol_mux=resource_data["protocol_multiplexor"],
                address=resource_data["address"],
                public_ip=resource_data["public_ip"],
                cluster=resource_data["cluster"] or "",
                aliases=resource_data["dns_names"]
            )

            # Set profile timestamp
            resource_node.set_profile_timestamp()

            # Save the node to the database
            saved_resource = database.save_node(resource_node)

            # Store the node for later use in creating relationships
            self.all_nodes[resource_data["name"]] = saved_resource
            resource_count += 1

        # Create app-specific cache resources
        for app_kebab, _ in self.app_names:
            cache_name = f"{app_kebab}-cache"

            resource_node = Node(
                profile_strategy_name="Inventory",
                provider="k8s",
                node_name=cache_name,
                node_type=NodeType.RESOURCE,
                protocol=PROTOCOL_TCP,
                protocol_mux="6379",
                address=f"{cache_name}.internal",
                public_ip=False,
                cluster="shared-services",
                aliases=[f"{cache_name}.internal"]
            )

            # Set profile timestamp
            resource_node.set_profile_timestamp()

            # Save the node to the database
            saved_resource = database.save_node(resource_node)

            # Store the node for later use in creating relationships
            self.all_nodes[cache_name] = saved_resource
            resource_count += 1

        print(f"Created {resource_count} resources")

    def create_unknown_nodes(self) -> None:
        """Create Unknown nodes for endpoints that can't be identified"""
        print("Creating unknown nodes...")

        # Create a few unknown nodes
        for i in range(5):
            unknown_name = f"unknown-endpoint-{i+1}"

            unknown_node = Node(
                profile_strategy_name="Inventory",
                provider="ssh",
                node_name=unknown_name,
                node_type=NodeType.UNKNOWN,
                address=unknown_name,
                cluster="unknown"
            )

            # Set profile timestamp
            unknown_node.set_profile_timestamp()

            # Save the node to the database
            saved_unknown = database.save_node(unknown_node)

            # Store the node for later use in creating relationships
            self.all_nodes[unknown_name] = saved_unknown

        print("Created 5 unknown nodes")

    def create_connections(self) -> None:
        """Create connections between nodes (CALLS, CONNECTS_TO relationships)"""
        print("Creating connections between nodes...")

        # Create app-specific resource connections
        self._create_app_specific_resource_connections()

        # Create shared resource connections
        self._create_shared_resource_connections()

        # Create deployment-to-deployment connections
        self._create_deployment_connections()

        # Create compute-to-unknown connections
        self._create_compute_to_unknown_connections()

        # Create deployment-to-traffic-controller connections
        self._create_deployment_to_tc_connections()

        print("Finished creating connections between nodes")

    def _create_app_specific_resource_connections(self) -> None:
        """Create connections from compute nodes to their app-specific resources like caches"""
        print("Creating app-specific resource connections...")

        for app_kebab, _ in self.app_names:
            cache_name = f"{app_kebab}-cache"
            cache_node = self.all_nodes.get(cache_name)

            if not cache_node:
                continue

            # Find all compute nodes for this application
            app_compute_nodes = [node for node in self.compute_nodes if node.service_name == app_kebab]

            # Connect each compute node to the cache
            for compute_node in app_compute_nodes:
                database.connect_nodes(compute_node, cache_node)

    def _create_shared_resource_connections(self) -> None:
        """Create connections to shared resources based on defined patterns"""
        print("Creating shared resource connections...")

        # Define shared resource connections with their patterns
        shared_resource_connections = [
            # format: (resource_name, probability, description)
            ("postgres-main", 1.0, "All compute nodes use postgres"),
            ("redis-main", 0.6, "Some compute nodes use redis"),
            ("elasticsearch-main", 0.4, "Some compute nodes use elasticsearch"),
            ("aws-s3", 1.0, "All compute nodes use S3"),
            ("aws-dynamodb", 0.3, "Some compute nodes use DynamoDB"),
            ("aws-sqs", 0.5, "Some compute nodes use SQS")
        ]

        # For each compute node, connect to resources based on probability
        for compute_node in self.compute_nodes:
            for resource_name, probability, _ in shared_resource_connections:
                resource_node = self.all_nodes.get(resource_name)

                if resource_node and random.random() < probability:
                    database.connect_nodes(compute_node, resource_node)

    def _create_deployment_connections(self) -> None:
        """Create a mesh of deployment-to-deployment connections via pod->deployment connections"""
        print("Creating deployment-to-deployment connections...")

        # Get all deployment nodes
        deployment_nodes = []
        for app_kebab, _ in self.app_names:
            for deployment_name in self.deployment_names[app_kebab]:
                if deployment_name in self.all_nodes:
                    deployment_nodes.append(self.all_nodes[deployment_name])

        # Create random connections between deployments (15% chance)
        connection_count = 0
        max_connections = 200

        for i, source_deployment in enumerate(deployment_nodes):
            for target_deployment in deployment_nodes[i+1:]:
                if connection_count >= max_connections:
                    break

                if random.random() < 0.15:  # 15% chance
                    # Find source pods for this deployment
                    source_pods = [node for node in self.compute_nodes 
                                  if node.node_name.startswith(source_deployment.node_name)]

                    if source_pods:
                        # Connect a random source pod to the target deployment
                        # The database module will automatically create the connection from 
                        # the parent deployment to the target deployment
                        source_pod = random.choice(source_pods)
                        database.connect_nodes(source_pod, target_deployment)
                        connection_count += 1

                        # Also create pod-to-pod connections (70% chance)
                        if random.random() < 0.7:
                            # Find target pods
                            target_pods = [node for node in self.compute_nodes 
                                          if node.node_name.startswith(target_deployment.node_name)]

                            if target_pods:
                                target_pod = random.choice(target_pods)
                                database.connect_nodes(source_pod, target_pod)

    def _create_compute_to_unknown_connections(self) -> None:
        """Connect some pods to unknown endpoints"""
        print("Creating compute-to-unknown connections...")

        # Get all unknown nodes
        unknown_nodes = [node for name, node in self.all_nodes.items() 
                        if node.node_type == NodeType.UNKNOWN]

        if not unknown_nodes:
            return

        # Connect some compute nodes to unknown nodes (10% chance)
        connection_count = 0
        max_connections = 20

        for compute_node in self.compute_nodes:
            if connection_count >= max_connections:
                break

            if random.random() < 0.1:  # 10% chance
                unknown_node = random.choice(unknown_nodes)
                database.connect_nodes(compute_node, unknown_node)
                connection_count += 1

    def _create_deployment_to_tc_connections(self) -> None:
        """Create HTTP/HTTPS traffic relationships between compute nodes and traffic controllers
        The database module will automatically create the connection from the parent deployment to the traffic controller"""
        print("Creating compute-to-traffic-controller connections...")

        # Connect compute nodes to traffic controllers of other apps (20% chance)
        connection_count = 0
        max_connections = 50

        for app_kebab, _ in self.app_names:
            # Find all compute nodes for this application
            app_compute_nodes = [node for node in self.compute_nodes if node.service_name == app_kebab]

            if not app_compute_nodes:
                continue

            for tc_node in self.tc_nodes:
                if connection_count >= max_connections:
                    break

                # Only connect to TCs of other apps
                if tc_node.service_name != app_kebab and random.random() < 0.2:  # 20% chance
                    # Connect a random compute node to the traffic controller
                    # The database module will automatically create the connection from 
                    # the parent deployment to the traffic controller
                    compute_node = random.choice(app_compute_nodes)
                    database.connect_nodes(compute_node, tc_node)
                    connection_count += 1

    def generate_data(self) -> None:
        """Generate all the data in the database"""
        try:
            print("Starting data generation...")
            self.initialize_configurations()

            # Execute data generation in sequence
            self.create_deployments()  # and computes, and traffic controllers
            self.create_resources()
            self.create_unknown_nodes()
            self.create_connections()

            print("\nData generation complete!")
            print(f"Generated {NUM_APPLICATIONS} applications")
            print(f"Generated approximately {NUM_APPLICATIONS * NUM_DEPLOYMENTS_PER_APP} deployments")
            print(f"Generated approximately {self.compute_count} compute nodes")
            print(f"Generated {self.tc_count} traffic controllers")
            print("To view the data, connect to your Neo4j browser")

        except Exception as e:
            print(f"Error during data generation: {e}")
            raise


def main():
    """Main function to run the data generator"""
    print("Neo4j Data Generator for Network Topology")

    # Print configuration
    print("\nConfiguration:")
    print(f"Number of applications: {NUM_APPLICATIONS}")
    print(f"Number of deployments per application: {NUM_DEPLOYMENTS_PER_APP}")
    print(f"Number of computes per deployment: {NUM_COMPUTES_PER_DEPLOYMENT}")
    print(f"Deployments have canaries: {DEPLOYMENTS_HAVE_CANARIES}")
    print(f"Multi-cluster deployments: {MULTI_CLUSTER_DEPLOYMENTS}")
    print(f"Number of EKS clusters: {NUM_EKS_CLUSTERS}")
    print(f"Number of AWS VPCs: {NUM_AWS_VPCS}")
    print(f"Number of public IP nodes: {NUM_PUBLIC_IP_NODES}")
    print(f"Percentage of nodes with unknown cluster: {PERCENT_UNKNOWN_CLUSTER}%")

    generator = AstrolabeDataGenerator()
    generator.generate_data()
    generator.close()


if __name__ == "__main__":
    exit(main())
