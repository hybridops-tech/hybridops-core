include "root" {
  path   = "${get_terragrunt_dir()}/root.hcl"
  expose = true
}

terraform {
  source = "${get_terragrunt_dir()}/terraform"
}

# inputs come from root.hcl (hyops.inputs.json). Do not override here.
