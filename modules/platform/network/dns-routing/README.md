# platform/network/dns-routing

Publish and optionally apply DNS routing intent for cutover/failback control.

This module is designed as a deterministic control surface:

- Always writes intent/state outputs for audit and orchestration.
- Applies provider updates only when explicitly enabled.

## v1 behavior

- Default mode is non-destructive:
  - `dry_run=true`
  - `dns_apply=false`
- Apply mode is explicit:
  - set `dry_run=false`
  - set `dns_apply=true`
  - provide `provider_command`

## Inputs

- `provider`: routing provider mode (`manual-command` in v1).
- `zone`, `record_fqdn`, `record_type`, `ttl`
- `primary_targets`, `secondary_targets`
- `desired`: `primary` or `secondary`
- `provider_command`: shell command to execute when apply mode is enabled.

## Usage

```bash
hyops preflight --env <env> --strict \
  --module platform/network/dns-routing \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/dns-routing/examples/inputs.min.yml"

hyops apply --env <env> \
  --module platform/network/dns-routing \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/dns-routing/examples/inputs.min.yml"
```
