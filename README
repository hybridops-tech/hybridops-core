<!--
Purpose: Product runtime distribution for HybridOps.Studio.
Architecture Decision: ADR-0622
Maintainer: HybridOps.Studio
-->

# HybridOps.Core

HybridOps.Core is the **shippable runtime** for HybridOps.Studio: a contract-driven automation product that runs **modules** through **drivers** under a single, explicit **runtime root**.

This repository ships the product runtime (code + packaged assets).  
All documentation lives on the public portal: **[docs.hybridops.studio](https://docs.hybridops.studio)**.

## What you get

- `hyops` CLI — stable operator interface.
- **Modules** — declarative intent contracts (`spec.yml`) with defaults and execution selection.
- **Drivers** — execution engines (Terragrunt/Terraform, Packer, Ansible, etc.) that run modules and produce deterministic evidence.
- **Profiles** — versioned policies (defaults) that control driver behaviour without changing modules.
- **Runtime standards** — stable paths for config, credentials, evidence, and state.

## Runtime root

Commands that write runtime artefacts MUST use this precedence:

1. `--root <path>`
2. `$HYOPS_RUNTIME_ROOT`
3. `~/.hybridops`

Outputs (evidence, readiness, state) are written under the runtime root unless explicitly overridden (e.g. `--out-dir` for evidence).

## Quick start

Install (recommended):

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install .
```

Initialize targets (examples):

```bash
hyops init proxmox
hyops init terraform-cloud
hyops init gcp
```

Run a module:

```bash
hyops apply --module examples/core/hello-world
```

Override runtime root (optional):

```bash
hyops apply --root /tmp/hyops-test --module examples/core/hello-world
```

Provide inputs (optional):

```bash
hyops apply --module examples/core/hello-world --inputs modules/examples/core/hello-world/tests/example-inputs.yml
```

## Evidence and operational artefacts

HybridOps.Core is evidence-first. Runs write deterministic, non-secret artefacts.

Canonical evidence structure:

- Init:   `<root>/logs/init/<target>/<run_id>/`
- Module: `<root>/logs/module/<module_id>/<run_id>/`
- Driver: `<root>/logs/driver/<driver_id>/<run_id>/`

Readiness markers:

- `<root>/meta/<target>.ready.json`

Runtime stamp (best-effort, non-fatal):

- `<root>/meta/runtime.json`

## Repository layout

```text
hybridops-core/
├── hyops/                # product runtime package (CLI, runtime services)
├── drivers/              # driver implementations + profiles + templates (packaged assets)
├── modules/              # module specs + probes + examples (packaged contracts)
├── tools/                # setup + helper scripts (tarball-safe)
├── pyproject.toml
└── README.md
```

## Documentation and support

- Documentation portal: **[docs.hybridops.studio](https://docs.hybridops.studio)**
- Evidence bundles produced by `hyops` are intended to support review and troubleshooting.

## License

- Code: MIT-0
