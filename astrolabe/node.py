"""
Module Name: node

Description:
This module contains the class definitions for nodes and the NodeTransport data transport object

Copyright:
Copyright 2024 Magellanbot, Inc

License:
SPDX-License-Identifier: Apache-2.0
"""

from typing import Dict, Optional
from dataclasses import dataclass, field

from . import profile_strategy, constants, network

database_muxes = ['3306', '9160', '5432', '6379', '11211']


@dataclass(frozen=True)
class NodeTransport:
    """Data Transport object for Node.  Forms a binding contract between providers and discover().

    Attributes
        protocol_mux: the protocol multiplexer (port for TCP, nsq topic:channel for NSQ).
        address: the node address.  e.g. "IP address" or k8s pod name
        debug_identifier: like the "name" of the service - but it is not the official name and only used for debug/logs
        num_connections: optional num_connections.  if 0, node will be marked as "DEFUNCT"
        metadata: optional key-value pairs of metadata.  not used by core but useful to custom plugins
    """
    protocol_mux: str
    address: Optional[str] = None
    debug_identifier: Optional[str] = None
    num_connections: Optional[int] = None
    metadata: Optional[dict] = field(default_factory=dict)


@dataclass
class Node:
    profile_strategy: profile_strategy.ProfileStrategy
    protocol: network.Protocol
    protocol_mux: str
    provider: str
    containerized: bool = False
    from_hint: bool = False
    address: str = None
    service_name: str = None
    children: Dict[str, 'Node'] = None
    warnings: dict = field(default_factory=dict)
    errors: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    __type__: str = 'Node'  # for json serialization/deserialization

    def is_database(self):
        return self.protocol_mux in database_muxes or self.protocol.is_database

    def is_profileable(self, depth):
        if bool(self.errors) or bool(self.warnings):
            return False

        if network.skip_protocol_mux(self.protocol_mux):
            return False

        if self.service_name and network.skip_service_name(self.service_name):
            return False

        is_child_or_grandchild = depth > 0
        if constants.ARGS.skip_nonblocking_grandchildren and not self.protocol.blocking and is_child_or_grandchild:
            return False

        return True

    def is_excluded(self, depth):
        """Is excluded entirely from discovery results.  i.e. if we find it, pretend we didn't find it!"""
        if self.provider in constants.ARGS.disable_providers:
            return True

        is_grandchild = depth > 1
        if constants.ARGS.skip_nonblocking_grandchildren and not self.protocol.blocking and is_grandchild:
            return True

        return False

    def profile_complete(self, depth: int) -> bool:
        if not self.is_profileable(depth):
            return True

        if not self.name_lookup_complete():
            return False

        if depth == constants.ARGS.max_depth:
            return True

        return self.children is not None

    def name_lookup_complete(self) -> bool:
        """
        Is name lookup complete on the Node()?

        :return:
        """
        return bool(self.service_name) or bool(self.errors)
