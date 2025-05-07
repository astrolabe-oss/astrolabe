"""
Module Name: provider_k8s

Description:
Provider for nodes in kubernetes cluster - relies on local kubectl setup and configured to connect to k8s cluster.

Assumptions:
- All services are in 1 and only 1 kubernetes cluster
- This 1 and only 1 kubernetes cluster is currently configured and authenticated as the active context in kubectl
- Services in kubernetes cluster can be identified by name with a user configured kubernetes label


License:
SPDX-License-Identifier: Apache-2.0
"""
import asyncio
import sys
import re
from typing import Dict, List, Optional, Union

from kubernetes_asyncio import client, config
from kubernetes_asyncio.stream import WsApiClient
from kubernetes_asyncio.client.rest import ApiException
from kubernetes_asyncio.client.models import V1PodList, V1ServiceList, V1Pod, V1Service
from termcolor import colored

from astrolabe import database, constants, logs
from astrolabe.network import Hint, get_protocol, PROTOCOL_TCP
from astrolabe.node import NodeTransport, NodeType, Node, create_node
from astrolabe.profile_strategy import ProfileStrategy, INVENTORY_PROFILE_STRATEGY_NAME, HINT_PROFILE_STRATEGY_NAME
from astrolabe.providers import ProviderInterface, parse_profile_strategy_response
from astrolabe.plugin_core import PluginArgParser

pod_cache: Dict[str, client.models.V1Pod] = {}


class ProviderKubernetes(ProviderInterface):
    def __init__(self):
        self.api: client.CoreV1Api
        self.ws_api: client.CoreV1Api
        self.cluster_name: Optional[str] = None

    async def init_async(self):
        await config.load_kube_config()
        self.api = client.CoreV1Api()
        self.ws_api = client.CoreV1Api(WsApiClient(configuration=client.configuration.Configuration.get_default()))
        self.cluster_name = self._get_cluster_name()

    def _get_cluster_name(self) -> Optional[str]:
        """
        Get the cluster name from the current Kubernetes context.
        If the cluster name is formatted like an AWS ARN, extract everything after the last "/".

        :return: The cluster name or None if it can't be determined
        """
        _, active_context = config.list_kube_config_contexts()
        if active_context and 'name' in active_context:
            cluster_name = active_context['name']
            # Check if it's an AWS ARN format
            if cluster_name.startswith('arn:aws:eks:'):
                # Extract everything after the last "/"
                match = re.search(r'/([^/]+)$', cluster_name)
                if match:
                    return match.group(1)
            return cluster_name
        return None

    async def inventory(self):
        await self._inventory_services()

    async def del_async(self):
        await self.api.api_client.rest_client.close()
        await self.ws_api.api_client.rest_client.close()

    @staticmethod
    def ref() -> str:
        return 'k8s'

    @staticmethod
    def register_cli_args(argparser: PluginArgParser):
        argparser.add_argument('--skip-containers', nargs='*', default=[], metavar='CONTAINER',
                               help='Ignore containers (uses substring matching)')
        argparser.add_argument('--label-selectors', nargs='*', metavar='SELECTOR',
                               help='Additional labels to filter services by in k8s.  '
                                    'Specified in format "LABEL_NAME=VALUE" pairs')
        argparser.add_argument('--app-name-label', metavar='LABEL', help='k8s label associated with app name')
        argparser.add_argument('--exclude-namespaces', nargs='*', default=[], metavar='EXCLUDE_NAMESPACES',
                               help='Additional namespaces to exclude from discovery')

    @staticmethod
    def is_container_platform() -> bool:
        return True

    def cluster(self) -> Optional[str]:
        return self.cluster_name

    async def lookup_name(self, address: str, _: Optional[type]) -> Optional[str]:
        # k8s pod service name
        pod = await self._get_pod(address)
        if not pod:
            return

        app_name_label = constants.ARGS.k8s_app_name_label
        if app_name_label in pod.metadata.labels:
            return pod.metadata.labels[app_name_label]

        return None

    async def sidecar(self, address: str, _: Optional[type]) -> None:
        logs.logger.debug("Running sidecars for address %s", address)
        await self._sidecar_lookup_hostnames(address)

    async def _sidecar_lookup_hostnames(self, address: str) -> None:
        """we are cheating! for every instance we ssh into, we are going to try a name lookup
           to get the DNS names for anything in the astrolabe DNS Cache that we don't yet have
           """
        asyncio_tasks = []
        for hostname, node in database.get_nodes_pending_dnslookup():
            asyncio_tasks.append(self._sidecar_lookup_hostname(address, hostname, node))
        await asyncio.gather(*asyncio_tasks)

    async def _sidecar_lookup_hostname(self, address: str, hostname: str, node: Node):
        sidecar_command = f"getent hosts {hostname} | awk '{{print $1}}'"
        logs.logger.debug(f"Running sidecar command: {sidecar_command} for address %s", address)
        exec_command = ['sh', '-c', sidecar_command]
        pod = await self._get_pod(address)
        if not pod:
            return

        pod_namespace = pod.metadata.namespace
        containers = pod.spec.containers
        containers = [c for c in containers if True not in
                      [skip in c.name for skip in constants.ARGS.k8s_skip_containers]]
        for container in containers:
            # IDE inspection doesn't think that this coroutine is async/awaitable, but it is
            ret = await self.ws_api.connect_get_namespaced_pod_exec(address, pod_namespace,
                                                                    container=container.name, command=exec_command,
                                                                    stderr=True, stdin=False, stdout=True, tty=False)
            ip_addrs = ret.strip().split('\n') if ret else None
            logs.logger.info("Found ipaddrs: [%s] for hostname %s on host %s", ",".join(ip_addrs), hostname, address)
            for ip_addr in ip_addrs:
                if ip_addr and database.get_node_by_address(ip_addr) is None:
                    node.address = ip_addr
                    node.ipaddrs = (node.ipaddrs or []) + [ip_addr]
                    database.save_node(node)

    async def profile(self, node: Node, pfss: List[ProfileStrategy], _: Optional[type]) -> List[NodeTransport]:
        # profile k8s service load balancer
        if database.node_is_k8s_load_balancer(node.address):
            # k8s lbs are pre-profiled during inventory
            logs.logger.debug("Profile of k8s load balancer (%s) requested "
                              "and skipped due to pre-profiling during inventory", node.address)
            return []

        # profile k8s service
        if database.node_is_k8s_service(node.address):
            logs.logger.debug("Profiling address %s as k8s service", node.address)
            return await self._profile_k8s_service(node.node_name)

        # profile pod
        logs.logger.debug("Profiling address %s as k8s pod", node.address)
        return await self._profile_pod(node.address, pfss)

    async def _profile_k8s_service(self, svc_name: str) -> List[NodeTransport]:
        # k8s_service_pfs = profile_strategy.
        try:
            # Filter by service name directly in the API call
            services = await self.api.list_service_for_all_namespaces(field_selector=f"metadata.name={svc_name}")
            services = _filter_excluded_namespaces(services)
            if 0 == len(services):
                return []

            # We are assuming that there is only one service in any namespace and just taking the first one here
            service = services[0]
            selector = service.spec.selector
            namespace = service.metadata.namespace
            if not selector:
                return []

            label_selector = ",".join([f"{key}={value}" for key, value in selector.items()])
            pods = await self.api.list_namespaced_pod(namespace=namespace,
                                                      label_selector=label_selector)

            node_transports = []
            for pod in pods.items:
                node_transport = NodeTransport(
                    address=pod.metadata.name,
                    protocol=get_protocol('TCP'),
                    protocol_mux=service.spec.ports[0].target_port,
                    profile_strategy_name='_profile_k8s_service',
                    provider='k8s',
                    from_hint=False,
                    node_type=NodeType(NodeType.COMPUTE)
                )
                node_transports.append(node_transport)
                logs.logger.debug("Found %d profile results for %s, profile strategy: \"%s\"..",
                                  len(node_transports), svc_name, '_profile_k8s_service')
            return node_transports

        except ApiException as exc:
            print(f"Exception when calling CoreV1Api: {exc}")
            return []

    async def _profile_pod(self, address: str, pfss: List[ProfileStrategy]) -> List[NodeTransport]:
        node_transports = []
        for pfs in pfss:
            shell_command = pfs.provider_args['shell_command']
            exec_command = ['bash', '-c', shell_command]
            pod = await self._get_pod(address)
            if not pod:
                return []

            pod_namespace = pod.metadata.namespace
            containers = pod.spec.containers
            containers = [c for c in containers if True not in
                          [skip in c.name for skip in constants.ARGS.k8s_skip_containers]]

            for container in containers:
                ret = await self.ws_api.connect_get_namespaced_pod_exec(address, pod_namespace,
                                                                        container=container.name, command=exec_command,
                                                                        stderr=True, stdin=False, stdout=True,
                                                                        tty=False)
                profiled_nts = parse_profile_strategy_response(ret, address, pfs)
                node_transports.extend(profiled_nts)
        return node_transports

    async def take_a_hint(self, hint: Hint) -> List[NodeTransport]:
        label_selector = _parse_label_selector(hint.service_name)
        all_pods = await self.api.list_pod_for_all_namespaces(limit=1, label_selector=label_selector)
        filtered_pods = _filter_excluded_namespaces(all_pods)

        try:
            pod = filtered_pods[0]
            address = pod.metadata.name
        except IndexError:
            print(colored(f"Unable to take a hint, no instance in k8s cluster: "
                          f"{config.list_kube_config_contexts()[1]} for hint:", 'red'))
            print(colored(hint, 'yellow'))
            sys.exit(1)

        return [NodeTransport(
            profile_strategy_name=HINT_PROFILE_STRATEGY_NAME,
            provider=hint.provider,
            protocol=hint.protocol,
            protocol_mux=hint.protocol_mux,
            address=address,
            debug_identifier=hint.service_name
        )]

    async def _get_pod(self, pod_name: str) -> Optional[client.models.V1Pod]:
        """
        Get the pod from kubernetes API, with caching

        :param pod_name:
        :return:
        """
        if pod_name in pod_cache:
            return pod_cache[pod_name]

        try:
            pods = await self.api.list_pod_for_all_namespaces(field_selector=f"metadata.name={pod_name}")
            filtered_pods = _filter_excluded_namespaces(pods)

            if not filtered_pods:
                logs.logger.debug("Cannot find pod %s in any non-excluded namespace", pod_name)
                return None

            pod = filtered_pods[0]
        except ApiException as exc:
            logs.logger.debug("Cannot find pod %s w/ ApiException(%s:%s)", pod_name, exc.status, exc.reason)
            return None

        return pod

    async def _inventory_services(self):
        """
        Inventory all services in the cluster and cache their DNS names and service names.
        """
        services = await self.api.list_service_for_all_namespaces(watch=False)
        for svc in services.items:
            if svc.spec.type == "LoadBalancer" and svc.status.load_balancer.ingress:
                ports = svc.spec.ports[0]
                ingress = svc.status.load_balancer.ingress
                lb_address = ingress[0].hostname or ingress[0].ip
                k8s_service_address = svc.spec.cluster_ip
                k8s_service_name = svc.metadata.name
                if svc.spec.selector and constants.ARGS.k8s_app_name_label in svc.spec.selector:
                    k8s_service_app_name = svc.spec.selector[constants.ARGS.k8s_app_name_label]
                else:
                    logs.logger.error("k8s service %s does not have configured k8s service name "
                                      "selector: %s", k8s_service_address, constants.ARGS.k8s_app_name_label)
                    k8s_service_app_name = None
                k8s_service_node = Node(
                    address=k8s_service_address,
                    node_name=k8s_service_name,
                    node_type=NodeType.DEPLOYMENT,
                    profile_strategy_name=INVENTORY_PROFILE_STRATEGY_NAME,
                    protocol=PROTOCOL_TCP,
                    protocol_mux=ports.node_port,
                    provider='k8s',
                    service_name=k8s_service_app_name,
                    cluster=self.cluster_name,
                    containerized=True
                )
                lb_node = Node(
                    node_type=NodeType.TRAFFIC_CONTROLLER,
                    node_name=k8s_service_name,
                    profile_strategy_name=INVENTORY_PROFILE_STRATEGY_NAME,
                    provider='k8s',
                    protocol=PROTOCOL_TCP,
                    protocol_mux=ports.port,
                    service_name=k8s_service_app_name,
                    aliases=[lb_address],
                    cluster=self.cluster_name,
                    containerized=True
                )
                database.save_node(k8s_service_node)
                database.save_node(lb_node)
                database.connect_nodes(lb_node, k8s_service_node)
                logs.logger.info("Inventoried 1 k8s service node: %s", k8s_service_node.debug_id())
                logs.logger.info("Inventoried 1 k8s load balancer node: %s", lb_node.debug_id())
                logs.logger.info("Profiling k8s load balancer node: %s", lb_node.debug_id())
                pod_nts = await self._profile_k8s_service(k8s_service_name)
                for pod_nt in pod_nts:
                    _, pod_node = create_node(pod_nt, self)
                    pod_node.set_profile_timestamp()
                    database.save_node(pod_node)
                    database.connect_nodes(k8s_service_node, pod_node)
                    logs.logger.info("Inventoried pods: %s for service: %s", pod_node.node_name, lb_node.debug_id())


def _parse_label_selector(service_name: str) -> str:
    """Generate a label selector to pass to the k8s api from service name and CLI args
    :param service_name: the service name
    """
    label_name_pos = 0
    label_value_pos = 1
    label_selector_pairs = {constants.ARGS.k8s_app_name_label: service_name}
    for label, value in [(selector.split('=')[label_name_pos], selector.split('=')[label_value_pos])
                         for selector in constants.ARGS.k8s_label_selectors]:
        label_selector_pairs[label] = value
    return ','.join(f"{label}={value}" for label, value in label_selector_pairs.items())


def _filter_excluded_namespaces(k8s_resources: Union[V1PodList, V1ServiceList]) -> List[Union[V1Pod, V1Service]]:
    # Default system namespaces to exclude from discovery
    default_exclude_namespaces = [
        # Core Kubernetes system namespaces
        "kube-system",  # Contains core Kubernetes components like kube-proxy, CoreDNS, etc.
        "kube-public",  # Contains publicly accessible data
        "kube-node-lease",  # Contains node heartbeat information

        # Service mesh namespaces
        "istio-system",  # Istio service mesh components
        "linkerd",  # Linkerd service mesh components
        "consul",  # Consul service mesh and service discovery

        # Monitoring and observability namespaces
        "monitoring",  # General monitoring namespace (often used by Prometheus stack)
        "prometheus",  # Prometheus monitoring specific namespace
        "grafana",  # Grafana dashboards
        "metrics-server",  # Kubernetes metrics collection
        "elastic-system",  # Elasticsearch, Logstash, Kibana (ELK stack)
        "logging",  # General logging infrastructure
        "loki",  # Loki logging system
        "datadog",  # Datadog monitoring agent and components
        "newrelic",  # New Relic monitoring components

        # Certificate and security namespaces
        "cert-manager",  # Certificate management for Kubernetes
        "vault",  # HashiCorp Vault for secrets management
        "security",  # General security tools

        # Ingress controllers
        "ingress-nginx",  # NGINX ingress controller
        "nginx-ingress",  # Alternative namespace for NGINX ingress
        "traefik",  # Traefik ingress controller
        "kong",  # Kong API gateway

        # Serverless/Function-as-a-Service
        "knative-serving",  # Knative serving components
        "openfaas",  # OpenFaaS serverless framework
        "kubeless",  # Kubeless serverless framework

        # Container registry
        "harbor",  # Harbor container registry

        # Operators and controllers
        "operators",  # General operators namespace
        "tekton-pipelines",  # Tekton CI/CD pipelines
        "argo",  # Argo Workflows and CD
        "argocd",  # ArgoCD GitOps
        "flux-system"  # Flux GitOps
    ]

    exclude_namespaces = default_exclude_namespaces + constants.ARGS.k8s_exclude_namespaces
    nonexcluded_resources = [s for s in k8s_resources.items if s.metadata.namespace not in exclude_namespaces]

    return nonexcluded_resources
