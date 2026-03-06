# dns_routing

Publishes DNS routing intent and can optionally apply DNS changes through:

- `manual-command`
- `powerdns-api`

Safety-first behavior remains:

- intent is always written to state
- DNS provider change requires explicit `dns_apply=true`
- `dry_run=true` keeps the module intent-only
