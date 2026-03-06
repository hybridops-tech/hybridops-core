# platform/network/powerdns-authority

Deploy PowerDNS Authoritative on a Linux host using Docker Compose.

This module is intended for the internal DNS authority layer:

- `powerdns_mode: primary` for the writable shared authority
- `powerdns_mode: secondary` for a read-only replicated authority

Recommended topology for HybridOps:

- shared primary in the Hetzner / WAN-edge control plane
- on-prem secondary for local resolution resilience

## What it does

- installs Docker Engine when needed
- deploys PowerDNS Authoritative with a persisted SQLite backend
- reuses the shared `hybridops.common.docker_compose_stack` lifecycle for Compose/systemd management
- enables the PowerDNS API
- optionally bootstraps one internal zone

## What it does not do

- does not provision the host VM
- does not provision public DNS
- does not replace NetBox as IPAM / source-of-truth metadata

## Required secret

- `POWERDNS_API_KEY`

Typical seed:

```bash
hyops secrets ensure --env <env> POWERDNS_API_KEY
```

## State-driven defaults

HybridOps should consume existing authority state by default:

- secondaries should prefer `powerdns_primary_state_ref`
- explicit `powerdns_primary_endpoint` remains available as an override

The shared primary publishes a reusable authority contract:

- `powerdns_target_host`
- `powerdns_api_url`
- `powerdns_server_id`
- `powerdns_zone_name`
- `powerdns_zone_id`
- `powerdns_api_key_env`

## Examples

Primary:

```bash
hyops validate --env <env> --skip-preflight \
  --module platform/network/powerdns-authority \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/powerdns-authority/examples/inputs.primary.yml"
```

Secondary:

```bash
hyops validate --env <env> --skip-preflight \
  --module platform/network/powerdns-authority \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/powerdns-authority/examples/inputs.secondary.yml"
```

## Notes

- The first clean product posture is Docker Compose + SQLite, not a separate database service.
- DNS cutover automation should target the **primary** API only.
- Clients should use stable names such as `postgres.dev.hyops.internal`, not raw node IPs.
- Shipped blueprints should consume authority state by default and fail clearly when the shared primary state is absent.
