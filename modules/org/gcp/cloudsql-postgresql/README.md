# org/gcp/cloudsql-postgresql

Provision a managed PostgreSQL instance in GCP Cloud SQL with private networking and normalized endpoint outputs.

This module is infra-only:

- Creates the Cloud SQL instance.
- Creates private service access resources when requested.
- Does **not** configure on-prem replication sources.
- Does **not** cut over application traffic.

## Recommended use

Use this as the first managed-DR building block.

- baseline DR remains self-managed restore to cloud VMs
- managed DR is a separate premium lane
- this module only provisions the managed database target

## Inputs

Preferred state-driven composition:

- `project_state_ref=org/gcp/project-factory`
- `network_state_ref=org/gcp/wan-hub-network`

When those state refs are present, treat them as the default contract for durable env overlays.
Keep `project_id`, `private_network`, and `network_project_id` empty unless you are intentionally overriding that state.

Fallback is explicit:

- `project_id`
- `private_network`
- `network_project_id` (required when the VPC lives in a different host project)

Default edition/tier pairing:

- `edition=ENTERPRISE`
- `tier=db-custom-2-8192`

If you want `ENTERPRISE_PLUS`, use a matching predefined performance tier such as `db-perf-optimized-*`.

`private_network` should be the VPC self link when provided explicitly.

For Shared VPC:

- `project_id` is the service project where Cloud SQL is created
- `network_project_id` is the host project that owns the VPC and private service access range
- set `manage_shared_vpc_attachment=true` only when you want this module to manage the service-project attachment explicitly
- GCP Shared VPC service-project attachment requires organization-backed projects; projects without an organization cannot be attached this way

## Usage

Preferred when HyOps already manages the GCP project and network in the same env:

```bash
HYOPS_INPUT_project_state_ref=org/gcp/project-factory \
HYOPS_INPUT_network_state_ref=org/gcp/wan-hub-network \
HYOPS_INPUT_instance_name=hyops-dev-pgsql-a1 \
hyops preflight --env <env> --strict \
  --module org/gcp/cloudsql-postgresql \
  --inputs "$HYOPS_CORE_ROOT/modules/org/gcp/cloudsql-postgresql/examples/inputs.min.yml"

HYOPS_INPUT_project_state_ref=org/gcp/project-factory \
HYOPS_INPUT_network_state_ref=org/gcp/wan-hub-network \
HYOPS_INPUT_instance_name=hyops-dev-pgsql-a1 \
hyops apply --env <env> \
  --module org/gcp/cloudsql-postgresql \
  --inputs "$HYOPS_CORE_ROOT/modules/org/gcp/cloudsql-postgresql/examples/inputs.min.yml"
```

Fallback for an external/pre-existing project/network:

```bash
hyops apply --env <env> \
  --module org/gcp/cloudsql-postgresql \
  --inputs "$HYOPS_CORE_ROOT/modules/org/gcp/cloudsql-postgresql/examples/inputs.min.yml"
```

For the fallback path, set `project_id`, `private_network`, `network_project_id` when needed, `manage_shared_vpc_attachment=true` when you want the module to create the Shared VPC service-project association, and `instance_name` in the input file first.

## Outputs

- `instance_name`
- `connection_name`
- `private_ip_address`
- `public_ip_address`
- `db_provider` (`gcp`)
- `db_engine` (`postgresql`)
- `db_host`
- `db_port`
- `cap_db_managed_postgresql`

## Notes

- `deletion_protection` defaults to `true`.
- `point_in_time_recovery_enabled` requires `backup_enabled=true`.
- `create_private_service_connection=true` is the default safe path for new networks.
- `hyops preflight`, `validate`, `plan`, and `apply` now fail early when the effective Terraform identity cannot create the private service access range or add the Service Networking peering.
- on a single-project VPC, `hyops init gcp --with-cli-login --force` now bootstraps `roles/servicenetworking.networksAdmin` onto the Terraform service account for the current project.
- `manage_shared_vpc_attachment=false` is the safe default; keep it false when the service project is already attached elsewhere.
- when `project_id` and `network_project_id` differ, the host project that owns the VPC must carry the network roles required for private service access, including `roles/compute.networkAdmin` and `roles/servicenetworking.networksAdmin` for the effective Terraform identity.
- This module is intentionally separate from the current Patroni restore blueprints.
