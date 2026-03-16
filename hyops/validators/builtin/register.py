"""
purpose: Register built-in module validators.
Architecture Decision: ADR-0206 (module execution contract v1)
maintainer: HybridOps.Studio
"""

from __future__ import annotations

from hyops.validators.registry import register
from hyops.validators.core.azure import nat_gateway, resource_group, vnet
from hyops.validators.core.hetzner import vyos_image_register, vyos_image_seed
from hyops.validators.core.onprem import network_sdn, template_image, vyos_template_import, vyos_template_seed
from hyops.validators.core.shared import manual_gate, vyos_image_artifact, vyos_image_build
from hyops.validators.org.aws import pgbackrest_repo as aws_pgbackrest_repo
from hyops.validators.org.azure import pgbackrest_repo as azure_pgbackrest_repo
from hyops.validators.org.gcp import (
    cloudsql_external_replica,
    cloudsql_postgresql,
    pgbackrest_repo,
    project_factory,
    wan_cloud_router,
    wan_hub_network,
    wan_vpn_to_edge,
)
from hyops.validators.org.hetzner import shared_control_host, vyos_edge_foundation, wan_edge_foundation
from hyops.validators.platform.azure import container_registry
from hyops.validators.platform.network import (
    decision_service,
    dns_routing,
    edge_observability,
    vyos_edge_wan,
)
from hyops.validators.platform.gcp import platform_vm as gcp_platform_vm
from hyops.validators.platform.onprem import (
    argocd_bootstrap,
    control_node,
    eve_ng,
    netbox,
    platform_vm,
    postgresql_core,
    postgresql_dr_source,
    postgresql_ha,
    postgresql_ha_backup,
    netbox_db_migrate,
    nfs_appliance,
    rke2_cluster,
    vyos_edge,
)


def register_all() -> None:
    register("org/aws/object-repo", aws_pgbackrest_repo.validate)
    register("org/aws/pgbackrest-repo", aws_pgbackrest_repo.validate)
    register("org/azure/object-repo", azure_pgbackrest_repo.validate)
    register("org/azure/pgbackrest-repo", azure_pgbackrest_repo.validate)
    register("org/gcp/cloudsql-external-replica", cloudsql_external_replica.validate)
    register("org/gcp/cloudsql-postgresql", cloudsql_postgresql.validate)
    register("org/gcp/object-repo", pgbackrest_repo.validate)
    register("org/gcp/project-factory", project_factory.validate)
    register("org/gcp/wan-hub-network", wan_hub_network.validate)
    register("org/gcp/wan-cloud-router", wan_cloud_router.validate)
    register("org/gcp/wan-vpn-to-edge", wan_vpn_to_edge.validate)
    register("org/hetzner/shared-control-host", shared_control_host.validate)
    register("org/hetzner/vyos-edge-foundation", vyos_edge_foundation.validate)
    register("org/hetzner/wan-edge-foundation", wan_edge_foundation.validate)
    register("org/gcp/pgbackrest-repo", pgbackrest_repo.validate)
    register("core/azure/resource-group", resource_group.validate)
    register("core/azure/vnet", vnet.validate)
    register("core/azure/nat-gateway", nat_gateway.validate)
    register("core/hetzner/vyos-image-seed", vyos_image_seed.validate)
    register("core/hetzner/vyos-image-register", vyos_image_register.validate)
    register("core/onprem/network-sdn", network_sdn.validate)
    register("core/onprem/template-image", template_image.validate)
    register("core/onprem/vyos-template-import", vyos_template_import.validate)
    register("core/onprem/vyos-template-seed", vyos_template_seed.validate)
    register("core/shared/manual-gate", manual_gate.validate)
    register("core/shared/vyos-image-artifact", vyos_image_artifact.validate)
    register("core/shared/vyos-image-build", vyos_image_build.validate)
    register("platform/azure/container-registry", container_registry.validate)
    register("platform/gcp/platform-vm", gcp_platform_vm.validate)
    register("platform/network/vyos-edge-wan", vyos_edge_wan.validate)
    register("platform/network/edge-observability", edge_observability.validate)
    register("platform/network/decision-service", decision_service.validate)
    register("platform/network/dns-routing", dns_routing.validate)
    register("platform/onprem/argocd-bootstrap", argocd_bootstrap.validate)
    register("platform/k8s/argocd-bootstrap", argocd_bootstrap.validate)
    register("platform/onprem/control-node", control_node.validate)
    register("platform/onprem/eve-ng", eve_ng.validate)
    register("platform/onprem/netbox", netbox.validate)
    register("platform/onprem/platform-vm", platform_vm.validate)
    register("platform/onprem/postgresql-core", postgresql_core.validate)
    register("platform/onprem/postgresql-dr-source", postgresql_dr_source.validate)
    register("platform/postgresql-ha", postgresql_ha.validate)
    register("platform/onprem/postgresql-ha", postgresql_ha.validate)
    register("platform/postgresql-ha-backup", postgresql_ha_backup.validate)
    register("platform/onprem/postgresql-ha-backup", postgresql_ha_backup.validate)
    register("platform/onprem/netbox-db-migrate", netbox_db_migrate.validate)
    register("platform/onprem/nfs-appliance", nfs_appliance.validate)
    register("platform/onprem/rke2-cluster", rke2_cluster.validate)
    register("platform/onprem/vyos-edge", vyos_edge.validate)
