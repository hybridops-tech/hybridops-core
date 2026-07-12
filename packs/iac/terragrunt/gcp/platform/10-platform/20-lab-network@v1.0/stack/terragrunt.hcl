include "root" {
  path   = "${get_terragrunt_dir()}/root.hcl"
  expose = true
}

terraform {
  source = "${get_terragrunt_dir()}/terraform"
}

# Preserve module inputs while passing through the GCP coordinates resolved by
# the profile from explicit inputs, init tfvars, or environment variables.
inputs = merge(
  include.root.locals.inputs,
  {
    project_id = include.root.locals.gcp.project_id
    region     = include.root.locals.gcp.region
  },
)
