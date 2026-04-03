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
- Prometheus needs unique external labels for the sidecar; the role derives stable labels from the HybridOps env and host name unless you set `edge_obs_prometheus_external_labels` explicitly
- decision-service can keep using `http://127.0.0.1:10902`

This gives the control plane a fast local signal path even before a broader
remote-write topology is deployed.

## Burst dashboard path

For burst-control demos and operator review, the module can also provision a
Grafana dashboard sourced from the local Thanos Query path.

Relevant inputs:

- `edge_obs_enable_decision_service_scrape`
- `edge_obs_decision_service_metrics_host`
- `edge_obs_decision_service_metrics_port`
- `edge_obs_enable_burst_dashboard`
- `edge_obs_burst_dashboard_title`

When enabled:

- Prometheus scrapes decision-service metrics directly from the host
- Thanos Query exposes those metrics through the existing Grafana datasource
- Grafana provisions a dashboard showing burst pressure, degraded state, probe
  health, latency, and current decision mode

This is the intended capture path for the burst showcase because it lets the
operator show the metric spike, the decision transition, and the traffic-state
change without switching tools.

## Public DNS-backed access

The module can optionally publish Grafana and Thanos Query behind a small
reverse proxy on the control host.

This is the preferred demo and operator path because:

- raw service ports stay loopback-only on the host
- the reverse proxy owns `80` and `443`
- Cloudflare or another public front door can point stable hostnames at the
  control host without exposing container ports directly

Relevant inputs:

- `edge_obs_enable_public_proxy`
- `edge_obs_public_grafana_host`
- `edge_obs_public_thanos_host`
- `edge_obs_public_http_port`
- `edge_obs_public_https_port`

When this is enabled, also open only the required public ports on
`org/hetzner/shared-control-host`, typically:

```yaml
firewall_extra_tcp_ports:
  - 80
  - 443
```

## Required secrets

- Always:
  - `EDGE_OBS_GRAFANA_ADMIN_PASSWORD`
- Only when receive/store/ruler are enabled:
  - `EDGE_OBS_OBJSTORE_CONFIG`

Use vault-backed flows:

```bash
hyops secrets ensure --env <env> EDGE_OBS_GRAFANA_ADMIN_PASSWORD
```

To print the current Grafana admin password for a controlled operator task:

```bash
hyops vault password >/dev/null
hyops secrets show --env <env> EDGE_OBS_GRAFANA_ADMIN_PASSWORD --raw
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
- When the public proxy path is enabled, Grafana and Thanos Query stay bound to
  loopback and are exposed publicly only through the configured hostnames.
- If the module reports `ok`, the enabled services are not only started through
  Docker Compose; they have also passed the built-in readiness checks.
- When the burst dashboard path is enabled, the dashboard JSON and provisioning
  files are written into the Grafana container mount and survive normal module
  replays.
