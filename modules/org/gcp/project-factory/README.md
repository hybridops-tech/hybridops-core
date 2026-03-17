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

Notes:

- `billing_account_id` remains a valid HyOps-friendly alias for the upstream `billing_account` input.
- HyOps accepts billing account values in either bare form (`01ED84-...`) or Google resource form (`billingAccounts/01ED84-...`) and normalizes them before Terraform runs.
- If billing is omitted from module inputs, HyOps can default it from the env-scoped GCP init config (`GCP_BILLING_ACCOUNT_ID` in `<root>/config/gcp.conf`).
- This defaulting is intended for interactive bootstrap and recovery flows; explicit module inputs still take precedence.
- `context_id` is a naming token for this module, not the env selector. `--env` selects the runtime lane; `context_id` is used for stable naming and labels.
- `hyops module init --module org/gcp/project-factory` now prefills `project_id`, `region`, `billing_account_id`, and `context_id` from the current env GCP init context when available, so the generated overlay is ready for editing instead of carrying stale example values.
- If `project_id` changes for the same env/module slot, HybridOps now rolls this module to a new Terraform Cloud workspace automatically. That avoids an unsafe in-place replacement of the old project state during account/project recovery.
- If the target `project_id` already exists and is accessible, preflight now skips the billing-association permission check and lets the module converge project-scoped settings such as enabled APIs and labels. Billing association is only preflight-critical when the lane still has to create or adopt a project.

Quick run:

```bash
hyops preflight --env <env> --strict \
  --module org/gcp/project-factory \
  --inputs "modules/org/gcp/project-factory/examples/inputs.min.yml"
```
