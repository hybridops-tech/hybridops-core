# org/gcp/gsm-eso-sa

Provision the GCP service account used by External Secrets Operator to read
Google Secret Manager from a Kubernetes cluster.

State-first contract:

- imports `project_id` from `org/gcp/project-factory` by default
- publishes `eso_sa_email`

Execution scope:

- creates the service account
- grants `roles/secretmanager.secretAccessor` on the project
- does not create or rotate service-account keys

Apply order:

1. `org/gcp/project-factory`
2. `org/gcp/gsm-eso-sa`
3. `hyops init gcp --force --with-eso-sa`
4. `platform/k8s/gsm-bootstrap`

Example:

```bash
hyops validate --env dev \
  --module org/gcp/gsm-eso-sa \
  --inputs "$HYOPS_CORE_ROOT/modules/org/gcp/gsm-eso-sa/examples/inputs.min.yml"
```

Output:

- `eso_sa_email`
