# platform/network/edge-observability

Deploy edge observability services (Thanos, Grafana, Alertmanager) on Linux edge nodes.

This module configures runtime services only. It does not provision infrastructure.

## What it does

- Installs and manages:
  - Thanos Receive
  - Thanos Query
  - Thanos Store Gateway
  - Grafana
  - Alertmanager
  - Thanos Ruler (optional)
- Writes module state capability for blueprint dependency checks.

## What it does not do

- Does not create object storage buckets.
- Does not create cloud credentials.
- Does not orchestrate WAN or DR cutover modules.

## Required secrets

- `EDGE_OBS_GRAFANA_ADMIN_PASSWORD`
- `EDGE_OBS_OBJSTORE_CONFIG`

Use vault-backed flows:

```bash
hyops secrets ensure --env <env> EDGE_OBS_GRAFANA_ADMIN_PASSWORD EDGE_OBS_OBJSTORE_CONFIG
```

## Usage

```bash
hyops preflight --env <env> --strict \
  --module platform/network/edge-observability \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/edge-observability/examples/inputs.min.yml"

hyops apply --env <env> \
  --module platform/network/edge-observability \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/edge-observability/examples/inputs.min.yml"
```

State-driven inventory example:

```bash
hyops apply --env <env> \
  --module platform/network/edge-observability \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/edge-observability/examples/inputs.state.yml"
```
