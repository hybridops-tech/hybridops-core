# org/gcp/project-factory

Creates or converges a GCP project using the `terraform-google-modules/project-factory` Terragrunt pack.

## Execution
- Driver: `iac/terragrunt`
- Profile: `gcp@v1.0`
- Pack: `gcp/org/00-project-factory@v1.0`

## Inputs
See:

- `spec.yml`
- `examples/inputs.min.yml`
- `tests/example-inputs.yml`

Quick run:

```bash
hyops preflight --env <env> --strict \
  --module org/gcp/project-factory \
  --inputs "modules/org/gcp/project-factory/examples/inputs.min.yml"
```
