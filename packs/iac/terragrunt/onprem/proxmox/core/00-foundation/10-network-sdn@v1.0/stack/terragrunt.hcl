include "root" {
  path   = "${get_terragrunt_dir()}/root.hcl"
  expose = true
}

locals {
  inputs = include.root.inputs
  module_source = "tfr://registry.terraform.io/hybridops-tech/sdn/proxmox?version=0.1.5"

  # HyOps writes validated + defaulted module inputs to hyops.inputs.json.
  # Keep pack locals as normalization only (no policy/default duplication).
  zone_name        = trimspace(tostring(local.inputs.zone_name))
  zone_bridge      = trimspace(tostring(local.inputs.zone_bridge))
  uplink_interface = trimspace(tostring(local.inputs.uplink_interface))

  dns_domain = trimspace(tostring(local.inputs.dns_domain))
  dns_lease  = trimspace(tostring(local.inputs.dns_lease))
  host_reconcile_nonce = trimspace(tostring(try(local.inputs.host_reconcile_nonce, "")))
  hyops_executable = trimspace(get_env("HYOPS_EXECUTABLE", "hyops"))

  vnets_input = try(local.inputs.vnets, {})
  # Topology is authoritative in module/blueprint inputs (validated by HyOps).
  # Keep the pack implementation free of embedded SDN policy defaults to avoid drift.
  vnets = local.vnets_input
}

terraform {
  source = local.module_source

  before_hook "validate_custom_sdn_vnets" {
    commands = ["init", "validate", "plan", "apply", "destroy"]
    execute = [
      local.hyops_executable,
      "terragrunt",
      "validate-proxmox-sdn-vnets",
      "--json",
      "${jsonencode(local.vnets)}",
    ]
  }
}

inputs = {
  zone_name        = local.zone_name
  zone_bridge      = local.zone_bridge
  uplink_interface = local.uplink_interface
  enable_snat      = local.inputs.enable_snat
  enable_host_l3   = local.inputs.enable_host_l3
  enable_dhcp      = local.inputs.enable_dhcp
  dns_domain       = local.dns_domain
  dns_lease        = local.dns_lease
  host_reconcile_nonce = local.host_reconcile_nonce
  vnets            = local.vnets
}
