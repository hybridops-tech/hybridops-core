# platform/network/cloudflare-traffic-steering

Manages same-host Cloudflare traffic steering for primary and burst origins.

Use this module when one public hostname must steer traffic between a primary
origin and a burst origin:

- one public hostname
- one sticky weighted worker
- one primary origin
- one burst origin
- one status endpoint that decision-service or operators can verify

Current desired modes:

- `primary`: send all traffic to the primary origin
- `balanced`: send a configurable percentage to the burst origin
- `burst`: send all traffic to the burst origin

The deployed worker:

- redirects `/` to `root_redirect_path`
- exposes `/<status>` at `/__burst/status`
- uses a sticky cookie so viewers stay on the same lane
- sets debug headers on proxied responses:
  - `x-hybridops-burst-lane`
  - `x-hybridops-burst-desired`
  - `x-hybridops-burst-weight`

Typical uses:

- controlled same-host burst balancing
- managed cutover to a secondary origin
- deterministic failback to the primary origin
- live status verification for decision-service or operator workflows

## Inputs

- `zone_name`, `hostname`, `worker_name`
- `primary_origin_url`, `burst_origin_url`
- `desired`
- `balanced_burst_weight_pct`
- `forward_prefixes`
- `root_redirect_path`
- `ensure_dns_record`, `dns_record_target`

When `apply_mode=bootstrap` or `steering_state=absent`, `required_env` must
include the env var named by `cloudflare_api_token_env`.

`apply_mode=status` performs a live readback from:

- `https://<hostname>/__burst/status`

and verifies the worker currently publishes the expected desired mode, weight,
and origins.

## Usage

```bash
hyops preflight --env <env> --strict \
  --module platform/network/cloudflare-traffic-steering \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/cloudflare-traffic-steering/examples/inputs.min.yml"

hyops apply --env <env> \
  --module platform/network/cloudflare-traffic-steering \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/cloudflare-traffic-steering/examples/inputs.min.yml"
```

Status verification:

```bash
hyops apply --env <env> \
  --module platform/network/cloudflare-traffic-steering \
  --state-instance burst_status \
  --inputs /path/to/cloudflare-traffic-steering.status.yml
```

Decision-service action example:

- `cutover_module_ref: platform/network/cloudflare-traffic-steering`
- `failback_module_ref: platform/network/cloudflare-traffic-steering`
- `cutover_desired: balanced`
- `failback_desired: primary`

Then place the shared worker inputs under `actions.module_inputs`.
