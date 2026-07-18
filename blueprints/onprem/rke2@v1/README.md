# On-Prem RKE2 Cluster

Build the base template, provision RKE2 VMs, and install an on-prem RKE2 cluster.

Outcome: RKE2 is installed and kubeconfig is exported for operators.

## Chain

```text
core/onprem/template-image
  -> platform/onprem/platform-vm
  -> platform/onprem/rke2-cluster
```

See [blueprint.yml](blueprint.yml) for the full contract.

## Usage

```bash
hyops blueprint validate --ref onprem/rke2@v1 --blueprints-root blueprints
hyops blueprint preflight --env <env> --ref onprem/rke2@v1 --blueprints-root blueprints
hyops blueprint deploy --env <env> --ref onprem/rke2@v1 --blueprints-root blueprints --execute
```
