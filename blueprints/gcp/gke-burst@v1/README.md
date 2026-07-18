# GCP GKE Burst Cluster

Create a governed GKE burst cluster on the shared hub network, fetch kubeconfig, bootstrap Argo CD, and configure the GCP Secret Manager store.

Outcome: a burst-ready GKE cluster is available and rooted on the public workloads baseline under `clusters/burst`.

## Chain

```text
platform/gcp/gke-cluster
  -> platform/gcp/gke-kubeconfig
  -> platform/k8s/argocd-bootstrap
  -> platform/k8s/gcp-secret-store
```

See [blueprint.yml](blueprint.yml) for the full contract.

## Usage

```bash
hyops blueprint validate --ref gcp/gke-burst@v1 --blueprints-root blueprints
hyops blueprint preflight --env <env> --ref gcp/gke-burst@v1 --blueprints-root blueprints
hyops blueprint deploy --env <env> --ref gcp/gke-burst@v1 --blueprints-root blueprints --execute
```
