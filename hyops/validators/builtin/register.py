"""
purpose: Register built-in module validators.
Architecture Decision: ADR-0206 (module execution contract v1)
maintainer: HybridOps.Tech
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
from hyops.validators.org.hetzner import (
    shared_control_host,
    shared_private_network,
    vyos_edge_foundation,
    wan_edge_foundation,
)
from hyops.validators.platform.azure import container_registry
from hyops.validators.platform.k8s import longhorn_dr_volume, runtime_bundle_secret
from hyops.validators.platform.network import (
    decision_consumer,
    decision_executor,
    decision_dispatcher,
    decision_service,
    dns_routing,
    edge_observability,
    vyos_edge_wan,
)
from hyops.validators.platform.gcp import platform_vm as gcp_platform_vm
from hyops.validators.platform.gcp import gke_cluster, gke_kubeconfig
from hyops.validators.platform.k8s import gcp_secret_store, gsm_bootstrap
from hyops.validators.platform.linux import (
    eve_ng as linux_eve_ng,
    eve_ng_healthcheck,
    eve_ng_images,
    eve_ng_labs,
)
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
    register("org/hetzner/shared-private-network", shared_private_network.validate)
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
    register("platform/gcp/gke-cluster", gke_cluster.validate)
    register("platform/gcp/gke-kubeconfig", gke_kubeconfig.validate)
    register("platform/linux/eve-ng", linux_eve_ng.validate)
    register("platform/linux/eve-ng-images", eve_ng_images.validate)
    register("platform/linux/eve-ng-labs", eve_ng_labs.validate)
    register("platform/linux/eve-ng-healthcheck", eve_ng_healthcheck.validate)
    register("platform/network/vyos-edge-wan", vyos_edge_wan.validate)
    register("platform/network/edge-observability", edge_observability.validate)
    register("platform/network/decision-consumer", decision_consumer.validate)
    register("platform/network/decision-executor", decision_executor.validate)
    register("platform/network/decision-dispatcher", decision_dispatcher.validate)
    register("platform/network/decision-service", decision_service.validate)
    register("platform/network/dns-routing", dns_routing.validate)
    register("platform/onprem/argocd-bootstrap", argocd_bootstrap.validate)
    register("platform/k8s/argocd-bootstrap", argocd_bootstrap.validate)
    register("platform/k8s/runtime-bundle-secret", runtime_bundle_secret.validate)
    register("platform/k8s/longhorn-dr-volume", longhorn_dr_volume.validate)
    register("platform/k8s/gcp-secret-store", gcp_secret_store.validate)
    register("platform/k8s/gsm-bootstrap", gsm_bootstrap.validate)
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
    register("platform/onprem/rke2-cluster", rke2_cluster.validate)
    register("platform/onprem/vyos-edge", vyos_edge.validate)
