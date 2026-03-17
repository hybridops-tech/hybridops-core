# platform/linux/eve-ng-healthcheck

Run a structured EVE-NG health check against an existing EVE-NG host.

Use this after `platform/linux/eve-ng` has already installed the base runtime.
`load_vault_env` now defaults to `true`, and validate/preflight fail early if `EVENG_ADMIN_PASSWORD` is not seeded for API checks.

## Typical use

```bash
hyops apply --env dev \
  --module platform/linux/eve-ng-healthcheck \
  --inputs modules/platform/linux/eve-ng-healthcheck/examples/inputs.min.yml
```

The module publishes a concise HyOps status result while the detailed role output stays on the Ansible side.
