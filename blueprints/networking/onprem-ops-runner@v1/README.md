# On-Prem Ops Runner

Provision and bootstrap an on-prem runner VM for runner-local failback and steady-state platform operations.

Outcome: a shared execution host exists on the on-prem management network for failback or local platform workflows.

## Chain

```text
core/onprem/template-image
  -> platform/onprem/platform-vm
  -> platform/linux/ops-runner
```

See [blueprint.yml](blueprint.yml) for the full contract.

## Usage

```bash
hyops blueprint validate --ref networking/onprem-ops-runner@v1 --blueprints-root blueprints
hyops blueprint preflight --env dev --ref networking/onprem-ops-runner@v1 --blueprints-root blueprints
hyops blueprint deploy --env dev --ref networking/onprem-ops-runner@v1 --blueprints-root blueprints --execute
```
