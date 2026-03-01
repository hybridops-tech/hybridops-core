# pgbackrest_repo

Internal HyOps helper role to normalize and validate pgBackRest repository settings and expose
Autobase-compatible variables:

- `pgbackrest_install: true`
- `pgbackrest_repo_type: s3|gcs|azure`
- `pgbackrest_stanza: <patroni_cluster_name>`
- `pgbackrest_conf: {...}`
- Optional `repo2-*` entries when `secondary_enabled=true` to support cross-cloud secondary backup copy.

This role does **not** create cloud resources. It assumes the backup repository already exists.
