output "private_network_name" {
  value = hcloud_network.shared.name
}

output "private_network_id" {
  value = tostring(hcloud_network.shared.id)
}

output "private_network_cidr" {
  value = var.private_network_cidr
}
