# GKE Kubeconfig

Fetches kubeconfig for an existing GKE cluster into the HyOps runtime state tree.

Recommended input contract:

- `cluster_state_ref: "platform/gcp/gke-cluster#<instance>"`

This module publishes `kubeconfig_path`, which can then be consumed by:

- `platform/k8s/argocd-bootstrap`
- `platform/k8s/gsm-bootstrap` when a cluster-specific secret-store bootstrap path is actually part of the target workload baseline

If `inputs.kubeconfig_path` is not set, HyOps writes:

- `~/.hybridops/envs/<env>/state/kubeconfigs/<cluster_name>.yaml`

The target kubeconfig file is rewritten on each successful apply. HyOps does not preserve older cluster
contexts in that file, because a named runtime kubeconfig is expected to represent one current cluster.

Notes:

- The controller running this module must already have usable `gcloud` credentials.
- The `gke-gcloud-auth-plugin` binary is required and is installed by `hyops setup cloud-gcp --sudo`.
- This module fails early when:
  - the cluster project is billing-blocked or the active account cannot describe the cluster
  - the public control-plane endpoint is not reachable from the current machine
- If the control plane is intentionally private or reachable only from another execution surface, fetch kubeconfig from a prepared runner instead of forcing workstation access.
