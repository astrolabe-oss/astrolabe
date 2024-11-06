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
from typing import Dict, Optional, List
from dataclasses import dataclass, field, asdict, is_dataclass, fields
from datetime import datetime, timezone
import json


database_muxes = ['3306', '9160', '5432', '6379', '11211']


class NodeType(Enum):
    NULL = 'NULL'
    COMPUTE = 'COMPUTE'
    RESOURCE = 'RESOURCE'
    DEPLOYMENT = 'DEPLOYMENT'
    TRAFFIC_CONTROLLER = 'TRAFFIC_CONTROLLER'
    __type__: str = 'NodeType'  # for json serialization/deserialization


# pylint:disable=too-many-instance-attributes
@dataclass(frozen=True)
class NodeTransport:
    """Data Transport object for Node.  Forms a binding contract between providers and discover().

    Attributes
        profile_strategy: the ProfileStrategy used to discover this NodeTransport
        provider: Node provider ref
        protocol: the protocol of the NodeTransport
        protocol_mux: the protocol multiplexer (port for TCP, nsq topic:channel for NSQ).
        address: the node address.  e.g. "IP address" or k8s pod name
        from_hint: wether the node transport is from a Hint
        debug_identifier: like the "name" of the service - but it is not the official name and only used for debug/logs
        num_connections: optional num_connections.  if 0, node will be marked as "DEFUNCT"
        metadata: optional key-value pairs of metadata.  not used by core but useful to custom plugins
    """
    profile_strategy_name: str  # name of profile strategy used to discover node
    provider: str
    protocol: 'network.Protocol'  # NOQA  (string import for type hint to avoid circular dependency)
    protocol_mux: str
    address: Optional[str] = None
    from_hint: bool = False
    debug_identifier: Optional[str] = None
    num_connections: Optional[int] = None
    metadata: Optional[dict] = field(default_factory=dict)
    node_type: NodeType = NodeType(NodeType.NULL)

    def __post_init__(self):
        if self.protocol_mux:
            object.__setattr__(self, 'protocol_mux', str(self.protocol_mux))


# pylint:disable=too-many-instance-attributes
@dataclass
class Node:
    profile_strategy_name: str  # name of the profile strategy used to determine, for debugging
    provider: str
    protocol: 'network.Protocol' = None  # NOQA  (string import for type hint to avoid circular dependency)
    protocol_mux: str = None
    containerized: bool = False
    from_hint: bool = False
    address: str = None
    service_name: str = None
    aliases: List[str] = field(default_factory=list)  # such as DNS names
    _profile_timestamp: Optional[datetime] = None
    _profile_lock_time: Optional[datetime] = None
    children: Dict[str, 'Node'] = field(default_factory=dict)
    warnings: dict = field(default_factory=dict)
    errors: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)
    node_type: NodeType = NodeType(NodeType.COMPUTE)
    __type__: str = 'Node'  # for json serialization/deserialization

    def __str__(self):
        def custom_serializer(obj):
            if hasattr(obj, '__dataclass_fields__'):
                obj_dict = asdict(obj)
                if 'node_type' in obj_dict:
                    obj_dict['node_type'] = str(obj.node_type)
                return {key: custom_serializer(value) for key, value in obj_dict.items()}
            elif isinstance(obj, datetime):
                return obj.isoformat()
            elif isinstance(obj, dict):
                return {key: custom_serializer(value) for key, value in obj.items()}
            elif isinstance(obj, list):
                return [custom_serializer(element) for element in obj]
            return str(obj)

        return json.dumps(custom_serializer(self))

    def __repr__(self):
        return self.__str__()

    def debug_id(self, shorten=60):
        clarifier = 'UNKNOWN'
        if self.address:
            clarifier = self.address

        if len(self.aliases) > 0:
            clarifier = self.aliases[0]

        debug_id = f"{self.provider}:{clarifier}"
        short = debug_id[:shorten] + '...' if len(debug_id) > shorten else debug_id
        return short

    def is_database(self):
        return self.protocol_mux in database_muxes or self.protocol.is_database

    def profile_complete(self, since: datetime) -> bool:
        return self._profile_timestamp is not None and self._profile_timestamp > since

    def name_lookup_complete(self) -> bool:
        """
        Is name lookup complete on the Node()?

        :return:
        """
        return bool(self.service_name) or bool(self.errors) or 'NAME_LOOKUP_FAILED' in self.warnings

    def set_profile_timestamp(self) -> None:
        self._profile_timestamp = datetime.now(timezone.utc)

    def get_profile_timestamp(self) -> datetime:
        return self._profile_timestamp

    def get_profile_lock_time(self) -> datetime:
        return self._profile_lock_time

    def aquire_profile_lock(self) -> None:
        self._profile_lock_time = datetime.utcnow()

    def clear_profile_lock(self) -> datetime:
        self._profile_lock_time = None

    def profile_locked(self) -> bool:
        return self._profile_lock_time is not None


def merge_node(copyto_node: Node, copyfrom_node: Node) -> None:
    if not is_dataclass(copyto_node) or not is_dataclass(copyfrom_node):
        raise ValueError("Both copyto_node and copyfrom_node must be dataclass instances")

    for fld in fields(Node):
        attr_name = fld.name
        inventory_preferred_attrs = ['provider', 'node_type']
        if attr_name in inventory_preferred_attrs:
            continue

        copyfrom_value = getattr(copyfrom_node, attr_name)

        # Only copy if the source value is not None, empty string, empty dict, or empty list
        if copyfrom_value is not None and copyfrom_value != "" and copyfrom_value != {} and copyfrom_value != []:
            setattr(copyto_node, attr_name, copyfrom_value)
