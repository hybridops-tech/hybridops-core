output "host_name" {
  value = hcloud_server.control.name
}

output "vm_id" {
  value = hcloud_server.control.id
}

output "public_ipv4" {
  value = hcloud_server.control.ipv4_address
}

output "private_ipv4" {
  value = var.private_ip
}

output "private_network_id" {
  value = var.private_network_id
}

output "private_network_cidr" {
  value = var.private_network_cidr
}

output "vm_keys" {
  value = [var.host_name]
}

output "vm_names" {
  value = [hcloud_server.control.name]
}

output "tags" {
  value = {
    (var.host_name) = ["shared-control", "hetzner", "control-plane"]
  }
}

output "vms" {
  value = {
    (var.host_name) = {
      vm_name                 = hcloud_server.control.name
      id                      = hcloud_server.control.id
      ipv4_address            = hcloud_server.control.ipv4_address
      ipv4_configured_primary = hcloud_server.control.ipv4_address
      ipv4_addresses          = compact([hcloud_server.control.ipv4_address])
      private_ipv4_address    = var.private_ip
      tags                    = ["shared-control", "hetzner", "control-plane"]
    }
  }
}

output "ipv4_configured_primary" {
  value = {
    (var.host_name) = hcloud_server.control.ipv4_address
  }
}

output "ipv4_addresses_all" {
  value = {
    (var.host_name) = compact([hcloud_server.control.ipv4_address])
  }
}
