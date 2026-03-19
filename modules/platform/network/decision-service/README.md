# platform/network/decision-service

Deploys a deterministic decision service on edge Linux nodes.

This is the control-loop surface for DR/burst policy execution.

## v1 scope

- Runs a local decision loop service (systemd) on edge control nodes.
- Queries Thanos Query HTTP API (`/api/v1/query`) for policy signals.
- Evaluates thresholds with confirm/stable/cooldown timing guards.
- Emits structured decision records for runner consumption by default.
- Can execute `hyops apply` locally only in explicit transitional mode.
- Writes service state, decision records, and local action results to filesystem.

## Runtime model

HybridOps installs this service with an Ansible role and runs it under `systemd`.

This is the preferred shipping model for now because decision service is a small
host-local control-plane process:

- no container runtime dependency
- simple lifecycle under the shared control host
- easy integration with local Thanos Query, PowerDNS, and runner services

If container packaging is added later, the module contract should stay the same.

## Deployment topology

Recommended topology is to run decision-service on the same edge VM as Thanos Query:

- site Prometheus -> Thanos Receive (fresh ingest)
- Thanos Receive/Store Gateway -> object storage (durability)
- Thanos Query -> Receive + Store Gateway
- decision-service -> local Thanos Query (`http://127.0.0.1:10902`)

This keeps decision latency low and avoids direct bucket API dependencies in control logic.

## Execution model

Default shipped mode is `emit-only`:

- decision service writes a decision record under `state/records/`
- a runner or workflow engine is expected to consume that record
- no local `hyops apply` is executed by default

Optional transitional mode is `local-hyops`:

- decision service still emits a decision record
- local `hyops apply` is allowed only when:
  - `dry_run=false`
  - `decision_enable_actions=true`
  - threshold breach/healthy windows are met
  - confirm/stable timers are met
  - cooldown guard is clear
  - signal readiness/freshness guards are satisfied
  - module state guards are satisfied when enabled or configured

Execution summary:

- `dry_run=true`: no local actions executed
- `decision_enable_actions=false`: no local actions executed
- `dry_run=false` + `decision_enable_actions=true`: local actions can execute only after the configured
  decision, freshness, cooldown, and state-guard checks pass

Actions can target any module ref the edge runtime can execute. Common current cases
are `platform/network/dns-routing` and `platform/network/cloudflare-traffic-steering`,
with base inputs in:
- `actions.module_inputs`
- `actions.module_inputs` must include the target module's normal execution contract

Example burst-steering path:

- `cutover_module_ref: platform/network/cloudflare-traffic-steering`
- `failback_module_ref: platform/network/cloudflare-traffic-steering`
- `cutover_desired: balanced`
- `failback_desired: primary`

That lets the decision loop move a single public host between:

- primary Pages delivery
- weighted same-host split
- full burst-origin delivery

## Signal readiness and freshness guards

Use these inputs to fail closed:

- `decision_require_signal_readiness` (default: `true`)
- `decision_require_fresh_signals` (default: `true`)
- `decision_max_signal_age_s` (default: `180`)
- `decision_min_ready_checks` (default: `1`)

When guards fail, the service records `signal_ready=false` and blocks actions.

## Module State Guards

Use these inputs to block actions until prerequisite module states are ready:

- `decision_require_action_state_guards` (default: `false`)
- `decision_runtime_root` (optional explicit runtime root override)
- `actions.module_state_guards.cutover`
- `actions.module_state_guards.failback`

If `decision_runtime_root` is unset, the service reads module state from:
- `~/.hybridops/envs/<decision_runtime_env>`

Each guard item supports:
- `state_ref`
- `require_status` (default: `ok`)
- `outputs_equal`
- `outputs_non_empty`

Typical use:
- require PostgreSQL restore state to be `ok`
- require Longhorn restore state to publish `restore_volume_ready=true`
- require DNS cutover targets to stay blocked until those guards pass

See:
- `modules/platform/network/decision-service/examples/inputs.dr-gates.yml`
- `modules/platform/network/decision-service/examples/inputs.cloudflare-burst.yml`

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
