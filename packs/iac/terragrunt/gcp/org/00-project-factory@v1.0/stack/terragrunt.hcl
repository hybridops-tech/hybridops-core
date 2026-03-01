include "root" {
  path   = "${get_terragrunt_dir()}/root.hcl"
  expose = true
}

terraform {
  source = "tfr:///terraform-google-modules/project-factory/google?version=18.2.0"
}

# inputs come from root.hcl (hyops.inputs.json). Do not override here.