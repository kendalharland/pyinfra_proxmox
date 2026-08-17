from dataclasses import dataclass
from typing import NamedTuple, override
from proxmoxer import ProxmoxAPI
from enum import Enum

from .errors import InvalidInputError, ProxmoxError


class ProxmoxApiSettings(NamedTuple):
    hostname: str
    username: str
    password: str
    realm: str = "pam"
    default_node: str | None = None

    @staticmethod
    def from_host_data(host_data: dict):
        return ProxmoxApiSettings(
            hostname=host_data.get(
                "proxmox_hostname", host_data.get("ssh_hostname", "")
            ),
            username=host_data.get("proxmox_user", host_data.get("ssh_user", "root")),
            password=host_data.get(
                "proxmox_pass", host_data.get("ssh_pass", "password")
            ),
            realm=host_data.get("proxmox_auth_realm", "pam"),
            default_node=host_data.get("proxmox_default_node", None),
        )

    def api(self) -> ProxmoxAPI:
        if not self.hostname:
            raise ProxmoxError("no hostname is configured")
        return ProxmoxAPI(
            self.hostname,
            user=f"{self.username}@{self.realm}",
            password=self.password,
            verify_ssl=False,
        )

    def host_data(self) -> dict:
        return {
            "ssh_hostname": self.hostname,
            "ssh_user": self.username,
            "ssh_pass": self.password,
        }


class EntityKind(Enum):
    LXC = "lxc"
    QEMU = "qemu"
    NODE = "node"

    def __str__(self) -> str:
        return self.value


class Selector:
    @staticmethod
    def parse(value: str):
        return parse_selector(value)


@dataclass
class FullyQualifiedSelector(Selector):
    """@proxmox/$node/$kind/$vmid
    Targets an entity on a specific cluster node.
    """

    node: str
    kind: EntityKind
    vmid: int


@dataclass
class GuestSelector(Selector):
    """@proxmox/$kind/$vmid
    Targets an entity from the default node or a standalone cluster node.
    """

    kind: EntityKind
    vmid: str


@dataclass
class NodeSelector(Selector):
    """@proxmox/$node
    Targets a specific node in a cluster.
    """

    node: str


class InventoryTarget(NamedTuple):
    name: str
    data: dict
    groups: list[str] = []


class NodeEntity(NamedTuple):
    node: str
    status: str
    maxdisk: int
    mem: int
    ssl_fingerprint: str
    uptime: int
    cpu: float
    id: str
    level: str
    type: str
    maxmem: int
    status: str
    maxcpu: int
    disk: int

    @property
    def kind(self) -> EntityKind:
        return EntityKind.NODE

    @property
    def is_running(self) -> bool:
        return self.status in ("running", "online")

    def matches(self, selector: Selector):
        return isinstance(selector, NodeSelector) and selector.node == self.node


class LxcEntity(NamedTuple):
    node: str
    vmid: int
    status: str
    name: str
    mem: int
    maxmem: int
    disk: int
    maxdisk: int
    cpu: float
    cpus: int
    netin: int
    netout: int
    uptime: int
    maxswap: int
    diskread: int
    diskwrite: int
    type: str
    swap: int
    pid: int = 0
    tags: str = ""
    pressurememoryfull: float = 0
    pressurememorysome: float = 0
    pressureiofull: float = 0
    pressureiosome: float = 0
    pressurecpusome: float = 0
    pressurecpufull: float = 0

    @property
    def kind(self) -> EntityKind:
        return EntityKind.LXC

    @property
    def is_running(self) -> bool:
        return self.status == "running"

    def matches(self, selector: Selector):
        return (
            isinstance(selector, FullyQualifiedSelector)
            and selector.node == self.node
            and selector.kind == self.kind
            and selector.vmid == self.vmid
        )


class QemuEntity(NamedTuple):
    node: str

    vmid: int
    status: str
    name: str
    mem_mb: int = ""
    bootdisk_gb: int = ""
    pid: int = 0
    cpu: int = 0
    mem: int = 0
    mem_mb: int = 0
    maxmem: int = 0
    serial: int = 0
    disk: int = 0
    maxdisk: int = 0
    memhost: int = 0
    cpus: int = 0
    netin: int = 0
    netout: int = 0
    uptime: int = 0
    pressurememoryfull: float = 0
    pressurememorysome: float = 0
    pressureiofull: float = 0
    pressureiosome: float = 0
    pressurecpusome: float = 0
    pressurecpufull: float = 0

    @property
    def kind(self) -> EntityKind:
        return EntityKind.QEMU

    @property
    def is_running(self) -> bool:
        return self.status == "running"

    @override
    def matches(self, selector: Selector):
        return (
            isinstance(selector, FullyQualifiedSelector)
            and selector.node == self.node
            and selector.kind == self.kind
            and selector.vmid == self.vmid
        )


ProxmoxEntity = QemuEntity | LxcEntity | NodeEntity


def discover_proxmox_inventory(settings: ProxmoxApiSettings):
    """
    Generates dynamic inventory data from the entity containers and VMs of a
    Proxmox node. See the class docstring for accepted name formats.
    """
    # Include the host as part of the inventory

    api = settings.api()
    for entity in list_proxmox_entities(api):
        if not entity.is_running:
            continue
        yield from generate_inventory_item(settings, entity)
    return


def parse_entity_kind(value: str) -> tuple[EntityKind, bool]:
    if value == EntityKind.LXC.value:
        return EntityKind.LXC
    if value == EntityKind.QEMU.value:
        return EntityKind.QEMU
    if value == EntityKind.NODE.value:
        return EntityKind.NODE
    raise InvalidInputError("entity kind", value)


def parse_vmid(value: str) -> int:
    if not value.isdigit():
        raise InvalidInputError("vmid", value)
    return int(value)


def parse_selector(name: str) -> Selector:
    if name.count("/") > 2:
        raise InvalidInputError("selector", name)

    parts = name.split("/", maxsplit=2)

    if len(parts) == 1:  # node
        return NodeSelector(node=parts[0])

    if len(parts) == 2:  # kind/vmid
        kind = parse_entity_kind(parts[0])
        vmid = parse_vmid(parts[1])
        return GuestSelector(kind=kind, vmid=vmid)

    if len(parts) == 3:  # node/kind/vmid
        node = parts[0]
        kind = parse_entity_kind(parts[1])
        vmid = parse_vmid(parts[2])
        return FullyQualifiedSelector(node=node, kind=kind, vmid=vmid)

    raise InvalidInputError("selector", name)


def generate_inventory_item(settings: ProxmoxApiSettings, entity: ProxmoxEntity):
    api = settings.api()
    api_host_data = settings.host_data()

    if entity.kind == EntityKind.LXC:
        yield lxc_inventory_item(
            entity,
            {
                "ssh_hostname": get_lxc_ip(api, entity.node, entity.vmid),
                # The Proxmox API doesn't support fetching the current logged in
                # container user. Assume the user is the same as the promox VE
                # shell user.
                "ssh_user": api_host_data["ssh_user"],
                "ssh_pass": api_host_data["ssh_pass"],
            },
        )
    elif entity.kind == EntityKind.QEMU:
        yield qemu_inventory_item(
            entity,
            {
                "ssh_hostname": get_vm_ip(api, entity.node, entity.vmid),
                "ssh_user": get_vm_user(api, entity.node, entity.vmid),
                # Since this connector has to discover the inventory itself,
                # assume the current QEMU VM user has the same password as
                # the Promxmox API host user.
                "ssh_pass": api_host_data["ssh_pass"],
            },
        )
    else:
        assert entity.kind == EntityKind.NODE
        yield node_inventory_item(entity, api_host_data)


def node_inventory_item(entity: NodeEntity, host_data: dict) -> InventoryTarget:
    return tuple(
        InventoryTarget(
            name=entity.node,
            data={
                **host_data,
                "kind": EntityKind.NODE,
            },
        )
    )


def lxc_inventory_item(entity: LxcEntity, host_data: dict) -> InventoryTarget:
    target_name = f"{entity.node}/{entity.kind}/{entity.vmid}"
    return tuple(
        InventoryTarget(
            name=target_name,
            data={
                **host_data,
                "kind": entity.kind,
                "vmid": entity.vmid,
            },
        )
    )


def qemu_inventory_item(entity: QemuEntity, host_data: dict) -> InventoryTarget:
    target_name = f"{entity.node}/{entity.kind}/{entity.vmid}"
    return tuple(
        InventoryTarget(
            name=target_name,
            data={
                **host_data,
                "kind": entity.kind,
                "vmid": entity.vmid,
            },
        )
    )


def list_proxmox_entities(api: ProxmoxAPI) -> ProxmoxEntity:
    entities: list[ProxmoxEntity] = []

    for node in api.nodes.get():
        entities.append(NodeEntity(**node))

        entities.extend(
            [
                LxcEntity(node=node["node"], **entity)
                for entity in api.nodes(node["node"]).lxc.get()
            ]
        )

        entities.extend(
            [
                QemuEntity(node=node["node"], **entity)
                for entity in api.nodes(node["node"]).qemu.get()
            ]
        )

    return entities


def get_vm_ip(api, node, vmid):
    result = api.nodes(node).qemu(vmid).agent.get("network-get-interfaces")

    for iface in result["result"]:
        if iface["name"] == "lo":
            continue  # skip loopback
        for addr in iface.get("ip-addresses", []):
            if addr["ip-address-type"] == "ipv4":
                return addr["ip-address"]
    return None


def get_lxc_ip(api, node, vmid):
    interfaces = api.nodes(node).lxc(vmid).interfaces.get()
    for iface in interfaces:
        if iface["name"] == "lo":
            continue  # skip loopback
        for addr in iface.get("ip-addresses", []):
            if addr["ip-address-type"] in ["ipv4", "inet"]:
                return addr["ip-address"]
    return None


def get_lxc_user(api, node, vmid):
    result = api.nodes(node).lxc(vmid).agent.post("exec", command="who")
    pid = result["pid"]
    status = api.nodes(node).qemu(vmid).agent("exec-status").get(pid=pid)
    err_data = status.get("err-data", None)
    if err_data:
        raise ProxmoxError(f"failed to fetch vm user: {err_data}")

    user = status.get("out-data").split(maxsplit=1)[0]
    return user


def get_vm_user(api, node, vmid):
    result = api.nodes(node).qemu(vmid).agent.post("exec", command="who")
    pid = result["pid"]
    status = api.nodes(node).qemu(vmid).agent("exec-status").get(pid=pid)
    err_data = status.get("err-data", None)
    if err_data:
        raise ProxmoxError(f"failed to fetch vm user: {err_data}")

    user = status.get("out-data").split(maxsplit=1)[0]
    return user


def get_standalone_node(api) -> NodeEntity:
    nodes = api.nodes.get()
    if len(nodes) > 1:
        names = [node["node"] for node in nodes]
        raise ProxmoxError(f"expected a single node but found {names}")
    return nodes[0]
