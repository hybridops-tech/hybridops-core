# GKE Cluster

Creates or converges a GKE cluster on the governed GCP hub network.

This module expects the target subnetwork and GKE secondary ranges to exist already.
The intended upstream source is `org/gcp/wan-hub-network` with:

- `subnet_workloads_name`
- `subnet_workloads_pods_secondary_range_name`
- `subnet_workloads_services_secondary_range_name`

Recommended flow:

1. Reconcile `org/gcp/wan-hub-network` with workload secondary ranges enabled.
2. Apply `platform/gcp/gke-cluster`.
3. Apply `platform/gcp/gke-kubeconfig`.
4. Reuse `platform/k8s/argocd-bootstrap` for the first burst baseline.
5. Add a cloud-native secret-store layer separately when the target workloads actually need it.

Key inputs:

- `network_state_ref`
- `location`
- `master_authorized_networks`
- `enable_private_nodes`
- `enable_private_endpoint`
- `node_count`
- `machine_type`
- `node_service_account` (optional external override; a dedicated node service account is created by default)

Important:

- public control-plane access is only allowed when `master_authorized_networks` is explicitly set
- the default starter profile is intentionally small (`1 x e2-standard-2`) so burst/bootstrap paths fit constrained project quota more reliably
- this module does not generate kubeconfig; use `platform/gcp/gke-kubeconfig`
- the shipped `gcp/gke-burst@v1` blueprint intentionally stops at GitOps bootstrap for a stateless burst baseline; do not force the on-prem `gsm-bootstrap` pattern into GKE solely to satisfy a temporary secret-store dependency
