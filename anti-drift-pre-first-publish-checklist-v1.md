# HybridOps.Core — Pre-First-Publish Checklist (Anti-Drift Note v1)

This note is the authoritative **pre-first-publish checklist** for HybridOps.Core.

If a release candidate fails any **MUST** item below, treat it as **not publishable**.
If an implementation change conflicts with this note, treat it as drift and reconcile before proceeding.

This note is intentionally operational. It exists to stop “it worked on my machine” behavior from leaking into the first public package.

---

## 1. Scope

Applies to:

- `hyops` CLI behavior
- runtime layout under `~/.hybridops`
- module and blueprint authoring
- profile/driver execution behavior
- tarball packaging and install behavior
- validator and preflight behavior
- runner-local execution model
- docs required to operate the packaged product

Out of scope:

- long-term roadmap items not required for first publish
- future premium packs not yet shipped
- CI/CD maturity beyond what is needed to prove package integrity

---

## 2. Publish Gate

The first publish is allowed only when all of these are true:

- packaged install path is the primary supported path
- all shipped workflows are runnable without Git repository assumptions
- all stateful commands require explicit runtime selection
- blueprints are shipped as immutable templates and executed from env overlays only
- destroy paths for cost-bearing resources are verified, not assumed
- external secret authority and runtime vault cache roles are clearly separated in code and docs
- docs match the actual packaged workflow

---

## 3. Tarball-Safe Rules

### 3.1 Packaging

- **MUST** support install and operation from a packaged release, not only a source checkout.
- **MUST NOT** require `.git`, local repo-relative assumptions, or ad hoc developer shell state.
- **MUST** keep runtime data outside the shipped payload.
- **MUST** treat shipped blueprints and packs as canonical templates/assets.

### 3.2 Runtime layout

- **MUST** write mutable data only under runtime root, especially:
  - `config/`
  - `credentials/`
  - `vault/`
  - `meta/`
  - `logs/`
  - `state/`
  - `work/`
- **MUST NOT** write operator-edited files back into the shipped blueprint tree.
- **MUST NOT** require operators to edit files inside `hybridops-core/`.

### 3.3 Release bootstrap

- **MUST** support current dev bootstrap via unpacked release root.
- **SHOULD** support versioned release archive bootstrap for disposable runners once the first package is published.
- **MUST NOT** make source checkout paths the long-term product contract.

---

## 4. Module vs Blueprint Boundary

### 4.1 Modules

- **MUST** remain atomic lifecycle/capability units.
- **MUST NOT** silently embed unrelated orchestration logic.
- **MUST** publish normalized state contracts when they are intended for downstream consumption.

### 4.2 Blueprints

- **MUST** represent composition, ordering, policy, or a real lifecycle across modules.
- **MUST NOT** exist merely as a thin one-module wrapper unless there is a defensible product reason.
- **SHOULD** use `blueprint init` + env-scoped overlays for operator customization.

### 4.3 Current first-publish stance

- runner blueprints **MUST** compose:
  - egress adapter
  - runner host lifecycle
  - runner bootstrap lifecycle
- DR blueprints **MUST** consume upstream state rather than duplicate IPs or topology details where a clean state contract exists.

---

## 5. Runtime Selection and State Safety

- **MUST** require explicit runtime selection for stateful commands (`--env`, `--root`, or runtime env var).
- **MUST NOT** fall back silently to a bare `~/.hybridops` global namespace for stateful operations.
- **MUST** fail clearly when required upstream state is absent, stale, destroyed, or in the wrong env.
- **MUST** keep env-scoped rerun inputs in runtime config, not transient workdirs.

Required examples already proven or expected:

- env-scoped module rerun input files
- env-scoped blueprint overlays
- instance-scoped state where modules are intentionally multi-instance

---

## 6. Validator and Preflight Discipline

- **MUST** fail fast on placeholder values.
- **MUST** fail fast on mutually exclusive inputs.
- **MUST** fail fast when a state reference cannot be resolved in the selected runtime.
- **MUST** catch known connectivity preconditions before expensive apply phases where possible.
- **MUST** surface the real blocking reason, not a generic driver failure, when a better diagnosis is available.

Examples that matter for first publish:

- NetBox/IPAM gating
- bucket naming and repo state refs
- runner SSH access mode correctness
- cloud network/firewall prerequisites
- workspace/backend namespace mismatches

---

## 7. Blueprint Overlay Rules

- shipped blueprints **MUST** be treated as immutable templates
- env-specific copies **MUST** live under:
  - `~/.hybridops/envs/<env>/config/blueprints/`
- `hyops blueprint init` **SHOULD** be the default operator path
- `hyops blueprint preflight/deploy --file ...` **MUST** reject files outside the env overlay directory
- packaged/install-time blueprint payload **SHOULD** be read-only as a hardening layer

---

## 8. Secret Authority Boundary

- **MUST** distinguish clearly between:
  - external secret authority (for example HashiCorp Vault)
  - runtime vault cache (`<root>/vault/bootstrap.vault.env`)
- **MUST NOT** treat the runtime vault cache as the long-term source of truth.
- **MUST** allow runner-local execution to refresh required secrets from an external authority before dispatch.
- **MUST NOT** make DR execution depend on an operator laptop shell exporting secrets by hand.

This is a publish blocker because mutable shipped blueprints invite uncontrolled drift.

---

## 8. Runner-Local Execution Rules

- runner-local is the preferred cross-cloud execution posture
- bastion is a fallback, not the primary execution model
- workstation-direct execution is acceptable for development only, not the target DR story
- cloud database and workload VMs **SHOULD** remain private-only by default
- per-target runners are preferred over a single global runner
- a central coordinator/dispatcher is allowed, but it **MUST NOT** become the only private execution plane

### Provider composition rule

- provider-specific runner blueprints **MUST** compose explicit layers in this order:
  - egress adapter
  - runner host lifecycle
  - generic runner bootstrap
- runner job dispatch **MUST** live in the HyOps CLI/orchestration layer, not inside modules and not as a thin convenience blueprint
- provider-specific access and egress behavior **MUST NOT** be hidden inside the generic runner bootstrap module
- the generic runner bootstrap module **MUST** stay provider-agnostic so the same lifecycle can be reused for GCP, Azure, AWS, and Proxmox

### Current execution-plane stance

- GCP runner path is first
- Proxmox/on-prem runner is next for failback symmetry
- Azure/AWS runners follow the same pattern

### GCP project-role discipline

- **MUST** keep GCP project roles explicit where more than one project is used.
- **MUST NOT** let docs or blueprints imply that a single `project_id` owns:
  - Shared VPC / NAT
  - runner placement
  - env-scoped secret authority
  - env-scoped object repositories
  - future workload projects
- **SHOULD** describe the preferred split as:
  - `host/network project`
  - `control project`
  - `workload project` (optional later)

---

## 9. Cost and Destroy Safety

- Any cloud-spend-bearing workflow **MUST** have a verified destroy path before publish.
- Destroy behavior **MUST** be documented where cost exposure is non-trivial.
- Destructive data purges **MUST NOT** be hidden inside routine destroy or rerun flows.
- Backup purge, bucket purge, or repo reset behavior **MUST** remain explicit and opt-in.

Examples already expected:

- runner VM create/destroy
- object repo state-slot safety
- backup mismatch reset as an explicit operator action

---

## 10. DR Product Shape for First Publish

### 10.1 Default lane

The publishable baseline is:

- on-prem Patroni HA
- off-site pgBackRest object repo
- restore to self-managed cloud VMs
- controlled failback to on-prem

### 10.2 Premium lane

Managed database DR **MUST** remain a separate product lane and separate contract family.

- **MUST NOT** be mixed into the baseline self-managed restore path
- **MAY** exist as contract/docs before full implementation

### 10.3 Decision service

- **MUST NOT** be required to prove the baseline DR lane
- **SHOULD** come after the baseline DR path is proven end to end

---

## 11. Documentation Publish Gate

The following docs **MUST** be aligned before first publish:

- install/bootstrap path
- runtime/env model
- module/blueprint operator workflow
- runner-local execution model
- default PostgreSQL DR lane
- NetBox/IPAM bootstrap and authority rules
- cloud object repo / backup workflow

Documentation **MUST** describe:

- packaged path first
- source-checkout path as development context only
- when operator overlays are required
- when destroy is required for cost control

If the real product path requires a command not documented in the packaged workflow, treat that as drift.

---

## 12. Evidence and Rehearsal Gate

Before first publish, the following **SHOULD** have evidence directories from real runs:

- packaged install
- NetBox bootstrap
- PostgreSQL HA deploy
- PostgreSQL HA backup to object repo
- runner VM create
- runner VM destroy
- runner blueprint create/bootstrap preflight at minimum
- RKE2 deploy
- at least one workload bootstrap/GitOps flow

If a path is documented as supported but has never been run successfully in this environment, mark it clearly as unproven or do not ship it as ready.

---

## 13. Known Acceptable Temporary States Before First Publish

These are acceptable only if they are documented as temporary and do not leak into the package contract:

- source-checkout use of `HYOPS_CORE_ROOT` during pre-package validation
- placeholder blueprint values in shipped templates
- managed DR documented as future/premium contract but not yet shipped as active module path

These are **not** acceptable:

- repo-root operator files
- mutable shipped blueprints as the working copy
- runtime writes back into package assets
- hidden reliance on a developer laptop or Git checkout

---

## 14. Final Sanity Questions Before Publish

Before shipping, ask:

1. Can a user install and operate this from the package without our repo checkout?
2. If a command fails, does it fail with a clear operator-actionable reason?
3. If a cloud resource is created, has destroy been verified?
4. Are blueprints real compositions rather than convenience wrappers?
5. Are env overlays and state contracts doing the real work instead of ad hoc files?
6. Do docs reflect the packaged product path rather than our dev habits?

If any answer is “no”, do not publish yet.
