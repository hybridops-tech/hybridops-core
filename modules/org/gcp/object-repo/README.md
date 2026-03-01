# org/gcp/object-repo

Provision a reusable GCS object repository and dedicated service account.

This module is infra-only:

- Creates the bucket and IAM bindings.
- Does **not** create service account keys (avoid secrets in Terraform state).

## Normalized outputs

- `repo_backend` (`gcs`)
- `repo_provider` (`gcp`)
- `repo_bucket_name`
- `repo_region`
- `repo_principal_type` (`service_account`)
- `repo_principal_name` (service account email)
- `repo_credential_create_hint`

## Usage

Preferred when HyOps already manages the target GCP project in the same env:

```bash
HYOPS_INPUT_project_state_ref=org/gcp/project-factory \
HYOPS_INPUT_bucket_name=hyops-object-repo-dev \
hyops preflight --env <env> --strict \
  --module org/gcp/object-repo \
  --inputs "$HYOPS_CORE_ROOT/modules/org/gcp/object-repo/examples/inputs.min.yml"

HYOPS_INPUT_project_state_ref=org/gcp/project-factory \
HYOPS_INPUT_bucket_name=hyops-object-repo-dev \
hyops apply --env <env> \
  --module org/gcp/object-repo \
  --inputs "$HYOPS_CORE_ROOT/modules/org/gcp/object-repo/examples/inputs.min.yml"
```

Fallback for an external/pre-existing project:

```bash
hyops preflight --env <env> --strict \
  --module org/gcp/object-repo \
  --inputs "$HYOPS_CORE_ROOT/modules/org/gcp/object-repo/examples/inputs.min.yml"

hyops apply --env <env> \
  --module org/gcp/object-repo \
  --inputs "$HYOPS_CORE_ROOT/modules/org/gcp/object-repo/examples/inputs.min.yml"
```

For the fallback path, set `project_id` and `bucket_name` in the input file first.

When `project_state_ref` is set, HyOps resolves `project_id` from upstream state and treats it as authoritative for the run. `hyops init gcp` still provides runtime credentials and Terragrunt defaults, but it is not the preferred source of project intent for reusable module composition.

Bucket naming guidance:

- Recommended pattern: `hyops-<env>-objectrepo-<suffix>`
- Example: `hyops-dev-objectrepo-a1`
- Keep it lowercase and globally unique within GCS.

State-slot safety:

- A bucket name is treated as immutable within a given HyOps state slot.
- If a state slot already points to one bucket, HyOps will refuse to pivot that same slot to a different bucket name.
- To create a second repo, use a new `--state-instance`.

Generate workload credentials out-of-band:

```bash
gcloud iam service-accounts keys create ./object-repo-sa.json \
  --iam-account "<repo_principal_name>"
```
