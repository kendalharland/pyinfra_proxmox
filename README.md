# PyInfra Proxmox Connector

The Proxmox connector allows pyinfra to manage proxmox nodes, LXC containers and VMs.

## Installation

```sh
uv install pyinfra-proxmox
```

## Configuration

To use this connector you must specify which proxmox node to use as the remote
API server. The server's settings are configured via the environment:

```sh
PROXMOX_HOST="10.0.0.100"
PROXMOX_USER="root"
PROXMOX_PASS="password"
PROXMOX_REALM="pam" # default
```

## Selectors

You can target entities using several types of selectors:

```sh
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
```

If there is more than one node in your cluster you must set PROXMOX_DEFAULT_NODE
to the name of a default node in order to use the node-free selectors above.
Otherwise an error will be raised.

## Executing Commands

This connector discovers the inventory of entities from the proxmox host
configured in the environment settings (see above). You can use selectors
to control which hosts are targeted.

```sh
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
```