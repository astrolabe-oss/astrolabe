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
from neo4j import GraphDatabase

# Load environment variables from .env file if it exists
load_dotenv()

# Neo4j connection settings
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

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


class Neo4jDataGenerator:
    """Class for generating and inserting network topology data into Neo4j"""

    def __init__(self, uri: str, username: str, password: str):
        """Initialize the Neo4j connection"""
        self.driver = GraphDatabase.driver(uri, auth=(username, password))
        self.app_names = []
        self.deployment_names = {}
        self.cluster_names = []
        self.vpc_names = []
        self.resource_names = []
        # Statistics for compute nodes creation
        self.compute_count = 0
        self.public_ips_assigned = 0
        self.unknown_clusters_assigned = 0
        self.compute_queries = []
        # Statistics for traffic controller creation
        self.tc_count = 0
        self.tc_queries = []

    def close(self) -> None:
        """Close the Neo4j connection"""
        self.driver.close()

    def run_query(self, query: str, params: Optional[Dict[str, Any]] = None) -> None:
        """Execute a Cypher query with parameters"""
        with self.driver.session() as session:
            try:
                session.run(query, params or {})
            except Exception as e:
                print(f"Error executing query: {e}")
                print(f"Query was: {query}")
                raise

    def run_queries(self, queries: List[str], params: Optional[Dict[str, Any]] = None) -> None:
        """Execute multiple Cypher queries separately"""
        for query in queries:
            if query.strip():  # Skip empty queries
                self.run_query(query, params)

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

    def initialize_data(self) -> None:
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

    def create_applications(self) -> None:
        """Create Application nodes"""
        print("Creating applications...")
        queries = []

        for i, (kebab_name, camel_name) in enumerate(self.app_names):
            provider = "k8s" if i < NUM_APPLICATIONS * 0.8 else "aws"  # 80% k8s, 20% aws
            timestamp = self.generate_timestamps()

            query = f"""
            CREATE (app{i}:Application {{
                name: "{camel_name}", 
                profile_timestamp: {timestamp}, 
                profile_warnings: "{{}}", 
                profile_errors: "{{}}", 
                profile_strategy_name: "Inventory", 
                provider: "{provider}", 
                app_name: "{kebab_name}"
            }})
            """
            queries.append(query)

        self.run_queries(queries)
        print(f"Created {NUM_APPLICATIONS} applications")

    def create_deployments(self) -> None:
        """Create Deployment nodes and connect them to Applications"""
        print("Creating deployments...")
        queries = []

        # Calculate how many compute nodes should have unknown clusters
        total_computes = sum(len(deployments) * NUM_COMPUTES_PER_DEPLOYMENT
                           for deployments in self.deployment_names.values())
        unknown_cluster_target = int(total_computes * PERCENT_UNKNOWN_CLUSTER / 100)
    
        # Reset compute node and traffic controller statistics
        self.compute_count = 0
        self.public_ips_assigned = 0
        self.unknown_clusters_assigned = 0
        self.compute_queries = []
        self.tc_count = 0
        self.tc_queries = []
    
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
                protocol = "TCP"
                protocol_multiplexor = str(random.randint(30000, 32767))
                timestamp = self.generate_timestamps()
    
                # Create deployment node
                create_query = f"""
                CREATE (deploy{deployment_count}:Deployment {{
                    name: "{deployment_name}", 
                    address: "{address}", 
                    protocol: "{protocol}", 
                    protocol_multiplexor: "{protocol_multiplexor}", 
                    public_ip: false, 
                    cluster: "{cluster}", 
                    deployment_type: "k8s_deployment", 
                    profile_timestamp: {timestamp}, 
                    profile_warnings: "{{}}", 
                    profile_errors: "{{}}", 
                    profile_strategy_name: "Inventory", 
                    provider: "k8s", 
                    app_name: "{kebab_name}"
                }})
                """
                queries.append(create_query)
    
                # Create the IMPLEMENTED_BY relationship - separate query
                relationship_query = f"""
                MATCH (app:Application {{app_name: "{kebab_name}"}}), (deploy:Deployment {{name: "{deployment_name}"}})
                CREATE (app)-[:IMPLEMENTED_BY]->(deploy)
                """
                queries.append(relationship_query)
    
                # Create compute nodes for this deployment
                for pod_index in range(NUM_COMPUTES_PER_DEPLOYMENT):
                    self._create_compute_node(
                        app_kebab=kebab_name,
                        deployment_name=deployment_name,
                        cluster=cluster,
                        pod_index=pod_index,
                        unknown_cluster_target=unknown_cluster_target
                    )
                
                # Create traffic controller if this is a main deployment
                if "main" in deployment_name:
                    self._create_traffic_controller(
                        app_kebab=kebab_name,
                        deployment_name=deployment_name,
                        cluster=cluster
                    )
    
                deployment_count += 1
    
        # Run queries to create deployments and their relationships
        self.run_queries(queries)
        print(f"Created {deployment_count} deployments and connected them to applications")
    
        # Run queries to create compute nodes and their relationships
        if self.compute_queries:
            self.run_queries(self.compute_queries)
            print(f"Created {self.compute_count} compute nodes with {self.public_ips_assigned} public IPs")
            print(f"Assigned {self.unknown_clusters_assigned} compute nodes to unknown clusters")
        
        # Run queries to create traffic controllers and their relationships
        if self.tc_queries:
            self.run_queries(self.tc_queries)
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
    
        timestamp = self.generate_timestamps()
    
        # Create compute node
        create_query = f"""
        CREATE (comp{self.compute_count}:Compute {{
            name: "{pod_name}", 
            address: "{address}", 
            protocol: "TCP", 
            protocol_multiplexor: "8080", 
            public_ip: {str(has_public_ip).lower()}, 
            cluster: "{pod_cluster}", 
            profile_timestamp: {timestamp}, 
            profile_warnings: "{{}}", 
            profile_errors: "{{}}", 
            profile_strategy_name: "Inventory", 
            provider: "k8s", 
            app_name: "{app_kebab}", 
            platform: "k8s"
        }})
        """
        self.compute_queries.append(create_query)
    
        # Create the HAS_MEMBER relationship
        relationship_query = f"""
        MATCH (deploy:Deployment {{name: "{deployment_name}"}}), (comp:Compute {{name: "{pod_name}"}})
        CREATE (deploy)-[:HAS_MEMBER]->(comp)
        """
        self.compute_queries.append(relationship_query)
    
        self.compute_count += 1
    
    def create_compute_nodes(self) -> None:
        """Initialize compute node creation and execute queries"""
        print("Creating compute nodes...")
        self.compute_count = 0
        self.public_ips_assigned = 0
        self.unknown_clusters_assigned = 0
        self.compute_queries = []
    
        # Calculate how many compute nodes should have unknown clusters
        total_computes = sum(len(deployments) * NUM_COMPUTES_PER_DEPLOYMENT
                            for deployments in self.deployment_names.values())
        unknown_cluster_target = int(total_computes * PERCENT_UNKNOWN_CLUSTER / 100)
    
        # Execute the compute node queries
        if self.compute_queries:
            self.run_queries(self.compute_queries)
            print(f"Created {self.compute_count} compute nodes with {self.public_ips_assigned} public IPs")
            print(f"Assigned {self.unknown_clusters_assigned} compute nodes to unknown clusters")
        else:
            print("No compute nodes created - ensure deployments create their compute nodes")

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

        timestamp = self.generate_timestamps()

        # Create traffic controller node
        create_query = f"""
        CREATE (tc{self.tc_count}:TrafficController {{
            name: "{tc_name}", 
            address: "{address}", 
            protocol: "TCP", 
            protocol_multiplexor: "80", 
            public_ip: false, 
            dns_names: ["{dns_name}"], 
            cluster: "{cluster}", 
            profile_timestamp: {timestamp}, 
            profile_warnings: "{{}}", 
            profile_errors: "{{}}", 
            profile_strategy_name: "Inventory", 
            provider: "k8s", 
            app_name: "{app_kebab}"
        }})
        """
        self.tc_queries.append(create_query)

        # Create FORWARDS_TO relationships between TrafficControllers and Deployments
        # Main deployment gets full traffic
        main_route_query = f"""
        MATCH (tc:TrafficController {{name: "{tc_name}"}}), (deploy:Deployment {{name: "{deployment_name}"}})
        CREATE (tc)-[:FORWARDS_TO]->(deploy)
        """
        self.tc_queries.append(main_route_query)

        # Canary deployment gets partial traffic if it exists
        canary_name = deployment_name.replace("main", "canary")
        if canary_name in self.deployment_names[app_kebab]:
            weight = round(random.uniform(0.1, 0.3), 1)  # Random weight between 0.1 and 0.3
            canary_route_query = f"""
            MATCH (tc:TrafficController {{name: "{tc_name}"}}), (deploy:Deployment {{name: "{canary_name}"}})
            CREATE (tc)-[:FORWARDS_TO {{weight: {weight}}}]->(deploy)
            """
            self.tc_queries.append(canary_route_query)

        self.tc_count += 1

    def create_resources(self) -> None:
        """Create Resource nodes for external services and databases"""
        print("Creating resources...")
        queries = []

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

        # Create standard resources in a loop
        for i, resource in enumerate(standard_resources):
            dns_names_str = ", ".join([f'"{dns}"' for dns in resource["dns_names"]])

            timestamp = self.generate_timestamps()
            query = f"""
            CREATE (res{i + 1}:Resource {{
                name: "{resource['name']}", 
                address: "{resource['address']}", 
                dns_names: [{dns_names_str}], 
                protocol: "TCP", 
                protocol_multiplexor: "{resource['protocol_multiplexor']}", 
                public_ip: {str(resource['public_ip']).lower()}, 
                cluster: "{resource['cluster']}", 
                profile_timestamp: {timestamp}, 
                profile_warnings: "{{}}", 
                profile_errors: "{{}}", 
                profile_strategy_name: "Inventory", 
                provider: "{resource['provider']}"
            }})
            """
            queries.append(query)

        # Create app-specific cache resources
        resource_count = len(standard_resources) + 1  # Starting after the standard resources
        for app_kebab, _ in self.app_names:
            cache_name = f"{app_kebab}-cache"

            timestamp = self.generate_timestamps()
            query = f"""
            CREATE (res{resource_count}:Resource {{
                name: "{cache_name}",
                address: "{cache_name}.internal",
                dns_names: ["{cache_name}.internal"],
                protocol: "TCP",
                protocol_multiplexor: "6379",
                public_ip: false,
                cluster: "shared-services",
                profile_timestamp: {timestamp},
                profile_warnings: "{{}}",
                profile_errors: "{{}}",
                profile_strategy_name: "Inventory",
                provider: "k8s"
            }})
            """
            queries.append(query)

            resource_count += 1

        self.run_queries(queries)
        print(f"Created {resource_count - 1} resources")

    def create_unknown_nodes(self) -> None:
        """Create Unknown nodes for endpoints that can't be identified"""
        print("Creating unknown nodes...")
        queries = []
        
        # Create a few unknown nodes
        for i in range(5):
            timestamp = self.generate_timestamps()
            query = f"""
            CREATE (unk{i}:Unknown {{
                name: "unknown-endpoint-{i+1}",
                address: "unknown-endpoint-{i+1}",
                profile_timestamp: {timestamp},
                profile_warnings: "{{}}", 
                profile_errors: "{{}}", 
                profile_strategy_name: "Inventory",
                cluster: "unknown",
                provider: "ssh"
            }})
            """
            queries.append(query)
        
        self.run_queries(queries)
        print("Created 5 unknown nodes")

    def create_connections(self) -> None:
        """Create connections between nodes (CALLS, CONNECTS_TO relationships)"""
        print("Creating connections between nodes...")

        # Define app-specific resource connections
        self._create_app_specific_resource_connections()

        # Define shared resource connections with their patterns
        shared_resource_connections = [
            # format: (resource_name, probability, description)
            ("postgres-main", 1.0, "All deployments use postgres"),
            ("redis-main", 0.6, "Some deployments use redis"),
            ("elasticsearch-main", 0.4, "Some deployments use elasticsearch"),
            ("aws-s3", 1.0, "All deployments use S3"),
            ("aws-dynamodb", 0.3, "Some deployments use DynamoDB"),
            ("aws-sqs", 0.5, "Some deployments use SQS")
        ]

        # Create all shared resource connections
        self._create_shared_resource_connections(shared_resource_connections)

        # Define other node-to-node connection patterns
        node_connection_patterns = [
            # Format: (source_label, target_label, relationship_type, match_conditions, probability, limit, props, description)
            ("Deployment", "Deployment", "CALLS", "source.name <> target.name AND NOT EXISTS((source)-[:CALLS]->(target))",
             0.15, 200, {}, "Create a mesh of deployment connections"),

            ("deploy1", "deploy2", "CALLS", "deploy1-[:CALLS]->deploy2, deploy1-[:HAS_MEMBER]->pod1, deploy2-[:HAS_MEMBER]->pod2",
             0.7, None, {}, "Create pod-to-pod connections based on deployment connections"),

            ("Compute", "Unknown", "CALLS", "source.platform = 'k8s'",
             0.1, 20, {}, "Connect some pods to unknown endpoints"),
        
            ("Deployment", "TrafficController", "CALLS", "source.app_name <> target.app_name",
             0.2, 50, {"protocol": "HTTP", "port": 80}, "Create HTTP/HTTPS traffic relationships")
        ]

        # Create all node-to-node connections
        for pattern in node_connection_patterns:
            self._create_node_connections(*pattern)

        print("Finished creating connections between nodes")

    def _create_app_specific_resource_connections(self) -> None:
        """Create connections from deployments to their app-specific resources like caches"""
        queries = []

        for app_kebab, _ in self.app_names:
            cache_name = f"{app_kebab}-cache"

            for deployment_name in self.deployment_names[app_kebab]:
                query = f"""
                MATCH (deploy:Deployment {{name: "{deployment_name}"}}), (res:Resource {{name: "{cache_name}"}})
                CREATE (deploy)-[:CALLS]->(res)
                """
                queries.append(query)

        self.run_queries(queries)
        print("Created app-specific resource connections")

    def _create_shared_resource_connections(self, resource_patterns) -> None:
        """
        Create connections to shared resources based on defined patterns

        Args:
            resource_patterns: List of tuples (resource_name, probability, description)
        """
        queries = []

        for resource_name, probability, description in resource_patterns:
            query = f"""
            // {description}
            MATCH (deploy:Deployment), (res:Resource {{name: "{resource_name}"}})
            """

            # Add probability condition if it's not 100%
            if probability < 1.0:
                query += f"WHERE rand() < {probability}  // {int(probability * 100)}% chance\n"

            query += "CREATE (deploy)-[:CALLS]->(res)"
            queries.append(query)

        self.run_queries(queries)
        print(f"Created connections to {len(resource_patterns)} shared resources")

    def _create_node_connections(self, source_label, target_label, relationship_type,
                                match_conditions, probability, limit, properties, description) -> None:
        """
        Create connections between nodes based on defined patterns

        Args:
            source_label: Label of the source node
            target_label: Label of the target node
            relationship_type: Type of relationship to create
            match_conditions: Additional match conditions
            probability: Probability of creating the connection
            limit: Limit the number of connections
            properties: Properties to add to the relationship
            description: Description of the connection pattern
        """
        # Special case for pod-to-pod connections which has a more complex match pattern
        if source_label == "deploy1" and target_label == "deploy2":
            query = f"""
            // {description}
            MATCH (deploy1)-[:CALLS]->(deploy2),
                  (deploy1)-[:HAS_MEMBER]->(pod1),
                  (deploy2)-[:HAS_MEMBER]->(pod2)
            WHERE rand() < {probability}  // {int(probability * 100)}% chance
            """
            
            if limit:
                query += f"WITH pod1, pod2 LIMIT {limit}\n"
                
            query += "CREATE (pod1)-[:CALLS]->(pod2)"
            
        else:
            # Standard node-to-node connections
            query = f"""
            // {description}
            MATCH (source:{source_label}), (target:{target_label})
            WHERE source <> target AND rand() < {probability}  // {int(probability * 100)}% chance
            """

            if match_conditions:
                # Replace 'source' and 'target' with actual variable names in the condition
                condition = match_conditions.replace("source", "source").replace("target", "target")
                query += f"AND {condition}\n"

            if limit:
                query += f"WITH source, target LIMIT {limit}\n"

            # Add properties to the relationship if specified
            if properties:
                props_str = ", ".join([f"{k}: '{v}'" if isinstance(v, str) else f"{k}: {v}"
                                     for k, v in properties.items()])
                query += f"CREATE (source)-[:{relationship_type} {{{props_str}}}]->(target)"
            else:
                query += f"CREATE (source)-[:{relationship_type}]->(target)"

        self.run_query(query)
        print(f"Created {relationship_type} connections from {source_label} to {target_label}")

    def generate_data(self) -> None:
        """Generate all the data in the database"""
        try:
            print("Starting data generation...")
            self.initialize_data()
            
            # Execute data generation in sequence
            self.create_applications()
            self.create_deployments()
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
    print(f"Connecting to Neo4j at {NEO4J_URI}...")
    
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
    
    try:
        generator = Neo4jDataGenerator(NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD)
        generator.generate_data()
        generator.close()
    except Exception as e:
        print(f"Fatal error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
