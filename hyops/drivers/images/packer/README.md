# Packer Image Driver Migration Notes

## Purpose
Define the migration boundary for Proxmox template image builds from legacy workbench tooling into `hyops-core` without modifying legacy sources.

## Source Of Truth Read-Only Inputs
- `hybridops-workbench/infra/packer-multi-os/`
- `hybridops-workbench/control/tools/provision/packer/`

## Legacy Semantics To Preserve
- Proxmox init provides API/token + storage/bridge discovery used by packer builds.
- Build orchestration supports `build`, `purge`, `rebuild` by template key.
- Evidence is produced per run with stable chain/run correlation.
- Template families include Linux and Windows with rendered unattended files.

## Core Target Model
- Driver family: `images/packer`.
- Module intent remains generic and capability-driven:
  - image build modules produce template outputs (for example template VM ID/name).
  - VM modules consume image outputs through state, not hardcoded IDs.
- Runtime/evidence layout must remain env-scoped under `~/.hybridops/envs/<env>/`.

## Phase 1 Implementation Scope
- Keep legacy packer trees read-only.
- Add `hyops-core` packer driver contracts and pack layout.
- Add one Proxmox image module chain:
  - validate inputs
  - render unattended assets
  - run `packer init/validate/build`
  - publish normalized outputs for VM modules.

## Non-Goals For Phase 1
- No modifications to workbench packer code.
- No remote bootstrap script migration (already handled by `hyops init proxmox`).
- No cloud provider image migration (Azure/GCP/etc.) in this phase.
