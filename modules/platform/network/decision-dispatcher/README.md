# platform/network/decision-dispatcher

Deploy a deterministic decision dispatcher on edge Linux nodes.

This module consumes structured decision records produced by
`platform/network/decision-service` and stages normalized dispatch requests for
runner-driven DR and burst execution.

## v1 scope

- Runs a local dispatcher service under `systemd`.
- Watches the decision record directory written by decision service.
- Writes normalized dispatch requests under `state/requests/`.
- Defaults to `record-only`; it does not execute HybridOps directly.

## Runtime model

HybridOps installs this service with an Ansible role and runs it under
`systemd`, alongside decision service and edge observability on the shared
control host.

This keeps the control plane simple:

- decision service evaluates signals and emits records
- decision dispatcher normalizes those records into execution requests
- a runner or workflow engine can consume those requests later

## Execution mode

The shipped mode is `record-only`.

That means:

- every matching decision record produces a dispatch request
- approval posture is captured in the request
- no local `hyops apply` or `hyops runner` command is executed by the dispatcher

Future execution modes may be added later, but the default release posture is
deliberately non-destructive.

## Route contract

`dispatcher_routes` is a mapping keyed by the emitted decision type, for
example:

```yaml
dispatcher_routes:
  cutover:
    target_kind: blueprint
    target_ref: dr/postgresql-ha-failover-gcp@v1
    target_env: dev
    execution_plane: runner-local
    requires_approval: true
  failback:
    target_kind: blueprint
    target_ref: dr/postgresql-ha-failback-onprem@v1
    target_env: dev
    execution_plane: runner-local
    requires_approval: true
```

These routes do not execute anything in v1. They define the normalized request
shape a future runner or workflow engine should consume.

## Usage

```bash
hyops preflight --env <env> --strict \
  --module platform/network/decision-dispatcher \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/decision-dispatcher/examples/inputs.min.yml"

hyops apply --env <env> \
  --module platform/network/decision-dispatcher \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/decision-dispatcher/examples/inputs.min.yml"
```

Destroy:

```bash
hyops destroy --env <env> \
  --module platform/network/decision-dispatcher \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/decision-dispatcher/examples/inputs.min.yml"
```
