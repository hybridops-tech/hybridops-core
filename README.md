# HybridOps Core

**Run reproducible infrastructure on Proxmox, Hetzner, GCP, AWS, Azure, and local — with DR, Kubernetes HA, and hybrid WAN — from a single CLI and a contract-driven module system.**

[![License: MIT-0](https://img.shields.io/badge/license-MIT--0-blue.svg)](LICENSE)
[![Python ≥ 3.11](https://img.shields.io/badge/python-%E2%89%A53.11-blue)](https://www.python.org/)
[![CI](https://github.com/hybridops-tech/hybridops-core/actions/workflows/ci.yml/badge.svg)](https://github.com/hybridops-tech/hybridops-core/actions/workflows/ci.yml)

---

| 70 modules | 24 blueprints | 60 decision records | 6 deployment surfaces |
|:---:|:---:|:---:|:---:|

---

## What this is

HybridOps Core is the automation runtime behind a hybrid infrastructure platform that runs across **Proxmox, Hetzner, GCP, AWS, Azure, and local** environments.

Each module carries a declarative intent contract (`spec.yml`). A CLI (`hyops`) resolves the contract, selects a driver (Terragrunt, Ansible, Packer), executes it, and writes a structured run record. Blueprints sequence modules into repeatable multi-step deployments.

The platform is validated end to end — not just tested in isolation. Every scenario below has a recorded walkthrough.

## Proven scenarios

| Scenario | What it delivers |
|---|---|
| **Authoritative on-prem foundation** | NetBox as IPAM + inventory source of truth, Proxmox SDN as the routed network baseline |
| **PostgreSQL HA failover and failback** | Patroni + pgBackRest — GCP recovery in 12 min, controlled failback in 40 min |
| **RKE2 HA platform foundation** | Three-node RKE2 cluster + Argo CD GitOps delivery on Proxmox |
| **Hybrid WAN edge and site extension** | VyOS HA pair on Hetzner, BGP peering to GCP HA VPN, on-prem site extension |
| **Managed PostgreSQL DR with Cloud SQL** | External replica standby on GCP, explicit promotion, controlled failback |
| **Hybrid portal burst to GKE** | Identity-gated workload burst from on-prem to GKE under load |
| **Secret delivery pipeline** | GCP Secret Manager → ESO → Kubernetes Secret on RKE2 and GKE |
| **Governed network emulation** | EVE-NG as a managed lab platform on GCP (nested virtualisation) or Proxmox |

Walkthroughs, architecture diagrams, and platform-state captures for each scenario: **[docs.hybridops.tech/showcases](https://docs.hybridops.tech/showcases)**

## Quick start

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install .
```

Initialise a target environment:

```bash
hyops init proxmox --env dev
hyops init gcp --env dev
```

Run a module:

```bash
hyops apply --env dev --module platform/onprem/rke2-cluster
hyops apply --env dev --module org/gcp/project-factory
```

Run a full blueprint (ordered multi-step deployment):

```bash
hyops blueprint run --env dev --blueprint onprem/rke2@v1
```

The runtime root defaults to `~/.hybridops`. Override with `--root <path>` or `$HYOPS_RUNTIME_ROOT`.

## How it works

```
spec.yml  →  hyops apply  →  driver (Terragrunt / Ansible / Packer)  →  run record
```

- **Modules** declare intent in `spec.yml` — inputs, driver selection, defaults. No driver logic lives in the spec.
- **Drivers** execute against a resolved module contract and write structured run records to `<root>/logs/`.
- **Profiles** are versioned driver policies — control behaviour without touching module specs.
- **Packs** are the versioned execution assets (Terraform stacks, Ansible playbooks, Packer templates).
- **Blueprints** sequence modules into repeatable multi-step deployments with explicit ordering.

Every `hyops` command writes a non-secret structured run record:

```
~/.hybridops/logs/module/<module_id>/<run_id>/
~/.hybridops/logs/init/<target>/<run_id>/
```

## Repository layout

```
hybridops-core/
├── hyops/       # CLI and runtime (drivers, runtime services)
├── modules/     # 70 module specs (spec.yml, probes, examples)
├── blueprints/  # 24 blueprints for multi-step deployments
├── packs/       # versioned execution assets
├── tools/       # setup and helper scripts
├── install.sh
└── pyproject.toml
```

## Requirements

- Python ≥ 3.11
- Tool dependencies vary by module: `terraform`, `terragrunt`, `ansible`, `packer`, `gcloud`, `kubectl` — only the tools used by the modules you run need to be present

## Documentation

- **Full docs and showcases:** [docs.hybridops.tech](https://docs.hybridops.tech)
- **Public site:** [hybridops.tech](https://hybridops.tech)
- **Security reports:** [security@hybridops.tech](mailto:security@hybridops.tech) — see [SECURITY.md](.github/SECURITY.md)
- **Bugs and feature requests:** use the issue tracker

## Editions

This repository is the **community edition** (MIT-0).

SME and Enterprise tiers — including full documentation access, operator training, and guided rollout — are available at [hybridops.tech](https://hybridops.tech).

## License

[MIT-0](LICENSE)
