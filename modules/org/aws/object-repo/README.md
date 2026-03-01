# org/aws/object-repo

Provision a reusable AWS S3 object repository and dedicated IAM user.

This module is infra-only:

- Creates the S3 bucket with public access blocked and encryption enabled.
- Creates an IAM user with least-privilege bucket access.
- Does **not** create access keys (avoid secrets in Terraform state).

## Normalized outputs

- `repo_backend` (`s3`)
- `repo_provider` (`aws`)
- `repo_bucket_name`
- `repo_region`
- `repo_principal_type` (`iam_user`)
- `repo_principal_name` (IAM username)
- `repo_credential_create_hint`

Legacy aliases are also published for compatibility.

## Usage

```bash
hyops preflight --env <env> --strict \
  --module org/aws/object-repo \
  --inputs "$HYOPS_CORE_ROOT/modules/org/aws/object-repo/examples/inputs.min.yml"

hyops apply --env <env> \
  --module org/aws/object-repo \
  --inputs "$HYOPS_CORE_ROOT/modules/org/aws/object-repo/examples/inputs.min.yml"
```

Generate workload credentials out-of-band:

```bash
aws iam create-access-key --user-name <repo_principal_name>
```
