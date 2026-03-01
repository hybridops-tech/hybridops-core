include "root" {
  path   = "${get_terragrunt_dir()}/root.hcl"
  expose = true
}

terraform {
  source = "${get_terragrunt_dir()}/terraform"
}

# Inputs come from root.hcl (hyops.inputs.json + profile defaults). Do not override here.
