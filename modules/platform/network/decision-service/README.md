# platform/network/decision-service

Deploys a deterministic decision service on edge Linux nodes.

This is the control-loop surface for DR/burst policy execution.

## v1 scope

- Runs a local decision loop service (systemd) on edge control nodes.
- Queries Thanos Query HTTP API (`/api/v1/query`) for policy signals.
- Evaluates thresholds with confirm/stable/cooldown timing guards.
- Can execute `hyops apply` actions when enabled.
- Writes state/action evidence to local filesystem.

## Deployment topology

Recommended topology is to run decision-service on the same edge VM as Thanos Query:

- site Prometheus -> Thanos Receive (fresh ingest)
- Thanos Receive/Store Gateway -> object storage (durability)
- Thanos Query -> Receive + Store Gateway
- decision-service -> local Thanos Query (`http://127.0.0.1:10902`)

This keeps decision latency low and avoids direct bucket API dependencies in control logic.

## Action execution model

- `dry_run=true`: no actions executed.
- `decision_enable_actions=false`: no actions executed.
- `dry_run=false` + `decision_enable_actions=true`: actions can execute after:
  - threshold breach/healthy windows
  - confirm/stable timers
  - cooldown guard
  - signal readiness/freshness guards (when enabled)

Actions currently target `platform/network/dns-routing` with base inputs in:
- `actions.module_inputs`
- `actions.module_inputs` must include dns-routing inventory contract (`inventory_groups` or `inventory_state_ref` + `inventory_vm_groups`).

## Signal readiness and freshness guards

Use these inputs to fail closed:

- `decision_require_signal_readiness` (default: `true`)
- `decision_require_fresh_signals` (default: `true`)
- `decision_max_signal_age_s` (default: `180`)
- `decision_min_ready_checks` (default: `1`)

When guards fail, the service records `signal_ready=false` and blocks actions.

## Usage

```bash
hyops preflight --env <env> --strict \
  --module platform/network/decision-service \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/decision-service/examples/inputs.min.yml"

hyops apply --env <env> \
  --module platform/network/decision-service \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/decision-service/examples/inputs.min.yml"
```

Destroy:

```bash
hyops destroy --env <env> \
  --module platform/network/decision-service \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/decision-service/examples/inputs.min.yml"
```
