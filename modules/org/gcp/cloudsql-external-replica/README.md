# org/gcp/cloudsql-external-replica

Managed DR module for the Cloud SQL PostgreSQL lane.

This module has two phases:

- `apply_mode=assess`
- `apply_mode=establish`

It consumes:

- `platform/onprem/postgresql-dr-source`
- optionally `org/gcp/cloudsql-postgresql` for managed target assessment

and can create Database Migration Service (DMS) objects for continuous
PostgreSQL migration to Cloud SQL.

Important:

- `assess` validates an existing Cloud SQL target with `gcloud`.
- `establish` uses DMS connection profiles and a migration job.
- DMS creates its own Cloud SQL replica via the destination connection profile.
- `establish` does not reuse a standalone `org/gcp/cloudsql-postgresql` instance.

This keeps replication secrets out of Terraform state and aligns the managed DR lane with the Google control plane.

## Current scope

- verify the upstream on-prem DR source contract
- assess an existing Cloud SQL target
- create DMS source and destination connection profiles
- create and optionally start a DMS migration job
- publish normalized readiness, establishment, and endpoint outputs

## Not in scope yet

- application cutover
- promotion workflow automation
- failback automation

## Usage

```bash
hyops apply --env dev \
  --module org/gcp/cloudsql-external-replica \
  --inputs "$HYOPS_CORE_ROOT/modules/org/gcp/cloudsql-external-replica/examples/inputs.min.yml"
```

## Inputs

- `source_state_ref`: upstream source assessment state. Default: `platform/onprem/postgresql-dr-source`
- `managed_target_state_ref`: upstream managed Cloud SQL target state. Default: `org/gcp/cloudsql-postgresql`
- `apply_mode`: `assess`, `establish`, or `status`
- `replication_mode`: currently `logical` only
- `endpoint_dns_name`: optional stable DNS name that clients should use after promotion/cutover
- `gcloud_active_account`: optional expected active `gcloud` account for operator sanity

For `apply_mode=establish`, additional inputs are required:

- `project_state_ref` or `project_id`
- `network_state_ref` or `private_network`
- `source_connection_profile_name`
- `destination_connection_profile_name`
- `migration_job_name`
- `source_replication_user`
- `source_replication_password_env`
- `connectivity_mode`

Connectivity modes currently supported:

- `static-ip`
- `peer-vpc`
- `reverse-ssh`

`gcloud` must already be authenticated for the current operator. The module copies the current `~/.config/gcloud` into the runtime cache on first use so long-running or packaged runs do not depend on write access to the default config directory.

## Outputs

- `target_project_id`
- `target_region`
- `target_instance_name`
- `target_db_host`
- `target_db_port`
- `target_connection_name`
- `endpoint_dns_name`
- `endpoint_target`
- `endpoint_target_type`
- `endpoint_host`
- `endpoint_port`
- `endpoint_cutover_required`
- `source_host`
- `source_port`
- `source_leader_name`
- `source_replication_candidate`
- `source_connection_profile_name`
- `destination_connection_profile_name`
- `migration_job_name`
- `migration_job_state`
- `connectivity_mode`
- `managed_replication_mode`
- `managed_replication_prereqs_ready`
- `managed_replication_established`
- `cap.db.managed_external_replica = assessed|established`

The endpoint outputs intentionally match the client-facing contract already used by `platform/postgresql-ha`:

- when `endpoint_dns_name` is set, `endpoint_target` publishes that DNS name and `endpoint_target_type=dns`
- when `endpoint_dns_name` is blank, `endpoint_target` falls back to the Cloud SQL private IP/host and `endpoint_cutover_required=true`

That keeps DNS cutover and application consumers lane-agnostic.
