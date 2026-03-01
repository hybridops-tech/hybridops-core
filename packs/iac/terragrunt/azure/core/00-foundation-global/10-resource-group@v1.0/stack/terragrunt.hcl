include "root" {
  path   = "${get_terragrunt_dir()}/root.hcl"
  expose = true
}

# Inputs come from root.hcl (hyops.inputs.json + profile defaults).
