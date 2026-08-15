"""PyInfra Proxmox Connector

The Proxmox connector allows pyinfra to manage a proxmox node and its guest LXC
containers and VMs.

Installation
-------------

uv install pyinfra-proxmox

Configuration
-------------
To use this connector you must specify which proxmox node to use as the remote
API server. The server's settings are configured via the environment:

    PROXMOX_HOST="10.0.0.100"
    PROXMOX_USER="root"
    PROXMOX_PASS="password"
    PROXMOX_REALM="pam" # default

Selectors
---------
You can target entities using several types of selectors:

    # Target all entities
    @proxmox

    # Target a specific cluster node
    @proxmox/pve0

    # Target a specific node's LXC or QEMU guest
    @proxmox/pve0/lxc/102
    @proxmox/pve0/qemu/102

    # Target a guest on the standalone node in a cluster.
    @proxmox/lxc/102
    @proxmox/qemu/102

If there is more than one node in your cluster you must set PROXMOX_DEFAULT_NODE
to the name of a default node in order to use the node-free selectors above.
Otherwise an error will be raised.

Executing Commands
------------------
This connector discovers the inventory of entities from the proxmox host
configured in the environment settings (see above). You can use selectors
to control which hosts are targeted.

    # Execute commands against the configured API host node
    pyinfra @proxmox exec -- hostname -I
    pyinfra @proxmox exec -- pct list

    # Execute commands against a cluster node named "proxmox".
    pyinfra @proxmox/promox exec -- hostname -I

    # Execute commands against an node's guest LXC
    pyinfra @proxmox/proxmox/lxc/110 exec -- hostname -I

    # Execute commands against a VM
    pyinfra @proxmox/proxmox/qemu/100 exec -- reboot

    # Execute commands against all containers and VMs
    pyinfra @proxmox/proxmox/all exec -- hostname -I
"""

# TODO: Explain how to target the connector from explicit inventory entries.

import os
import time
from typing import override, Unpack, Callable
from paramiko.ssh_exception import SSHException

from pyinfra import logger
from pyinfra.connectors.base import BaseConnector
from pyinfra.connectors.ssh import SSHConnector
from pyinfra.connectors.util import CommandOutput
from pyinfra.connectors.util import extract_control_arguments, make_unix_command_for_host
from pyinfra.api.command import StringCommand, QuoteString
from pyinfra.api.arguments import ConnectorArguments
from pyinfra.api.host import Host
from pyinfra.api.state import State
from pyinfra.api.exceptions import ConnectError
from pyinfra_proxmox.errors import ProxmoxError
from pyinfra_proxmox.inventory import (
    EntityKind, 
    ProxmoxApiSettings, 
    discover_proxmox_inventory, 
    list_proxmox_entities,
    lxc_inventory_item,
    qemu_inventory_item,
    node_inventory_item,
    get_vm_ip,
    get_vm_user,
    Selector,
    FullyQualifiedSelector,
    GuestSelector,
    get_standalone_node,
)

def load_proxmox_settings():
    return ProxmoxApiSettings(
        hostname = os.getenv("PROXMOX_HOST"),
        username = os.getenv("PROXMOX_USER"),
        password = os.getenv("PROXMOX_PASS"),
        realm = os.getenv("PROXMOX_REALM"),
        default_node = os.getenv("PROXMOX_DEFAULT_NODE", None)
    )

class ProxmoxConnector(BaseConnector):
    NAME_ALL_GUESTS = "all"
    NAME_PREFIX_LXC = "lxc/"
    NAME_PREFIX_VM = "qemu/"

    #
    # Helpers
    #

    ssh: SSHConnector

    #
    # BaseConnector implementation
    #

    handles_execution = True

    def __init__(self, state: State, host: Host):
        super().__init__(state, host)

    @override
    @staticmethod
    def make_names_data(name=None):
        settings = load_proxmox_settings()
       
        # All targets in the cluster
        if not name:
            yield from discover_proxmox_inventory(settings)
            return

        selector = Selector.parse(name)

        if isinstance(selector, GuestSelector):
            # Try resolving the nodename
            if settings.default_node:
                node = settings.default_node
            else:
                entity = get_standalone_node(settings.api())
                node = entity["node"]

            selector = FullyQualifiedSelector(
                node = node,
                kind = selector.kind,
                vmid = selector.vmid,
            )
            
        # Find the entity matching the selector
        try:
            entities = list_proxmox_entities(settings.api())
            entity = next(e for e in entities if e.matches(selector))
        except StopIteration:
            raise ProxmoxError(f"entity not found: '{name}'")

        # Generate the inventory item.
        if entity.kind == EntityKind.LXC:
            yield lxc_inventory_item(entity, settings.host_data())
        elif entity.kind == EntityKind.QEMU:
            api = settings.api()
            api_host_data = settings.host_data()
            host_data = {
                "ssh_hostname": get_vm_ip(api, entity.node, entity.vmid),
                "ssh_user": get_vm_user(api, entity.node, entity.vmid),
                "ssh_pass": api_host_data["ssh_pass"],
            }
            yield qemu_inventory_item(entity, host_data)
        else:
            assert entity.kind == EntityKind.HOST
            yield node_inventory_item(entity, settings.host_data())
            

        

    @override
    def connect(self):
        self.ssh = SSHConnector(self.state, self.host)
        self.ssh.connect()
        self.api = load_proxmox_settings().api()

    @override
    def disconnect(self) -> None:
        self.ssh.disconnect()

    @override
    def run_shell_command(
        self,
        command: StringCommand,
        print_output: bool = False,
        print_input: bool = False,
        **arguments: Unpack["ConnectorArguments"],
    ) -> tuple[bool, CommandOutput]:
        # Extract and remove control parameters from arguments
        # This modifies arguments dict in place and returns the extracted params
        ssh_arguments = extract_control_arguments(arguments)
        command = make_unix_command_for_host(self.state, self.host, command, **arguments)

        # Proxmox VMs can find /bin/sh but not sh.
        # make_unix_command_for_host neglects to use the absolute path.
        command = StringCommand(QuoteString(command))

        if self.host.data.get("kind") == EntityKind.LXC:
            # Indirect execution; Shell into the proxmox VE shell and run with `pct exec`.
            vmid = self.host.data.get("vmid")
            proxmox_cmd = StringCommand(f"pct exec {vmid} -- /bin/sh -c {command}")
        else:
            # QEMU VMs and proxmox hosts use a direct SSH connection.
            proxmox_cmd = StringCommand(f"/bin/sh -c {command}")

        logger.debug(
            "run_shell_command: host=%s target=%s vmid=%s command=%s",
            self.host.name,
            self.host.data.get("kind"),
            self.host.data.get("vmid"),
            proxmox_cmd,
        )

        return self.ssh.run_shell_command(
            proxmox_cmd,
            print_output=print_output,
            print_input=print_input,
            **ssh_arguments,
        )

    @override
    def put_file(
        self,
        filename_or_io,
        remote_filename,
        remote_temp_filename = None,  # ignored
        print_output: bool = False,
        print_input: bool = False,
        **arguments,
    ) -> bool:
        """
        Upload a local file or IO object by copying it to a temporary directory
        and then writing it to the upload location.

        Returns:
            bool: indicating success or failure.
        """
        # TODO: implement
        raise Exception("unimplemented")
        if self.host.data.get("kind") == EntityKind.HOST:
            return self.ssh.put_file(
                filename_or_io,
                remote_filename,
                remote_temp_filename,
                print_output,
                print_input,
                **arguments,
            )

        if self.host.data.get("kind") == EntityKind.LXC:
            vmid = self.host.data.get("vmid")
            proxmox_cmd = StringCommand("pct", "push", f"{vmid}", remote_temp_filename, remote_filename)

        if self.host.data.get("kind") == EntityKind.QEMU:
            logger.warning("vm file upload is unimplemented")
            return

        # Copy to temp location on proxmox node first.
        if not self.ssh.put_file(
            filename_or_io,
            remote_temp_filename,
            remote_temp_filename=None,
            print_output=print_output,
            print_input=print_input,
            **arguments,
        ):
            logger.error(f"failed to upload file to {self.ssh.host}")
            return False

        # Copy from temp location on proxmox node into final location on the guest.
        status, output = self.ssh.run_shell_command(
            proxmox_cmd,
            print_output=print_output,
            print_input=print_input,
        )

        if not status:
            logger.error(output)

        return status

    @override
    def get_file(
        self,
        remote_filename,
        filename_or_io,
        remote_temp_filename=None,  # ignored
        print_output: bool = False,
        print_input: bool = False,
        **arguments,
    ) -> bool:
        """
        Download a local file by copying it to a temporary location and then writing
        it to our filename or IO object.

        Returns:
            bool: indicating success or failure.
        """
        raise Exception("unimplemented")
        if self.host.data.get("kind") == EntityKind.HOST:
            return self.ssh.put_file(
                filename_or_io,
                remote_filename,
                remote_temp_filename,
                print_output,
                print_input,
                **arguments,
            )

        if self.host.data.get("kind") == EntityKind.LXC:
            vmid = self.host.data.get("vmid")
            proxmox_cmd = StringCommand("pct", "pull", f"{vmid}", remote_temp_filename, remote_filename)

        if self.host.data.get("kind") == EntityKind.QEMU:
            logger.warning("vm file upload is unimplemented")
            return

        # Copy to temp location on proxmox node first.
        if not self.ssh.put_file(
            filename_or_io,
            remote_temp_filename,
            remote_temp_filename=None,
            print_output=print_output,
            print_input=print_input,
            **arguments,
        ):
            logger.error(f"failed to upload file to {self.ssh.host}")
            return False

        # Copy from temp location on proxmox node into final location on the guest.
        success, output = self.ssh.run_shell_command(
            proxmox_cmd,
            print_output=print_output,
            print_input=print_input,
        )

        if not success:
            logger.error(output)

        return success


def retry(func, max_attempts=5, delay=2, exceptions=(Exception,)):
    """
    Retry `func(*args, **kwargs)` up to `max_attempts` times.
    Raises the last exception if all attempts fail.
    """
    last_exception = None

    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except exceptions as e:
            last_exception = e
            if attempt < max_attempts:
                time.sleep(delay)
            else:
                raise last_exception