output "edge01_name" {
  value = hcloud_server.edge01.name
}

output "edge02_name" {
  value = hcloud_server.edge02.name
}

output "edge01_id" {
  value = hcloud_server.edge01.id
}

output "edge02_id" {
  value = hcloud_server.edge02.id
}

output "edge01_public_ip" {
  value = hcloud_server.edge01.ipv4_address
}

output "edge02_public_ip" {
  value = hcloud_server.edge02.ipv4_address
}

output "edge01_private_ip" {
  value = var.edge01_private_ip
}

output "edge02_private_ip" {
  value = var.edge02_private_ip
}

output "floating_ipv4" {
  value = hcloud_floating_ip.edge.ip_address
}

output "floating_target" {
  value = lower(trimspace(var.assign_floating_to))
}

output "private_network_id" {
  value = local.effective_private_network_id
}

output "private_network_cidr" {
  value = var.private_network_cidr
}

# Canonical VM output map for downstream state consumers
# (e.g. Ansible modules using inventory_state_ref / inventory_vm_groups).
output "vms" {
  value = {
    edge01 = {
      name                    = hcloud_server.edge01.name
      id                      = hcloud_server.edge01.id
      ipv4_address            = hcloud_server.edge01.ipv4_address
      ipv4_configured_primary = hcloud_server.edge01.ipv4_address
      ipv4_addresses          = [hcloud_server.edge01.ipv4_address]
      private_ipv4_address    = var.edge01_private_ip
    }
    edge02 = {
      name                    = hcloud_server.edge02.name
      id                      = hcloud_server.edge02.id
      ipv4_address            = hcloud_server.edge02.ipv4_address
      ipv4_configured_primary = hcloud_server.edge02.ipv4_address
      ipv4_addresses          = [hcloud_server.edge02.ipv4_address]
      private_ipv4_address    = var.edge02_private_ip
    }
  }
}

output "ipv4_configured_primary" {
  value = {
    edge01 = hcloud_server.edge01.ipv4_address
    edge02 = hcloud_server.edge02.ipv4_address
  }
}

output "ipv4_addresses_all" {
  value = {
    edge01 = [hcloud_server.edge01.ipv4_address]
    edge02 = [hcloud_server.edge02.ipv4_address]
  }
}
