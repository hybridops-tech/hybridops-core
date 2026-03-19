# platform/network/decision-service

Deploy a deterministic edge decision service for burst and failover control loops.

This module turns live observability signals into gated operational actions.

## What it does

- Runs a local decision loop service (systemd) on edge control nodes.
- Queries a Prometheus-compatible HTTP API (`/api/v1/query`) for policy signals.
- Evaluates thresholds with confirm/stable/cooldown timing guards.
- Emits structured decision records for downstream automation.
- Can execute approved `hyops apply` actions locally when explicitly enabled.
- Writes service state, decision records, and local action results to filesystem.

## Runtime model

HybridOps installs this service with an Ansible role and runs it under `systemd`.

That model is intentional for the current product shape because decision-service
is a small host-local control-plane process:

- no container runtime dependency
- simple lifecycle under the shared control host
- easy integration with local Thanos Query, PowerDNS, and runner services

If container packaging is added later, the module contract should remain the same.

## Deployment topology

Recommended topology is to run decision-service on the same edge VM as Thanos Query:

- site Prometheus -> Thanos Receive (fresh ingest), or local edge probes -> Prometheus -> Thanos Sidecar
- Thanos Receive/Store Gateway -> object storage (durability)
- Thanos Query -> Receive + Store Gateway + Sidecar
- decision-service -> local query API (`http://127.0.0.1:10902`)

This keeps decision latency low and avoids direct bucket API dependencies in control logic.

## Operating modes

Default mode is `emit-only`:

- decision service writes a decision record under `state/records/`
- a runner or workflow engine consumes that record
- no local `hyops apply` is executed by default

Optional automation mode is `local-hyops`:

- decision service still emits a decision record
- local `hyops apply` is allowed only when:
  - `dry_run=false`
  - `decision_enable_actions=true`
  - threshold breach/healthy windows are met
  - confirm/stable timers are met
  - cooldown guard is clear
  - signal readiness/freshness guards are satisfied
  - module state guards are satisfied when enabled or configured
  - the host has an installed HybridOps release plus a minimal runtime root

Execution summary:

- `dry_run=true`: no local actions executed
- `decision_enable_actions=false`: no local actions executed
- `dry_run=false` + `decision_enable_actions=true`: local actions can execute only after the configured
  decision, freshness, cooldown, and state-guard checks pass

Actions can target any module ref the edge runtime can execute. Common current cases
are `platform/network/dns-routing` and `platform/network/cloudflare-traffic-steering`.
Base action inputs are supplied in:

- `actions.module_inputs`

`actions.module_inputs` must satisfy the target module's normal execution contract.

Example burst-steering path:

- `cutover_module_ref: platform/network/cloudflare-traffic-steering`
- `failback_module_ref: platform/network/cloudflare-traffic-steering`
- `cutover_desired: balanced`
- `failback_desired: primary`

That lets the decision loop move a single public host between:

- primary Pages delivery
- weighted same-host split
- full burst-origin delivery

## Metrics and demo signal path

When `decision_service_metrics_enabled=true`, the service exposes a local
Prometheus-format endpoint. This is intended for edge-local observability and
for dashboards that need to show the decision loop in real time.

Key inputs:

- `decision_service_metrics_enabled`
- `decision_service_metrics_bind_host`
- `decision_service_metrics_port`

Key exported metrics:

- `hyops_burst_demo_pressure`
- `hyops_burst_demo_active`
- `hyops_decision_degraded`
- `hyops_decision_mode`
- `hyops_decision_recommended_action`
- `hyops_decision_check_value`
- `hyops_decision_check_ok`
- `hyops_decision_check_sample_age_seconds`

When `decision_service_demo_signal_enabled=true`, the role also installs a
controlled demo helper on the edge host:

- `/opt/hybridops/decision-service/decision-demo-signal`

Typical operator flow:

```bash
ssh <edge-host> sudo /opt/hybridops/decision-service/decision-demo-signal set \
  --pressure 100 \
  --ttl-s 120 \
  --note "showcase burst trigger"

ssh <edge-host> sudo /opt/hybridops/decision-service/decision-demo-signal clear
```

This helper is meant for demos and controlled rehearsals. In production policy,
`burst_pressure_query` can point at any Prometheus-compatible signal that
represents real load or saturation pressure.

## Signal readiness and freshness guards

Use these inputs to fail closed when signals are incomplete or stale:

- `decision_require_signal_readiness` (default: `true`)
- `decision_require_fresh_signals` (default: `true`)
- `decision_max_signal_age_s` (default: `180`)
- `decision_min_ready_checks` (default: `1`)

When guards fail, the service records `signal_ready=false` and blocks actions.

## Module state guards

Use these inputs to block actions until prerequisite module states are ready:

- `decision_require_action_state_guards` (default: `false`)
- `decision_runtime_root` (optional explicit runtime root override)
- `actions.module_state_guards.cutover`
- `actions.module_state_guards.failback`

If `decision_runtime_root` is unset, the service reads module state from:
- `~/.hybridops/envs/<decision_runtime_env>`

If `decision_runtime_root` is set, the service reads and writes state there instead.
For Cloudflare steering actions, a minimal local runtime root only needs:

- `<runtime_root>/meta/`
- `<runtime_root>/credentials/cloudflare.credentials.tfvars`
- the required API token exposed in the service environment

Each guard item supports:
- `state_ref`
- `require_status` (default: `ok`)
- `outputs_equal`
- `outputs_non_empty`

Typical uses:

- require a restore or replica module to be `ok`
- require published outputs such as `restore_volume_ready=true`
- block DNS or traffic-steering actions until those guards pass

See:
- `modules/platform/network/decision-service/examples/inputs.dr-gates.yml`
- `modules/platform/network/decision-service/examples/inputs.cloudflare-burst.yml`

## True burst steering example

`inputs.cloudflare-burst.yml` is the reference pattern for a same-host burst
story:

- one public hostname
- Cloudflare traffic steering as the execution target
- probe-based health and latency checks
- optional `burst_pressure_query` for load-driven promotion to balanced traffic

In that pattern, decision-service does not publish a second demo hostname. It
changes the live delivery state for a single public host.

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
