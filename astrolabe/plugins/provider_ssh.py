"""
Module Name: provider_ssh

Description:
Provider for connecting to Linux instances over SSH.  Expects SSH config set up correctly.

Assumptions:
- A Jump/Bastion server is used
- The Jump/Bastion server is configured in an ssh config file per host, default ~/.ssh/config

Copyright:
Copyright 2024 Magellanbot, Inc

License:
SPDX-License-Identifier: Apache-2.0
"""

import asyncio
import os
import getpass
import sys
from typing import List, Optional

import asyncssh
import paramiko
from asyncssh import ChannelOpenError, SSHClientConnection
from termcolor import colored

from astrolabe import database, constants, logs
from astrolabe.profile_strategy import ProfileStrategy
from astrolabe.providers import ProviderInterface, TimeoutException, parse_profile_strategy_response
from astrolabe.plugin_core import PluginArgParser
from astrolabe.node import Node, NodeTransport

bastion: Optional[SSHClientConnection] = None
CONNECT_TIMEOUT = 5
CONNECTION_SEMAPHORE = None
CONNECTION_SEMAPHORE_SPACES_USED = 0
CONNECTION_SEMAPHORE_SPACES_MIN = 10
SSH_CONNECT_ARGS = None


class ProviderSSH(ProviderInterface):
    @staticmethod
    def ref() -> str:
        return 'ssh'

    @staticmethod
    def register_cli_args(argparser: PluginArgParser):
        argparser.add_argument('--bastion-timeout', type=int, default=10, metavar='TIMEOUT',
                               help='Timeout in seconds to establish SSH connection to bastion (jump server)')
        argparser.add_argument('--concurrency', type=int, default=10, metavar='CONCURRENCY',
                               help='Max number of concurrent SSH connections')
        argparser.add_argument('--config-file', default="~/.ssh/config", metavar='FILE',
                               help='SSH config file to parse for configuring SSH sessions.  '
                                    'As in `ssh -F ~/.ssh/config`)')
        argparser.add_argument('--passphrase', action='store_true',
                               help='Prompt for, and use the specified passphrase to decrype SSH private keys')
        argparser.add_argument('--name-command', required=True, metavar='COMMAND',
                               help='Used by SSH Provider to determine node name')

    async def open_connection(self, address: str) -> SSHClientConnection:
        await _configure_connection_semaphore()
        if not SSH_CONNECT_ARGS:
            await _configure(address)
        logs.logger.debug("Getting asyncio SSH connection for host %s", address)
        async with CONNECTION_SEMAPHORE:
            return await _get_connection(address)

    async def lookup_name(self, address: str, connection: SSHClientConnection) -> str:
        logs.logger.debug("Getting service name for address %s", address)
        node_name_command = constants.ARGS.ssh_name_command
        async with CONNECTION_SEMAPHORE:
            result = await connection.run(node_name_command, check=True)
        node_name = result.stdout.strip()
        logs.logger.debug("Discovered name: %s for address %s", node_name, address)

        return node_name

    async def sidecar(self, address: str, connection: SSHClientConnection) -> None:
        logs.logger.debug("Running sidecars for address %s", address)
        await _sidecar_lookup_hostnames(address, connection)

    async def profile(self, address: str, pfss: List[ProfileStrategy], connection: SSHClientConnection)\
            -> List[NodeTransport]:
        node_transports = []
        for pfs in pfss:
            try:
                command = pfs.provider_args['shell_command']
            except IndexError as exc:
                print(colored(f"Crawl Strategy incorrectly configured for provider SSH.  "
                              f"Expected **kwargs['shell_command']. Got:{str(pfs.provider_args)}", 'red'))
                raise exc
            response = await connection.run(command)
            if response.stdout.strip().startswith('ERROR:'):
                raise Exception("CRAWL ERROR: %s" %  # pylint: disable=broad-exception-raised
                                response.stdout.strip().replace("\n", "\t"))
            i_node_transports = parse_profile_strategy_response(response.stdout.strip(), address, pfs)
            node_transports.extend(i_node_transports)
        return node_transports


async def _get_connection(host: str, retry_num=0) -> asyncssh.SSHClientConnection:
    logs.logger.debug("Getting asyncio SSH connection for host %s", host)
    try:
        if bastion:
            logs.logger.debug("Using bastion: %s", str(bastion))
            conn = await bastion.connect_ssh(host, **SSH_CONNECT_ARGS)
        conn = await asyncssh.connect(host, **SSH_CONNECT_ARGS)
        return conn
    except ChannelOpenError as exc:
        raise TimeoutException(f"asyncssh.ChannelOpenError encountered opening SSH connection for {host}") from exc
    except Exception as exc:
        if retry_num < 3:
            asyncio.ensure_future(_occupy_one_sempahore_space())
            await asyncio.sleep(.1)
            return await _get_connection(host, retry_num + 1)
        raise exc


async def _occupy_one_sempahore_space() -> None:
    """Use up one spot in the SSH connection semaphore.

       This is used to fine tune whether the semaphore is configured
       for too many concurrent SHH connection.  It will not occupy more
       than that which leaves {semaphore_spaces_min} spaces in the
       semaphore for real work.
    """
    global CONNECTION_SEMAPHORE_SPACES_USED

    if (constants.ARGS.ssh_concurrency - CONNECTION_SEMAPHORE_SPACES_USED) > CONNECTION_SEMAPHORE_SPACES_MIN:
        async with CONNECTION_SEMAPHORE:
            CONNECTION_SEMAPHORE_SPACES_USED += 1
            logs.logger.debug("Using 1 additional semaphore space, (%d used)", CONNECTION_SEMAPHORE_SPACES_USED)
            forever_in_the_context_of_this_program = 86400
            await asyncio.sleep(forever_in_the_context_of_this_program)


# configuration private functions
async def _configure(address: str):
    global bastion, SSH_CONNECT_ARGS
    # SSH CONNECT ARGS
    SSH_CONNECT_ARGS = {'known_hosts': None}
    ssh_config = _get_ssh_config_for_host(address)
    SSH_CONNECT_ARGS['username'] = ssh_config.get('user')
    if constants.ARGS.ssh_passphrase:
        SSH_CONNECT_ARGS['passphrase'] = getpass.getpass(colored("Enter SSH key passphrase:", 'green'))

    # BASTION
    bastion_address = _get_jump_server_for_host(ssh_config)
    if not bastion_address:
        return

    try:
        bastion = await asyncio.wait_for(
            asyncssh.connect(bastion_address, **SSH_CONNECT_ARGS), timeout=constants.ARGS.ssh_bastion_timeout
        )
    except asyncio.TimeoutError:
        print(colored(f"Timeout connecting to SSH bastion server: {bastion_address}.  "
                      f"Try turning it off and on again.", 'red'))
        sys.exit(1)
    except asyncssh.PermissionDenied:
        print(colored(f"SSH Permission denied attempting to connect to {address}.  It is possible that your SSH Key "
                      f"requires a passphrase.  If this is the case please add either it to ssh-agent with `ssh-add` "
                      f"(See https://www.ssh.com/ssh/add for details on that process) or try again using the "
                      f"--ssh-passphrase argument.  ", 'red'))
        sys.exit(1)


async def _configure_connection_semaphore():
    global CONNECTION_SEMAPHORE
    CONNECTION_SEMAPHORE = asyncio.BoundedSemaphore(constants.ARGS.ssh_concurrency)


def _get_ssh_config_for_host(host: str) -> dict:
    """Parse ssh config file to retrieve bastion address and username

    :param host: (str) host to parse ssh config file for
    :return: a dict of ssh config, e.g.
        {
            'forwardagent': 'yes',
            'hostname': '10.0.0.145',
            'proxycommand': 'ssh -q ops nc 10.0.0.145 22',
            'serveraliveinterval': '120',
            'stricthostkeychecking': 'no',
            'user': 'foo',
            'userknownhostsfile': '/dev/null'
        }
    """
    ssh_config = paramiko.SSHConfig()
    user_config_file = os.path.expanduser(constants.ARGS.ssh_config_file)
    try:
        with open(user_config_file, encoding="utf8") as open_file:
            ssh_config.parse(open_file)
    except FileNotFoundError:
        print("%s file could not be found. Aborting.", user_config_file)
        sys.exit(1)

    return ssh_config.lookup(host)


def _get_jump_server_for_host(config: dict) -> Optional[str]:
    """
    :param config: ssh config in dict format as returned by paramiko.SSHConfig().lookup()
    """
    config_file_path = os.path.expanduser(constants.ARGS.ssh_config_file)
    proxycommand_host = _get_proxycommand_host(config)
    proxyjump_host = _get_proxyjump_host(config)
    bastion_host = proxyjump_host or proxycommand_host

    if not bastion_host:
        return None

    bastion_config = _get_ssh_config_for_host(bastion_host)

    if 'hostname' not in bastion_config:
        print(colored("Bastion (proxy) SSH Host: (%s) misconfigured in %s...  "
                      "Please correct your ssh config! Contents:", bastion_host, config_file_path, 'red'))
        constants.PP.pprint(config)
        sys.exit(1)

    return bastion_config['hostname']


def _get_proxycommand_host(config):
    if 'proxycommand' not in config:
        return None

    proxycommand_columns = config['proxycommand'].split(" ")

    if 6 != len(proxycommand_columns):
        return None

    return proxycommand_columns[2]


def _get_proxyjump_host(config):
    if 'proxyjump' not in config:
        return None

    return config['proxyjump']


async def _sidecar_lookup_hostnames(address: str, connection: SSHClientConnection) -> None:
    """we are cheating! for every instance we ssh into, we are going to try a name lookup
       to get the DNS names for anything in the astrolabe DNS Cache that we don't yet have
       """
    asyncio_tasks = []
    for hostname, node in database.get_nodes_pending_dnslookup():
        asyncio_tasks.append(_sidecar_lookup_hostname(address, hostname, node, connection))
    await asyncio.gather(*asyncio_tasks)


async def _sidecar_lookup_hostname(address: str, hostname: str, node: Node, connection: SSHClientConnection) -> None:
    """we are cheating! for every instance we ssh into, we are going to try a name lookup
       to get the DNS names for anything in the astrolabe DNS Cache that we don't yet have
       """
    sidecar_command = f"getent hosts {hostname} | awk '{{print $1}}'"
    logs.logger.debug("Looking up ipaddresses for hostname %s on host %s", hostname, address)
    async with CONNECTION_SEMAPHORE:
        result = await connection.run(sidecar_command, check=True)
    if not result:
        logs.logger.info("No ipaddres found for hostname %s on host %s", hostname, address)
        return

    ip_addrs = result.stdout.strip().split('\n')
    logs.logger.info("Found ipaddresses: [%s] for hostname %s on host %s", ",".join(ip_addrs), hostname, address)
    for addr_bytes in ip_addrs:
        address = str(addr_bytes)
        if address and database.get_node_by_address(address) is None:
            logs.logger.debug(f"Discovered IP %s for {hostname}: from address %s", addr_bytes, address)
            node.address = address
            database.save_node(node)