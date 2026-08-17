"""PyInfra Proxmox Connector

The Proxmox connector allows pyinfra to manage a proxmox node and its guest LXC
containers and VMs. See README.md for documentation.
"""

# TODO: Explain how to target the connector from explicit inventory entries.

import os
from typing import override, Unpack

from pyinfra.connectors.ssh import SSHConnector
from pyinfra.connectors.util import CommandOutput
from pyinfra.connectors.util import (
    extract_control_arguments,
    make_unix_command_for_host,
)
from pyinfra.api.command import StringCommand, QuoteString
from pyinfra.api.arguments import ConnectorArguments
from pyinfra.api.host import Host
from pyinfra.api.state import State
from pyinfra_proxmox.errors import ProxmoxError
from pyinfra_proxmox.inventory import (
    ProxmoxApiSettings,
    discover_proxmox_inventory,
    list_proxmox_entities,
    Selector,
    FullyQualifiedSelector,
    GuestSelector,
    get_standalone_node,
    generate_inventory_item,
)


def load_proxmox_settings():
    return ProxmoxApiSettings(
        hostname=os.getenv("PROXMOX_HOST"),
        username=os.getenv("PROXMOX_USER"),
        password=os.getenv("PROXMOX_PASS"),
        realm=os.getenv("PROXMOX_REALM"),
        default_node=os.getenv("PROXMOX_DEFAULT_NODE", None),
    )


class ProxmoxConnector(SSHConnector):
    NAME_ALL_GUESTS = "all"
    NAME_PREFIX_LXC = "lxc/"
    NAME_PREFIX_VM = "qemu/"

    def __init__(self, state: State, host: Host):
        super().__init__(state, host)

    @override
    @staticmethod
    def make_names_data(name=None):
        settings = load_proxmox_settings()

        # User wrote @proxmox without a selector.
        # Resolve all entities in the cluster.
        if not name:
            yield from discover_proxmox_inventory(settings)
            return

        selector = Selector.parse(name)

        # Resolve the selector to a FullyQualifiedSelector
        if isinstance(selector, GuestSelector):
            if settings.default_node:
                node = settings.default_node
            else:
                entity = get_standalone_node(settings.api())
                node = entity["node"]

            selector = FullyQualifiedSelector(
                node=node,
                kind=selector.kind,
                vmid=selector.vmid,
            )

        # Find the entity matching the selector
        try:
            entities = list_proxmox_entities(settings.api())
            entity = next(e for e in entities if e.matches(selector))
        except StopIteration:
            raise ProxmoxError(f"entity not found: '{name}'")

        yield from generate_inventory_item(settings, entity)

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
        command = make_unix_command_for_host(
            self.state, self.host, command, **arguments
        )

        # Proxmox guests require an absolute path to /bin/sh.
        command = StringCommand(QuoteString(command))
        command = StringCommand(f"/bin/sh -c {command}")

        return super().run_shell_command(
            command,
            print_output=print_output,
            print_input=print_input,
            **ssh_arguments,
        )
