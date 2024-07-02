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

import sys
from typing import Dict, List, Optional

from kubernetes import client, config
from kubernetes.stream import stream
from termcolor import colored

from astrolabe import constants
from astrolabe.network import Hint
from astrolabe.node import NodeTransport
from astrolabe.providers import ProviderInterface, parse_profile_strategy_response
from astrolabe.plugin_core import PluginArgParser

pod_cache: Dict[str, client.models.V1Pod] = {}


class ProviderKubernetes(ProviderInterface):
    def __init__(self):
        config.load_kube_config()
        self.api = client.CoreV1Api()

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
        pod = self._get_pod(address)
        service_name_label = 'app'
        if service_name_label in pod.metadata.labels:
            return pod.metadata.labels[service_name_label]

        return None

    async def profile(self, address: str, _: Optional[type], **kwargs) -> List[NodeTransport]:
        shell_command = kwargs['shell_command']
        exec_command = ['sh', '-c', shell_command]
        containers = self._get_pod(address).spec.containers
        containers = [c for c in containers if True not in
                      [skip in c.name for skip in constants.ARGS.k8s_skip_containers]]

        node_transports = []
        for container in containers:
            ret = stream(self.api.connect_get_namespaced_pod_exec, address, constants.ARGS.k8s_namespace,
                         container=container.name, command=exec_command,
                         stderr=True, stdin=False, stdout=True, tty=False)
            node_transports.extend(parse_profile_strategy_response(ret, address, shell_command))
        return node_transports

    async def take_a_hint(self, hint: Hint) -> List[NodeTransport]:
        ret = self.api.list_namespaced_pod(constants.ARGS.k8s_namespace, limit=1,
                                           label_selector=_parse_label_selector(hint.service_name))
        try:
            address = ret.items[0].metadata.name
        except IndexError:
            print(colored(f"Unable to take a hint, no instance in k8s cluster: "
                          f"{config.list_kube_config_contexts()[1]} for hint:", 'red'))
            print(colored(hint, 'yellow'))
            sys.exit(1)

        return [NodeTransport(hint.protocol_mux, address, hint.service_name)]

    def _get_pod(self, pod_name: str) -> client.models.V1Pod:
        """
        Get the pod from kubernetes API, with caching

        :param pod_name:
        :return:
        """
        if pod_name in pod_cache:
            pod = pod_cache[pod_name]
        else:
            pod = self.api.read_namespaced_pod(pod_name, constants.ARGS.k8s_namespace)
            pod_cache[pod_name] = pod

        return pod


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
