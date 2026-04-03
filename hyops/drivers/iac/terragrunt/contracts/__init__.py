"""
purpose: Terragrunt module contract registry.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from .base import TerragruntModuleContract
from .gcp_cloudsql_postgresql import GcpCloudSqlPostgresqlContract
from .gcp_project_factory import GcpProjectFactoryContract
from .gcp_wan_vpn_to_edge import GcpWanVpnToEdgeContract
from .hetzner_servers import HetznerServerStateContract
from .network_sdn import NetworkSdnContract
from .proxmox_vm import ProxmoxVmContract


_proxmox_vm = ProxmoxVmContract()
_gcp_cloudsql_postgresql = GcpCloudSqlPostgresqlContract()
_gcp_project_factory = GcpProjectFactoryContract()
_gcp_wan_vpn_to_edge = GcpWanVpnToEdgeContract()
_hetzner_servers = HetznerServerStateContract()
_CONTRACTS = {
    "core/onprem/network-sdn": NetworkSdnContract(),
    "platform/onprem/platform-vm": _proxmox_vm,
    "platform/onprem/control-node": _proxmox_vm,
    "platform/onprem/vyos-edge": _proxmox_vm,
    "platform/onprem/netbox": _proxmox_vm,
    "platform/onprem/postgresql-core": _proxmox_vm,
    "platform/onprem/eve-ng": _proxmox_vm,
    "org/gcp/cloudsql-postgresql": _gcp_cloudsql_postgresql,
    "org/gcp/project-factory": _gcp_project_factory,
    "org/gcp/wan-vpn-to-edge": _gcp_wan_vpn_to_edge,
    "org/hetzner/vyos-edge-foundation": _hetzner_servers,
    "org/hetzner/shared-control-host": _hetzner_servers,
}


def get_contract(module_ref: str) -> TerragruntModuleContract:
    return _CONTRACTS.get(module_ref, TerragruntModuleContract())
