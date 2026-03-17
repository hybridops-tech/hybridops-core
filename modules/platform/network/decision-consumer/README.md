# platform/network/decision-consumer

Deploy a deterministic decision consumer on the shared control host.

## What it does

- Runs a local consumer service under `systemd`.
- Watches dispatcher request files under `/opt/hybridops/decision-dispatcher/state/requests`.
- Waits for approval markers when a request requires approval.
- Emits normalized execution records under `/opt/hybridops/decision-consumer/state/executions`.

## What it does not do in v1

- It does not execute `hyops`.
- It does not mutate dispatcher request files.
- It does not replace the runner model.

Current v1 execution mode is:

- `approval-only`

That means the service promotes approved requests into execution records that a later runner-aware executor can consume.

## Why it exists

The control-plane split is deliberate:

1. `platform/network/decision-service` evaluates signals and emits a decision record.
2. `platform/network/decision-dispatcher` turns that record into a routed dispatch request.
3. `platform/network/decision-consumer` waits for approval and writes an execution record.
4. a later executor runs the approved record through the correct runner/module path.

This keeps policy evaluation, routing, approval, and execution as separate concerns.

## Usage

```bash
hyops validate --env dev \
  --module platform/network/decision-consumer \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/decision-consumer/examples/inputs.min.yml"

hyops apply --env dev \
  --module platform/network/decision-consumer \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/decision-consumer/examples/inputs.min.yml"
```
