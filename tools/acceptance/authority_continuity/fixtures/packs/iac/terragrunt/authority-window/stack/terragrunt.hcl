terraform {
  source = "./modules/window"
}

locals {
  runtime_inputs = jsondecode(file("${get_terragrunt_dir()}/hyops.inputs.json"))
}

inputs = local.runtime_inputs
