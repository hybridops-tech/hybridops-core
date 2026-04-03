# HybridOps.Core

HybridOps.Core is the **shippable runtime** for HybridOps: a contract-driven automation product that runs **modules** through **drivers** under a single, explicit **runtime root**.

This repository ships the product runtime (code + packaged assets).
Full documentation is at **[docs.hybridops.tech](https://docs.hybridops.tech)**.

## What you get

- `hyops` CLI — stable operator interface.
- **Modules** — declarative intent contracts (`spec.yml`) with driver selection and input defaults.
- **Drivers** — execution engines (Terragrunt/Terraform, Packer, Ansible) that run modules and produce deterministic run records.
- **Profiles** — versioned driver policies that control behaviour without modifying module specs.
- **Packs** — versioned, driver-specific execution assets (playbooks, Terraform stacks, templates).
- **Blueprints** — ordered module sequences for repeatable multi-step deployments.
- **Runtime standards** — stable paths for config, credentials, run records, and state.

## Requirements

- Python ≥ 3.11
- Tools required vary by module: `terraform`, `terragrunt`, `ansible`, `packer`, `gcloud`, `kubectl` — only the tools used by the modules you run need to be present.

## Quick start

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install .
```

Initialise a target:

```bash
hyops init gcp --env dev
hyops init proxmox --env dev
```

Run a module:

```bash
hyops apply --env dev --module org/gcp/project-factory
```

The runtime root defaults to `~/.hybridops`. Override with `--root <path>` or `$HYOPS_RUNTIME_ROOT`.

## Run records

Every `hyops` command writes structured, non-secret run records for review and troubleshooting:

```
<root>/logs/init/<target>/<run_id>/
<root>/logs/module/<module_id>/<run_id>/
```

Readiness markers are written to `<root>/meta/<target>.ready.json` after a successful `hyops init`.

## Repository layout

```text
hybridops-core/
├── hyops/          # CLI and runtime package (drivers, runtime services)
├── modules/        # module specs (spec.yml, probes, examples)
├── packs/          # versioned execution assets (playbooks, Terraform stacks, templates)
├── blueprints/     # ordered module sequences for multi-step deployments
├── tools/          # setup and helper scripts
├── install.sh      # convenience installer
└── pyproject.toml
```

## Documentation and support

- **Docs:** [docs.hybridops.tech](https://docs.hybridops.tech)
- **Security reports:** [security@hybridops.tech](mailto:security@hybridops.tech) — see [SECURITY.md](.github/SECURITY.md)
- **Issues:** use the repository issue tracker for bugs and feature requests

This repository is the **community edition**. SME and Enterprise tiers — including full documentation access, operator training, and guided rollout — are available at [hybridops.tech](https://hybridops.tech).

## License

Code: [MIT-0](LICENSE)
