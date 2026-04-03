# platform/network/dns-routing

Publish and optionally apply DNS routing intent for cutover/failback control.

This module is designed as a deterministic control surface:

- Always writes intent/state outputs for audit and orchestration.
- Applies provider updates only when explicitly enabled.
- Supports a live readback mode for PowerDNS so drill status can reflect the
  current rrset, not only the last requested intent.

## Providers

- `manual-command`
  - fallback provider
  - executes a shell command only when `dns_apply=true`
- `powerdns-api`
  - first-class internal DNS authority target
  - updates a PowerDNS Authoritative server through its HTTP API

Default mode remains non-destructive:

- `dry_run=true`
- `dns_apply=false`

## Inputs

- `provider`: routing provider mode (`manual-command` or `powerdns-api`).
- `apply_mode`: `bootstrap` or `status`
- `zone`, `record_fqdn`, `record_type`, `ttl`
- `primary_targets`, `secondary_targets`
- `desired`: `primary` or `secondary`
- `endpoint_state_ref`: optional upstream service endpoint state reference
- `endpoint_state_env`: optional alternate HybridOps environment to resolve `endpoint_state_ref`
- `endpoint_fqdn_output_key`, `endpoint_target_output_key`: output keys used when resolving endpoint data from state
- `provider_command`: shell command to execute when `provider=manual-command`.
- `powerdns_state_ref`: preferred shared PowerDNS authority state reference
- `powerdns_state_env`: optional alternate HybridOps environment to resolve `powerdns_state_ref`
- `powerdns_api_url`, `powerdns_server_id`, `powerdns_zone_id`
- `powerdns_api_key_env`: env var containing the PowerDNS API key
- `ssh_private_key_env`: optional env var containing the SSH private key used to reach the PowerDNS control host when the run executes on a shared runner
- `powerdns_validate_tls`, `powerdns_account`, `powerdns_comment`

When `provider=powerdns-api` and `dns_apply=true`, `required_env` must include the env var named by `powerdns_api_key_env`.

When `apply_mode=status`, the module performs a live readback of the current
PowerDNS rrset and compares it against the desired targets and TTL. This mode:

- supports `provider=powerdns-api`
- requires `required_env` to include the env var named by `powerdns_api_key_env`
- publishes `dns.status=live-ok` only when the live rrset matches the desired
  record, TTL, and targets
- records the observed live values in `dns.targets`, `dns.observed_targets`,
  `dns.observed_ttl`, and `dns.matches_desired`

This is the preferred verification step after DNS cutover or failback in DR
blueprints. It prevents a historical successful cutover state from standing in
for the current live PowerDNS record.

When `endpoint_state_ref` is set, HybridOps resolves:

- `record_fqdn` from `outputs.<endpoint_fqdn_output_key>` when omitted
- `primary_targets` / `secondary_targets` from `outputs.<endpoint_target_output_key>` when omitted

This is the preferred way to publish stable service FQDNs from stateful modules such as `platform/postgresql-ha`.

When `provider=powerdns-api`, HybridOps should also prefer:

- `powerdns_state_ref: platform/network/powerdns-authority#shared_primary`

That lets the module resolve the PowerDNS API endpoint, server id, zone id, and API key env name from state by default. Explicit values remain valid overrides.

State resolution rule:

- same-env state resolution is the default
- `shared` is the only normal cross-env authority
- if `endpoint_state_env` or `powerdns_state_env` points at another non-`shared` env, set `allow_cross_env_state=true` explicitly and treat the run as a controlled drill or migration

When `provider=powerdns-api` and `powerdns_state_ref` is set, the module can also derive the PowerDNS control host inventory automatically. This is the preferred DR pattern: execute DNS cutover from the shared control host, not from the workload runner itself. If the execution host does not already carry the SSH key on disk, set `ssh_private_key_env` and include it in `required_env` so HybridOps can materialize a transient key file for the Ansible driver.

## Usage

```bash
hyops preflight --env <env> --strict \
  --module platform/network/dns-routing \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/dns-routing/examples/inputs.min.yml"

hyops apply --env <env> \
  --module platform/network/dns-routing \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/network/dns-routing/examples/inputs.min.yml"
```

Status verification example:

```bash
hyops apply --env <env> \
  --module platform/network/dns-routing \
  --state-instance postgres_dns_status \
  --inputs /path/to/dns-status.inputs.yml
```
