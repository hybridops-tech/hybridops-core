# Packer Image Driver Notes

## Purpose

Define the current `images/packer` driver boundary inside HybridOps.Core.

HybridOps.Core owns the runtime contract for image builds:

- module inputs and outputs
- run-record behaviour
- normalized template outputs for downstream VM modules
- env-scoped runtime paths under `~/.hybridops`

The driver contract is self-contained within HybridOps.Core.

## Driver semantics to preserve

- Proxmox init provides API/token plus storage and bridge discovery used by packer builds.
- Build orchestration supports `build`, `purge`, and `rebuild` by template key.
- Each run produces a stable run record with chain and run correlation.
- Template families include Linux and Windows with rendered unattended assets.

## Core target model

- Driver family: `images/packer`
- Image build modules produce normalized template outputs such as template VM ID and name.
- VM modules consume image outputs through state rather than hardcoded IDs.
- Runtime logs and state remain env-scoped under `~/.hybridops/envs/<env>/`.

## Current scope

- ship the packer driver contracts and pack layout in HybridOps.Core
- validate inputs
- render unattended assets
- run `packer init`, `packer validate`, and `packer build`
- publish normalized outputs for VM modules and follow-on workflows

## Non-goals

- depending on external source-tree paths at runtime
- requiring extra repository context to build or verify HybridOps.Core
- expanding the shipped product boundary beyond the current driver contract
- broad cloud image migration notes beyond the current driver scope
