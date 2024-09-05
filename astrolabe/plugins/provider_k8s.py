"""
Module Name: provider_k8s

Description:
Provider for nodes in kubernetes cluster - relies on local kubectl setup and configured to connect to k8s cluster.

Assumptions:
- All services are in 1 and only 1 kubernetes cluster
- This 1 and only 1 kubernetes cluster is currently configured and authenticated as the active context in kubectl
- Services in kubernetes cluster can be identified by name with a user configured kubernetes label

Copyright:
Copyright 2024 Magellanbot, Inc

License:
SPDX-License-Identifier: Apache-2.0
"""
import asyncio
import sys
from typing import Dict, List, Optional

from kubernetes_asyncio import client, config
from kubernetes_asyncio.stream import WsApiClient
from kubernetes_asyncio.client.rest import ApiException
from termcolor import colored

from astrolabe import database, constants, logs
from astrolabe.network import Hint
from astrolabe.node import NodeTransport, NodeType, Node
from astrolabe.profile_strategy import ProfileStrategy, INVENTORY_PROFILE_STRATEGY
from astrolabe.providers import ProviderInterface, parse_profile_strategy_response
from astrolabe.plugin_core import PluginArgParser

pod_cache: Dict[str, client.models.V1Pod] = {}


class ProviderKubernetes(ProviderInterface):
    def __init__(self):
        self.api: client.CoreV1Api
        self.ws_api: client.CoreV1Api

    async def init_async(self):
        await config.load_kube_config()
        self.api = client.CoreV1Api()
        self.ws_api = client.CoreV1Api(WsApiClient(configuration=client.configuration.Configuration.get_default()))
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
        argparser.add_argument('--namespace', required=True, help='k8s Namespace in which to discover services')
        argparser.add_argument('--label-selectors', nargs='*', metavar='SELECTOR',
                               help='Additional labels to filter services by in k8s.  '
                                    'Specified in format "LABEL_NAME=VALUE" pairs')
        argparser.add_argument('--service-name-label', metavar='LABEL', help='k8s label associated with service name')

    @staticmethod
    def is_container_platform() -> bool:
        return True

    async def lookup_name(self, address: str, _: Optional[type]) -> Optional[str]:
        # k8s pod service name
        pod = await self._get_pod(address)
        if not pod:
            return

        service_name_label = 'app'
        if service_name_label in pod.metadata.labels:
            return pod.metadata.labels[service_name_label]

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

        containers = pod.spec.containers
        containers = [c for c in containers if True not in
                      [skip in c.name for skip in constants.ARGS.k8s_skip_containers]]
        for container in containers:
            # IDE inspection doesn't think that this coroutine is async/awaitable, but it is
            ret = await self.ws_api.connect_get_namespaced_pod_exec(address, constants.ARGS.k8s_namespace,
                                                                    container=container.name, command=exec_command,
                                                                    stderr=True, stdin=False, stdout=True, tty=False)
            ip_addrs = ret.strip().split('\n') if ret else None
            for ip_addr in ip_addrs:
                if ip_addr and database.get_node_by_address(ip_addr) is None:
                    logs.logger.debug("Discovered IP %s for hostname %s: from address %s",
                                      ip_addr, hostname, address)
                    # TODO: we are glossing over the fact that there can multiple addresses per
                    #  node for DNS records here!  Solve that problem later!
                    node.address = ip_addr
                    database.save_node(node)

    async def profile(self, address: str, pfs: ProfileStrategy, _: Optional[type]) -> List[NodeTransport]:
        # profile k8s service load balancer
        if database.node_is_k8s_load_balancer(address):
            # k8s lbs are pre-profiled during inventory
            logs.logger.debug("Profile of k8s load balancer (%s) requested "
                              "and skipped due to pre-profiling during inventory", address)
            return []

        # profile k8s service
        if database.node_is_k8s_service(address):
            logs.logger.debug("Profiling address %s as k8s service", address)
            return await self._profile_k8s_service(address)

        # profile pod
        logs.logger.debug("Profiling address %s as k8s pod", address)
        return await self._profile_pod(address, pfs)

    async def _profile_k8s_service(self, address: str) -> List[NodeTransport]:
        try:
            service = await self.api.read_namespaced_service(address, namespace="default")
            selector = service.spec.selector
            if not selector:
                return []

            label_selector = ",".join([f"{key}={value}" for key, value in selector.items()])
            pods = await self.api.list_namespaced_pod(namespace="default", label_selector=label_selector)

            node_transports = []
            for pod in pods.items:
                ret = "address mux\n"
                ret += f"{pod.metadata.name} {service.spec.ports[0].target_port}\n"
                node_transports.extend(parse_profile_strategy_response(ret, address, '_profile_k8s_service'))
            return node_transports

        except ApiException as exc:
            print(f"Exception when calling CoreV1Api: {exc}")
            return []

    async def _profile_pod(self, address: str, pfs: ProfileStrategy) -> List[NodeTransport]:
        shell_command = pfs.provider_args['shell_command']
        exec_command = ['bash', '-c', shell_command]
        pod = await self._get_pod(address)
        if not pod:
            return []

        containers = pod.spec.containers
        containers = [c for c in containers if True not in
                      [skip in c.name for skip in constants.ARGS.k8s_skip_containers]]

        node_transports = []
        for container in containers:
            ret = await self.ws_api.connect_get_namespaced_pod_exec(address, constants.ARGS.k8s_namespace,
                                                                    container=container.name, command=exec_command,
                                                                    stderr=True, stdin=False, stdout=True, tty=False)
            node_transports.extend(parse_profile_strategy_response(ret, address, pfs.name))
        return node_transports

    async def take_a_hint(self, hint: Hint) -> List[NodeTransport]:
        ret = await self.api.list_namespaced_pod(constants.ARGS.k8s_namespace, limit=1,
                                                 label_selector=_parse_label_selector(hint.service_name))
        try:
            address = ret.items[0].metadata.name
        except IndexError:
            print(colored(f"Unable to take a hint, no instance in k8s cluster: "
                          f"{config.list_kube_config_contexts()[1]} for hint:", 'red'))
            print(colored(hint, 'yellow'))
            sys.exit(1)

        return [NodeTransport(hint.protocol_mux, address, hint.service_name)]

    async def _get_pod(self, pod_name: str) -> Optional[client.models.V1Pod]:
        """
        Get the pod from kubernetes API, with caching

        :param pod_name:
        :return:
        """
        if pod_name in pod_cache:
            return pod_cache[pod_name]

        try:
            pod = await self.api.read_namespaced_pod(pod_name, constants.ARGS.k8s_namespace)
            pod_cache[pod_name] = pod
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
                lb_name = svc.metadata.name
                k8s_service_address = svc.metadata.name
                k8s_service_name = f"{svc.metadata.name}-service"
                k8s_service_node = Node(
                    address=k8s_service_address,
                    node_type=NodeType.DEPLOYMENT,
                    profile_strategy=INVENTORY_PROFILE_STRATEGY,
                    protocol=INVENTORY_PROFILE_STRATEGY.protocol,
                    protocol_mux=ports.node_port,
                    provider='k8s',
                    service_name=k8s_service_name
                )
                # lb protocol/mux will be filled in when a connection is profiled thereto it
                lb_node = Node(
                    node_type=NodeType.TRAFFIC_CONTROLLER,
                    profile_strategy=INVENTORY_PROFILE_STRATEGY,
                    provider='k8s',
                    service_name=lb_name,
                    children={f"K8S_{k8s_service_address}": k8s_service_node}
                )
                database.save_node(k8s_service_node)
                database.save_node_by_dnsname(lb_node, lb_address)


def _parse_label_selector(service_name: str) -> str:
    """Generate a label selector to pass to the k8s api from service name and CLI args
    :param service_name: the service name
    """
    label_name_pos = 0
    label_value_pos = 1
    label_selector_pairs = {constants.ARGS.k8s_service_name_label: service_name}
    for label, value in [(selector.split('=')[label_name_pos], selector.split('=')[label_value_pos])
                         for selector in constants.ARGS.k8s_label_selectors]:
        label_selector_pairs[label] = value
    return ','.join(f"{label}={value}" for label, value in label_selector_pairs.items())
