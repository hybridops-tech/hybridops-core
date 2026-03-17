locals {
  internal_ips = {
    for k, inst in google_compute_instance.vm :
    k => try(inst.network_interface[0].network_ip, null)
  }
  external_ips = {
    for k, inst in google_compute_instance.vm :
    k => try(inst.network_interface[0].access_config[0].nat_ip, null)
  }

  preferred_ips = {
    for k, _ in google_compute_instance.vm :
    k => (local.external_ips[k] != null ? local.external_ips[k] : local.internal_ips[k])
  }
}

output "vms" {
  value = {
    for k, inst in google_compute_instance.vm :
    k => {
      vm_name                 = inst.name
      vm_id                   = inst.id
      zone                    = inst.zone
      role                    = try(var.vms[k].role, null)
      ipv4_address            = local.preferred_ips[k]
      ipv4_configured_primary = local.internal_ips[k]
      ipv4_addresses          = compact([local.internal_ips[k], local.external_ips[k]])
      tags                    = inst.tags
      labels                  = inst.labels
    }
  }
}

output "vm_ids" {
  value = { for k, inst in google_compute_instance.vm : k => inst.id }
}

output "vm_names" {
  value = { for k, inst in google_compute_instance.vm : k => inst.name }
}

output "zones" {
  value = { for k, inst in google_compute_instance.vm : k => inst.zone }
}

output "ipv4_addresses" {
  value = local.preferred_ips
}

output "ipv4_addresses_all" {
  value = {
    for k, _ in google_compute_instance.vm :
    k => compact([local.internal_ips[k], local.external_ips[k]])
  }
}

output "tags" {
  value = { for k, inst in google_compute_instance.vm : k => inst.tags }
}

