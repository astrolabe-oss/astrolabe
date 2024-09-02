"""
Module Name: node

Description:
This module contains the class definitions for nodes and the NodeTransport data transport object

Copyright:
Copyright 2024 Magellanbot, Inc

License:
SPDX-License-Identifier: Apache-2.0
"""
from enum import Enum
from typing import Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime

from astrolabe import profile_strategy, network


database_muxes = ['3306', '9160', '5432', '6379', '11211']


class NodeType(Enum):
    NULL = 'NULL'
    COMPUTE = 'COMPUTE'
    RESOURCE = 'RESOURCE'
    DEPLOYMENT = 'DEPLOYMENT'
    TRAFFIC_CONTROLLER = 'TRAFFIC_CONTROLLER'
    __type__: str = 'NodeType'  # for json serialization/deserialization


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
    node_type: NodeType = NodeType(NodeType.NULL)


@dataclass
class Node:  # pylint:disable=too-many-instance-attributes
    profile_strategy: profile_strategy.ProfileStrategy
    provider: str
    protocol: network.Protocol = None
    protocol_mux: str = None
    containerized: bool = False
    from_hint: bool = False
    address: str = None
    service_name: str = None
    _profile_timestamp: datetime = None
    children: Dict[str, 'Node'] = field(default_factory=dict)
    warnings: dict = field(default_factory=dict)
    errors: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    node_type: NodeType = NodeType(NodeType.COMPUTE)
    __type__: str = 'Node'  # for json serialization/deserialization

    def is_database(self):
        return self.protocol_mux in database_muxes or self.protocol.is_database

    def profile_complete(self) -> bool:
        return self._profile_timestamp is not None

    def name_lookup_complete(self) -> bool:
        """
        Is name lookup complete on the Node()?

        :return:
        """
        return bool(self.service_name) or bool(self.errors) or 'NAME_LOOKUP_FAILED' in self.warnings

    def set_profile_timestamp(self) -> None:
        self._profile_timestamp = datetime.utcnow()

    def get_profile_timestamp(self) -> datetime:
        return self._profile_timestamp
