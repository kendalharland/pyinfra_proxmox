# PyInfra Proxmox Connector

The Proxmox connector allows pyinfra to manage proxmox nodes, LXC containers and VMs.

## Installation

```sh
uv install pyinfra-proxmox
```

## Configuration

This connector discovers the inventory of entities from a preconfigured 
proxmox host. To use it you must set these environment variables:

```sh
PROXMOX_HOST="10.0.0.100"
PROXMOX_USER="root"
PROXMOX_PASS="password"
PROXMOX_REALM="pam" # default
PROXMOX_DEAULT_NODE="" # optional
```

## Selectors

You can target entities using several different of selectors:

```sh
# Target all entities on the configured host.
@proxmox

# Target a specific cluster node 'pve0'
@proxmox/pve0

# Target a specific node's LXC or QEMU guest
@proxmox/pve0/lxc/102
@proxmox/pve0/qemu/102

# Target a guest on the default or lone node in a cluster.
@proxmox/lxc/102
@proxmox/qemu/102
```

If there is more than one node in your cluster you must set 
PROXMOX_DEFAULT_NODE in order to use the node-free selectors above. Otherwise an error will be raised.

## Usage examples

```sh
pyinfra @proxmox exec -- hostname -I

pyinfra @proxmox/proxmox exec -- pct list

pyinfra @proxmox/lxc/110 exec -- hostname -I

pyinfra @proxmox/proxmox/qemu/100 exec -- reboot
```

## API Limitations

This package uses the Proxmox API to fetch VM and LXC information. 
The Proxmox API allows fetching the current QEMU user of a running VM, but not
an LXC container. Since this is an inventory connector and SSH credentials are
not known ahead of time this connector assumes the following:

1. An LXC container uses the same ssh_user and ssh_pass as the proxmox host.
1. A QEMU VM uses the same ssh_pass as the proxmox host.
