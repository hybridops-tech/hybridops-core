"""
purpose: Terragrunt module contract registry.
Architecture Decision: ADR-N/A (terragrunt contracts)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

from .base import TerragruntModuleContract
from .gcp_project_factory import GcpProjectFactoryContract
from .network_sdn import NetworkSdnContract
from .proxmox_vm import ProxmoxVmContract


_proxmox_vm = ProxmoxVmContract()
_gcp_project_factory = GcpProjectFactoryContract()
_CONTRACTS = {
    "core/onprem/network-sdn": NetworkSdnContract(),
    "platform/onprem/platform-vm": _proxmox_vm,
    "platform/onprem/control-node": _proxmox_vm,
    "platform/onprem/netbox": _proxmox_vm,
    "platform/onprem/postgresql-core": _proxmox_vm,
    "platform/onprem/eve-ng": _proxmox_vm,
    "org/gcp/project-factory": _gcp_project_factory,
}


def get_contract(module_ref: str) -> TerragruntModuleContract:
    return _CONTRACTS.get(module_ref, TerragruntModuleContract())
