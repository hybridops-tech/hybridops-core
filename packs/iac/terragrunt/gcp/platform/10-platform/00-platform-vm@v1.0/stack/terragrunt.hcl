include "root" {
  path   = "${get_terragrunt_dir()}/root.hcl"
  expose = true
}

terraform {
  source = "${get_terragrunt_dir()}/terraform"
}

# SSH readiness is a HyOps post-apply control, not a Terraform variable.
inputs = {
  for key, value in include.root.locals.inputs :
  key => value if key != "post_apply_ssh_readiness"
}
