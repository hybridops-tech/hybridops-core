# platform/network/edge-observability

Deploy the edge observability stack on Linux control nodes.

This module configures runtime services only. It does not provision infrastructure.
The apply path now verifies that enabled containers stay running and that the
published HTTP endpoints for Thanos Query, Grafana, and Alertmanager are healthy
before module state is marked `ok`.

## What it does

- Installs and manages:
  - Local Prometheus (optional)
  - Blackbox Exporter probe targets (optional)
  - Thanos Sidecar for local Prometheus query fan-in (optional)
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

## Local metrics mode

For burst control and edge decision loops, the module can run a local probe path:

- Blackbox Exporter probes primary and burst origins
- Prometheus scrapes those probe metrics locally
- Thanos Sidecar exposes Prometheus data to local Thanos Query
- Prometheus needs unique external labels for the sidecar; the role derives stable labels from the HyOps env and host name unless you set `edge_obs_prometheus_external_labels` explicitly
- decision-service can keep using `http://127.0.0.1:10902`

This gives the control plane a fast local signal path even before a broader
remote-write topology is deployed.

## Required secrets

- Always:
  - `EDGE_OBS_GRAFANA_ADMIN_PASSWORD`
- Only when receive/store/ruler are enabled:
  - `EDGE_OBS_OBJSTORE_CONFIG`

Use vault-backed flows:

```bash
hyops secrets ensure --env <env> EDGE_OBS_GRAFANA_ADMIN_PASSWORD
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

## Operational notes

- Grafana and Alertmanager use non-root container users. The module reconciles
  bind-mounted host paths to the expected service ownership before startup.
- If the module reports `ok`, the enabled services are not only started through
  Docker Compose; they have also passed the built-in readiness checks.
