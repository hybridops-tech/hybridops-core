# Runtime Contract: NetBox Export Hook

## Purpose

Defines the runtime contract for module-level `execution.hooks.export_infra` when using the Terragrunt driver and Core NetBox exporter.

## Required Runtime Inputs

- `HYOPS_RUNTIME_ROOT`: root for runtime state, logs, and artifacts.
- `HYOPS_EXPORT_HOOK_ROOT`: hook execution Terragrunt root (defaults to `.` from profile).

## NetBox API Inputs (for import tools)

- `NETBOX_API_URL`
- `NETBOX_API_TOKEN`
- Optional fallback file: `CONTROL_SECRETS_ENV` (defaults to `credentials/netbox.env` under runtime root).

## Hook Execution Contract

Terragrunt profile command should call:

`python3 -m hyops.drivers.inventory.netbox.tools.export_infra --target {target} --terragrunt-root {hook_root} --only-module . --changed-only`

Module opt-in contract:

```yaml
execution:
  hooks:
    export_infra:
      enabled: true
      strict: false
      push_to_netbox: false
```

- `enabled: true` runs export hook after successful apply.
- `strict: false` records warning on hook failure and does not fail apply.
- `strict: true` fails apply when hook fails.


When `push_to_netbox: true`, hidden fail-fast checks are enforced automatically:

- export hook command must succeed
- dataset (`NETBOX_VMS_AUTO_JSON` / `NETBOX_VMS_AUTO_CSV`) must exist and contain rows
- `NETBOX_API_URL` and `NETBOX_API_TOKEN` must be present
- profile `netbox_sync_command` must exist and return success

## Output Paths (default)

All paths are rooted at runtime root unless overridden:

- `state/netbox/vms/vms.auto.csv`
- `state/netbox/vms/vms.auto.json`
- `state/netbox/network/ipam-prefixes.csv`
- `state/netbox/network/ipam-prefixes.json`
- `logs/netbox/terraform/...`
- `artifacts/netbox/terraform/...`

## Validation and Smoke Commands

From `hybridops-core`:

- `PYTHONPYCACHEPREFIX=/tmp/hyops-pyc python3 -m compileall -q hyops`
- `python3 -m hyops.drivers.inventory.netbox.tools.export_infra --list-targets`

Dry-run style execution against a stack path:

- `HYOPS_RUNTIME_ROOT=/tmp/hyops-netbox-e2e PYTHONPATH=$(pwd) python3 -m hyops.drivers.inventory.netbox.tools.export_infra --target cloud-azure --terragrunt-root packs/iac/terragrunt/azure/core/00-foundation-global/10-resource-group@v1.0/stack --only-module . --changed-only`

If no Terraform state exists yet, exporter reports `no outputs or not deployed` and exits successfully.
