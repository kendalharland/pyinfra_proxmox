
from typing_extensions import override
from pyinfra.api import FactBase
from pyinfra_proxmox.inventory import ProxmoxEntity, list_proxmox_entities, ProxmoxApiSettings

class IsApiHost(FactBase):
    """Returns true iff the given host is a Proxmox instance."""
    command = "test -d /etc/pve && echo 1 || echo 0"

    @override
    def process(self, result) -> bool:
        return result and result == ["1"]

class Entities(FactBase):
    requires_facts = ("IsHost",)

    # Garbage command; We use the API to fetch the entity list.
    command = "echo 1"

    @override
    def check_preconditions(self, _, host) -> str | None:
        if not host.get_fact(IsApiHost):
            return "not a Proxmox host"

        settings = ProxmoxApiSettings.from_host_data(host.data.dict())

        if not settings.hostname:
            return "no hostname is configured"

        self.api = settings.api()

    @override
    def process(self, _) -> list[ProxmoxEntity]:
        return list_proxmox_entities(self.api)