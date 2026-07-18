# GCP Ops Runner

Provision a private GCP runner VM in the hub core subnet for runner-local DR and burst execution.

Outcome: a shared execution host exists inside the GCP hub VPC for CI or decision-driven workflows.

## Chain

```text
org/gcp/wan-cloud-nat
  -> platform/gcp/platform-vm
  -> platform/linux/ops-runner
```

See [blueprint.yml](blueprint.yml) for the full contract.

## Usage

```bash
hyops blueprint validate --ref networking/gcp-ops-runner@v1 --blueprints-root blueprints
hyops blueprint preflight --env <env> --ref networking/gcp-ops-runner@v1 --blueprints-root blueprints
hyops blueprint deploy --env <env> --ref networking/gcp-ops-runner@v1 --blueprints-root blueprints --execute
```
