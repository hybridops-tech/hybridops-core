# platform/k8s/longhorn-dr-volume

Observe Longhorn backup state and manage Longhorn DR volumes from backup URLs.

This module is a DR primitive for Longhorn-backed Kubernetes targets. It is intended
for restore preparation and recovery orchestration, not normal day-2 workload storage
management.

What it does:
- resolves a Longhorn backup by `backup_name` or direct `backup_url`
- publishes backup metadata that can be used for freshness and readiness gates
- can create or update a Longhorn standby DR volume from that backup
- can create or update an active Longhorn restore volume from that backup
- can activate an existing standby volume by clearing `Standby`
- can remove the managed Longhorn volume on `destroy`

What it does not do:
- it does not provision a Kubernetes cluster
- it does not install Longhorn
- it does not create application PVCs or rebind workloads
- it does not cut DNS
- it does not replace application-specific recovery validation

Promotion boundary:
- this module is a reusable restore primitive, not a complete application failover workflow
- merge it on its own merits
- add application-specific DR blueprints only when the target cluster and workloads recovery path are real

## Operation Modes

- `observe`
  - resolve backup metadata only
  - recommended first step for backup freshness gates
- `standby`
  - create or update a Longhorn standby DR volume from the resolved backup URL
  - useful for `warm-standby` recovery lanes
- `restore`
  - create or update an active Longhorn restore volume from the resolved backup URL
  - useful for `restore-baseline` recovery lanes on Longhorn-backed targets
- `activate`
  - promote an existing standby volume by setting `Standby=false` and enabling the frontend

## Required Inputs

Always required:
- `kubeconfig_path`
- `kubectl_bin`
- `longhorn_namespace`
- `operation_mode`

For `observe`, `standby`, or `restore`:
- one of:
  - `backup_name`
  - `backup_url`

For `standby`, `restore`, or `activate`:
- `restore_volume_name`

## Restore Readiness

This module publishes a conservative readiness contract:
- `restore_volume_ready=true` only when the Longhorn `Restore` condition is `False`
- otherwise the module publishes the current Longhorn status fields and a reason string

Longhorn still exposes `restoreRequired` and `restoreInitiated`, but those fields are
published as informational status only. They are not the readiness gate because live
restore testing showed `restoreInitiated` can remain `true` after the `Restore`
condition has already settled.

This keeps Core DR gates honest. A created or patched volume is not automatically
considered ready.

## Outputs

Backup metadata:
- `backup_name`
- `backup_url`
- `backup_state`
- `backup_created_at`
- `backup_last_synced_at`
- `backup_target_name`
- `source_longhorn_volume_name`
- `source_pvc_namespace`
- `source_pvc_name`

Restore volume metadata:
- `restore_volume_name`
- `restore_volume_size`
- `restore_volume_state`
- `restore_volume_robustness`
- `restore_condition_status`
- `restore_volume_is_standby`
- `restore_volume_restore_required`
- `restore_volume_restore_initiated`
- `restore_volume_ready`
- `restore_volume_ready_reason`

`restore_condition_status` mirrors the raw Longhorn `Restore` condition value.

Capability output:
- `cap.k8s.longhorn_dr_volume = ready`

## Usage

Observe backup state:

```bash
hyops validate --env <env> --skip-preflight \
  --module platform/k8s/longhorn-dr-volume \
  --inputs modules/platform/k8s/longhorn-dr-volume/examples/inputs.observe.yml
```

Create a standby DR volume:

```bash
hyops apply --env <env> \
  --module platform/k8s/longhorn-dr-volume \
  --inputs modules/platform/k8s/longhorn-dr-volume/examples/inputs.standby.yml
```

Promote an existing standby volume:

```bash
HYOPS_INPUT_operation_mode=activate \
hyops apply --env <env> \
  --module platform/k8s/longhorn-dr-volume \
  --inputs modules/platform/k8s/longhorn-dr-volume/examples/inputs.standby.yml
```

Validator smoke example:

```bash
hyops validate --env <env> --skip-preflight \
  --module platform/k8s/longhorn-dr-volume \
  --inputs modules/platform/k8s/longhorn-dr-volume/tests/example-inputs.yml
```
