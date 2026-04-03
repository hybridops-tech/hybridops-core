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

Education-stage workloads follow the same pattern:

```bash
hyops secrets gsm-persist --env dev --scope education
```

This is the preferred way to seed Moodle-related secrets into GCP Secret
Manager before ESO projects them into the cluster.

Cloudflare Tunnel follows the same pattern:

```bash
hyops secrets gsm-persist --env dev --scope cloudflare
```

Use this when the tunnel token must be projected into the cluster through ESO
instead of a hand-applied long-lived `Secret`.
## Mapping file

Default map file:

```text
tools/secrets/gsm/map/allowed.csv
```

Preferred env-local override:

```text
<runtime>/config/secrets/gsm/allowed.csv
```

Safe local template pattern:

```text
<runtime>/config/secrets/gsm/allowed.csv.example
```

Copy the example to `allowed.csv` only when the current env really needs a
different GSM naming contract from the shipped default.

The shipped default is intentionally narrow. Private training, Moodle, and
external identity-provider rows belong in the env-local override, not in the
shipped core map.

Map resolution order:

1. `--map-file`
2. env-local runtime map
3. `HYOPS_GSM_MAP_FILE`
4. shipped core default

CSV format:

```text
scope,ENV_KEY,GSM_SECRET_NAME
```

Supported placeholders in `GSM_SECRET_NAME`:

- `{env}`
- `{scope}`
- `{env_key}`
- `{env_key_slug}`

## Register env-local mappings while persisting

When you are creating or rotating secrets through `hyops secrets set` or
`hyops secrets ensure`, you can register missing env-local GSM mappings and
persist them in one step.

Example:

```bash
hyops secrets set --env dev \
  --persist gsm \
  --persist-scope labs \
  --persist-register-gsm-map \
  LEARN_SESSION_SECRET=... \
  ENTITLEMENTS_API_TOKEN=...
```

Before HybridOps writes any env-local GSM rows, it first validates that the target
GCP project can be resolved and that Secret Manager access is actually
available. If project access fails, the command exits without mutating the
env-local GSM map.

On success, this writes any missing rows to:

```text
<runtime>/config/secrets/gsm/allowed.csv
```

using the default naming template:

```text
hyops-{env}-{scope}-{env_key_slug}
```

Override the generated naming pattern only when you need a different
env-local convention:

```bash
hyops secrets ensure --env dev \
  --persist gsm \
  --persist-scope labs \
  --persist-register-gsm-map \
  --persist-register-gsm-template '{env}-labs-{env_key_slug}' \
  LEARN_SESSION_SECRET ENTITLEMENTS_API_TOKEN
```

`--persist-register-gsm-map` only writes to the env-local override after the
target GCP project passes access checks. It never modifies the shipped core
default map.

## Notes

- Only mapped keys are read.
- Secret values are never printed.
- Synced values are written into the runtime vault bundle, not plain text files.
- Use runner dispatch with `--secret-source gsm` to refresh the runtime vault
  bundle before staging a remote DR job.
