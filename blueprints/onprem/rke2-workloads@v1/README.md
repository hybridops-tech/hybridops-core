# On-Prem RKE2 + Workloads Bootstrap

Provision RKE2 VMs, install RKE2, bootstrap Argo CD, and publish the GSM bootstrap secret for External Secrets Operator.

Outcome: RKE2 is ready, Argo CD points to the workloads repository, and the GSM service-account secret is present for ESO.

## Chain

```text
core/onprem/template-image
  -> platform/onprem/platform-vm
  -> platform/onprem/rke2-cluster
  -> platform/k8s/argocd-bootstrap
  -> platform/k8s/gsm-bootstrap
```

See [blueprint.yml](blueprint.yml) for the full contract.

## Usage

```bash
hyops blueprint validate --ref onprem/rke2-workloads@v1 --blueprints-root blueprints
hyops blueprint preflight --env <env> --ref onprem/rke2-workloads@v1 --blueprints-root blueprints
hyops blueprint deploy --env <env> --ref onprem/rke2-workloads@v1 --blueprints-root blueprints --execute
```
