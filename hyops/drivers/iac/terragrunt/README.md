# Terragrunt Driver

This driver executes Terragrunt packs from `packs/iac/terragrunt/...` using a selected profile.

## Workspace Policy (Terraform Cloud)

Profiles may define `workspace_policy`:

- `enabled`: turn policy enforcement on/off.
- `provider`: workspace naming provider segment (for example `azure`, `gcp`).
- `mode`: target execution mode (`local`, `remote`, `agent`).
- `strict`: when `true`, policy failures stop apply; when `false`, they are warnings.

When enabled, the driver:

1. Computes workspace name from module context.
2. Runs `terragrunt init`.
3. Calls Terraform Cloud API to ensure workspace execution mode (workspace must already exist, or policy emits a warning/error depending on `strict`).
4. Stores outcome in the run record as `workspace_policy.json`.

This replaces the legacy external workspace execution-mode script path.

Notes:

- Workspace creation is a separate operator action (`hyops tfc workspace-ensure`) so workspaces can be bootstrapped headlessly without the Terraform Cloud GUI.
- The driver persists backend/Terraform Cloud binding metadata in module state (`execution.backend`) and blocks accidental drift for the same module state slot by default.
- Intentional backend/workspace migrations require explicit override:
  - `HYOPS_ALLOW_BACKEND_BINDING_DRIFT=1`
  - followed by Terraform import/reconciliation as needed.

## Command Behavior

- `hyops apply` / `hyops deploy`: runs `terragrunt init` then `terragrunt apply`.
- `hyops plan`: runs `terragrunt init` then `terragrunt plan`.
- `hyops validate`: runs `terragrunt init` then `terragrunt validate`.
- `hyops preflight --module ...`: runs driver contract checks without terragrunt execution.
- Export hooks are executed only for `apply`/`deploy`.

By default, `hyops apply|deploy|plan|validate` runs driver preflight first and fails fast on contract errors. Use `--skip-preflight` only for controlled troubleshooting.

Terraform provider cache:

- By default, the driver reuses the shared runtime plugin cache under `~/.hybridops/envs/<env>/cache/terraform/plugins`.
- Set `HYOPS_TERRAFORM_ISOLATE_PLUGIN_CACHE=1` only when you intentionally need a per-run cache for provider-install troubleshooting.

## Module Sources

Packs use explicit `module_source` values in their `terragrunt.hcl` files.

Use one explicit source per pack (no fallback chains in shipped config), preferably pinned by tag or commit:

- `git::https://github.com/hybridops-tech/hybridops-terraform-gitmods.git//<provider>/<module>?ref=<tag>`

Use `//subdir` syntax for modules that reference sibling modules (for example `proxmox/vm-multi` -> `../vm`) so Terragrunt/Terraform fetch the full module tree.

## Export Hook (Spec-driven)

Profiles may define `hooks.export_infra` with a command template. Modules opt in via:

- `execution.hooks.export_infra.enabled`
- `execution.hooks.export_infra.target` (optional; inferred from module provider when omitted)
- `execution.hooks.export_infra.strict` (`true` fails apply, `false` adds warning)
- `execution.hooks.export_infra.push_to_netbox` (`true` enables fail-fast dataset + NetBox sync enforcement)

Execution behavior:

1. Terragrunt apply completes.
2. If enabled, driver runs the configured export hook command.
3. Run-record files are written to `hook_export_infra.*`.
4. Non-strict hook failures are warnings; strict failures stop apply.

When `push_to_netbox` is enabled, the driver enforces fail-fast behavior: export hook must succeed, dataset must exist and contain rows, NetBox env vars must be present, and NetBox sync command must return success.

Core ships a generic NetBox export tool at `hyops.drivers.inventory.netbox.tools.export_infra`; profiles can reference it directly or point to another integration package.

## Dependency Outputs Contract

`hyops apply` and `hyops deploy` persist module state at:

- `<runtime_root>/state/modules/<module_id>/latest.json`

Only outputs listed in `spec.outputs.publish` are persisted and made available for downstream imports.

Modules can import upstream outputs with:

- `dependencies[].module_ref`
- `dependencies[].required`
- `dependencies[].imports` (`<upstream_output>` -> `<local_input_path>`)

Dependency imports are merged after defaults and before operator overrides.

## Backend Binding Guard (State Slot Sanity)

For Terragrunt-backed modules, HyOps now records backend binding metadata in module state:

- `execution.backend.mode` (`local` or `cloud`)
- `execution.backend.terraform_cloud.host`
- `execution.backend.terraform_cloud.org`
- `execution.backend.terraform_cloud.workspace_name`
- when a resolved `project_id` changes for a Terraform Cloud-backed GCP lane, HyOps keeps the current derived workspace name and allows a controlled rehome instead of preserving the legacy workspace alias
- when an older GCP module state did not publish `project_id`, HyOps now infers the prior project from published self links and connection names so project-move drift is still detected early

On later runs for the same module state slot (same module + `state_instance`), the driver compares the newly derived binding to the prior state and fails fast on mismatch. This prevents accidental cross-namespace writes (for example, `--env dev` state slot drifting to a `shared` Terraform Cloud workspace because `WORKSPACE_PREFIX`, `context_id`, or `TFC_ORG` changed).

Legacy module states without `execution.backend` are allowed once (warning only); the next successful run persists the binding.
If a prior state slot already uses a Terraform Cloud workspace name from an older naming scheme, HyOps preserves that workspace name when the current derivation is only a compatibility-equivalent form. This covers both the shortened workspace formatter and the known `hybridops-*` to `platform-*` prefix migration, so existing state slots stay bound to the original workspace instead of drifting during naming-policy upgrades.
