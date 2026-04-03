# platform/network/decision-executor

Deploy a deterministic decision executor on edge Linux nodes.

This module consumes approved execution records produced by
`platform/network/decision-consumer` and stages normalized execution-attempt
records for later real execution planes.

## v1 scope

- Runs a local executor service under `systemd`.
- Watches execution records under `/opt/hybridops/decision-consumer/state/executions`.
- Writes dry-run execution-attempt records under `/opt/hybridops/decision-executor/state/attempts`.
- Defaults to `dry-run`; it does not invoke HybridOps, runners, or CI systems.

## Runtime model

HybridOps installs this service with an Ansible role and runs it under
`systemd`, alongside decision service, dispatcher, and consumer on the shared
control host.

This keeps the control loop explicit:

- decision service evaluates signals and emits records
- decision dispatcher turns those records into dispatch requests
- decision consumer applies approval posture and emits execution records
- decision executor turns approved execution records into dry-run execution attempts

## Execution mode

The shipped mode is `dry-run`.

That means:

- every approved execution record produces an execution-attempt record
- target metadata is preserved for a future runner or workflow adapter
- no local `hyops apply`, `hyops runner`, or GitHub Actions call is performed

Future execution modes may add real runner or workflow dispatch, but the first
release posture is deliberately non-destructive.

## Usage

```bash
hyops preflight --env <env> --strict \
  --module platform/network/decision-executor \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/decision-executor/examples/inputs.min.yml"

hyops apply --env <env> \
  --module platform/network/decision-executor \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/decision-executor/examples/inputs.min.yml"
```

Destroy:

```bash
hyops destroy --env <env> \
  --module platform/network/decision-executor \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/decision-executor/examples/inputs.min.yml"
```
