<!--
Purpose: Define how workbench work is promoted into HybridOps.Core modules.
Architecture Decision: ADR-0622
Maintainer: HybridOps.Studio
-->

# RB-030 — Module lifecycle

HybridOps.Core ships **modules** as the product unit. Workbench remains the integration environment.

## Status tiers

- **draft**: functional in a controlled environment; interface may change.
- **candidate**: stable enough for repeated operator runs and Academy labs.
- **released**: versioned, supported, and eligible for packaging.

## Promotion checklist (minimum)

A module is eligible for promotion when it provides:

- `spec.yml` with explicit requirements and inputs.
- `probes/run.sh` that returns pass/fail and writes `probes/summary.txt`.
- Evidence output under `output/artifacts/core/modules/<epoch>/<module>/<run_id>/`.
- A minimal `README.md` pointing to canonical docs.

## Backward compatibility

- Module IDs are stable once a module reaches **candidate**.
- Inputs in `spec.yml` are treated as an interface contract.
