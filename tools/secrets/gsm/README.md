# GCP Secret Manager sync

Use `hyops secrets gsm-sync` to copy an allowlisted set of GCP Secret Manager
secrets into the env-scoped runtime vault bundle.

This is intended for bootstrap, CI, and runner-driven DR workflows where the
execution plane is in GCP and cannot rely on on-prem secret stores.

## Command

```bash
hyops secrets gsm-sync --env dev --scope all
```

Project resolution order:

1. `--project-id`
2. `--project-state-ref`
3. `GCP_PROJECT_ID`
4. `<runtime>/config/gcp.conf`
5. implicit `org/gcp/project-factory` state when available

This keeps the command state-driven by default while still allowing an explicit
override when needed.

## Persist current runtime-vault secrets into GCP Secret Manager

Use `hyops secrets gsm-persist` to push the currently cached env-scoped secrets
from the runtime vault bundle into GCP Secret Manager using the same allowlist:

```bash
hyops secrets gsm-persist --env dev --scope dr
```

This is useful when you already have DR secrets in the runtime vault bundle and
want to seed Secret Manager as the external authority before a runner-driven DR
demo.

The same path can also persist build-time secrets, for example:

```bash
hyops secrets gsm-persist --env dev --scope build
```

This is the preferred way to make `HYOPS_VYOS_GCS_SA_JSON` available to a
runner-driven VyOS image build without depending on a local shell export.

## Mapping file

Default map file:

```text
tools/secrets/gsm/map/allowed.csv
```

CSV format:

```text
scope,ENV_KEY,GSM_SECRET_NAME
```

Supported placeholders in `GSM_SECRET_NAME`:

- `{env}`
- `{scope}`

## Notes

- Only mapped keys are read.
- Secret values are never printed.
- Synced values are written into the runtime vault bundle, not plain text files.
- Use runner dispatch with `--secret-source gsm` to refresh the runtime vault
  bundle before staging a remote DR job.
