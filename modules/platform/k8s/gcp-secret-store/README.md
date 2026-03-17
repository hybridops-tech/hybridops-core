# platform/k8s/gcp-secret-store

Bootstraps a `ClusterSecretStore` on GKE using GCP Workload Identity rather than a static Secret Manager key secret.

What it does:

- ensures the target GCP project has `secretmanager.googleapis.com` enabled
- installs the External Secrets CRD bundle when it is not already present
- creates a Kubernetes service account for External Secrets Operator in `external-secrets`
- grants that Kubernetes principal `roles/secretmanager.secretAccessor` on the target GCP project
- applies a `ClusterSecretStore` named `gcp-secret-manager`
- waits for the store to report `Ready`

Recommended flow:

1. Apply `platform/gcp/gke-cluster`.
2. Apply `platform/gcp/gke-kubeconfig`.
3. Bootstrap `platform/external-secrets` on the cluster.
4. Apply `platform/k8s/gcp-secret-store`.
5. Add workloads that consume `gcp-secret-manager`.

Important:

- this module is for GKE and cloud-native Secret Manager access
- it expects the External Secrets operator app to exist, but it can install the official CRD bundle itself so the Helm app does not need to manage oversized CRDs
- it does not write a long-lived GCP key into the cluster
- the on-prem `platform/k8s/gsm-bootstrap` module remains the right path for on-prem clusters using a bootstrap key pattern

Outputs:

- `secret_store_name`
- `service_account_name`
- `service_account_namespace`
- `secret_project_id`
- `cap.k8s.gcp-secret-store = ready`
