# org/gcp/cloudsql-external-replica

Managed DR module for the Cloud SQL PostgreSQL lane.

This module has two phases:

- `apply_mode=assess`
- `apply_mode=establish`

It consumes:

- `platform/onprem/postgresql-dr-source`
- optionally `org/gcp/cloudsql-postgresql` for managed target assessment
- optionally its own prior state via `replica_state_ref` for status-only assertions

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
- `managed_target_state_ref`: upstream managed Cloud SQL target state. Default: `org/gcp/cloudsql-postgresql` for `apply_mode=assess`
- `apply_mode`: `assess`, `establish`, or `status`
- `replica_state_ref`: optional prior `org/gcp/cloudsql-external-replica#<instance>` state used to resolve status-mode inputs without repeating connection-profile names
- `replica_state_env`: optional alternate HybridOps environment for isolated drills or migrations
- `allow_cross_env_state=true` when `replica_state_env` points to a non-`shared` env
- `required_migration_job_states`: optional list of acceptable DMS job states for `apply_mode=status` checks (for example `["RUNNING"]`)
- `replication_mode`: `logical` (only supported mode)
- `endpoint_dns_name`: optional stable DNS name that clients should use after promotion/cutover
- `gcloud_active_account`: optional expected active `gcloud` account for operator sanity

For `apply_mode=establish`, additional inputs are required:

- `project_state_ref` or `project_id`
- `network_state_ref` or `private_network`

For durable env overlays, prefer the state-driven form first.
Leave the explicit project and network fields empty unless the lane is intentionally detached from upstream HybridOps state.
- `source_connection_profile_name`
- `destination_connection_profile_name`
- `migration_job_name`
- `source_replication_user`
- `source_replication_password_env`
- `connectivity_mode`
- `required_env` must include `source_replication_password_env` when the value is loaded from runtime vault/env

TLS contract for the source profile:

- `source_ssl_type: NONE` means HybridOps omits the DMS SSL flags entirely
- `source_ssl_type: REQUIRED` or `SERVER_ONLY` requires `source_ca_certificate_env`
- `source_ssl_type: SERVER_CLIENT` requires all of:
  - `source_ca_certificate_env`
  - `source_client_certificate_env`
  - `source_private_key_env`
- `required_env` must include any TLS env keys referenced by those fields when they are set

For `apply_mode=establish` and `apply_mode=status`, a standalone
`managed_target_state_ref` is not required because DMS owns the destination
Cloud SQL lane.

Supported connectivity modes:

- `static-ip`
- `peer-vpc`
- `reverse-ssh`

For `reverse-ssh`, prefer `reverse_ssh_state_ref=platform/gcp/platform-vm#<runner-instance>`
so HybridOps resolves the bastion VM name and IP from state. Use the explicit
`reverse_ssh_vm`, `reverse_ssh_vm_ip`, and `reverse_ssh_vm_port` fields only
when no upstream bastion state exists.

`gcloud` must already be authenticated for the current operator. The module copies the current `~/.config/gcloud` into the runtime cache on first use so long-running or packaged runs do not depend on write access to the default config directory.

State resolution rule:

- same-env is the default
- `shared` is the only normal cross-env authority
- non-`shared` cross-env state is only for controlled drills or migrations and must opt in explicitly with `allow_cross_env_state=true`

Project service requirement:

- `datamigration.googleapis.com` must be enabled in the target project before `apply_mode=establish`
- if the project is managed by `org/gcp/project-factory`, prefer declaring that API in `activate_apis`
- otherwise enable it explicitly with:
  `gcloud services enable datamigration.googleapis.com --project=<project_id>`

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
- `managed_replication_ready_for_cutover`
- `connectivity_mode`
- `managed_replication_mode`
- `managed_replication_prereqs_ready`
- `managed_replication_established`
- `cap.db.managed_external_replica = assessed|established`

`managed_replication_ready_for_cutover=true` means the DMS job is currently `RUNNING`.

When `apply_mode=status` is rerun after the lane has changed state, HybridOps now overwrites that status instance with `status=error` if the live DMS job no longer matches the required state. This prevents an older green status snapshot from surviving a failed live refresh.

Operator rule:

- treat `org/gcp/cloudsql-external-replica#managed_standby` as the last successful
  establish contract
- treat `org/gcp/cloudsql-external-replica#managed_standby_status` as the live
  readiness signal for the current DMS lane

After promote or failback, the establish state can remain `ok` as historical
evidence while the status instance correctly flips to `error` because the live
migration job is no longer `RUNNING`.

The endpoint outputs intentionally match the client-facing contract already used by `platform/postgresql-ha`:

- when `endpoint_dns_name` is set, `endpoint_target` publishes that DNS name and `endpoint_target_type=dns`
- when `endpoint_dns_name` is blank, `endpoint_target` falls back to the Cloud SQL private IP/host and `endpoint_cutover_required=true`

That keeps DNS cutover and application consumers lane-agnostic.
