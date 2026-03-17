output "project_id" {
  value = var.project_id
}

output "network_self_link" {
  value = var.network_self_link
}

output "ha_vpn_gateway_self_link" {
  value = google_compute_ha_vpn_gateway.hub.self_link
}

output "ha_vpn_gateway_ip_a" {
  value = try(google_compute_ha_vpn_gateway.hub.vpn_interfaces[0].ip_address, null)
}

output "ha_vpn_gateway_ip_b" {
  value = try(google_compute_ha_vpn_gateway.hub.vpn_interfaces[1].ip_address, null)
}

output "peer_ip_a" {
  value = var.peer_ip_a
}

output "peer_ip_b" {
  value = var.peer_ip_b
}

output "router_name" {
  value = var.router_name
}

output "tunnel_a_name" {
  value = google_compute_vpn_tunnel.tunnel_a.name
}

output "tunnel_b_name" {
  value = google_compute_vpn_tunnel.tunnel_b.name
}

output "bgp_a_gcp_ip" {
  value = cidrhost(var.tunnel_a_inside_cidr, 2)
}

output "bgp_a_peer_ip" {
  value = cidrhost(var.tunnel_a_inside_cidr, 1)
}

output "bgp_b_gcp_ip" {
  value = cidrhost(var.tunnel_b_inside_cidr, 2)
}

output "bgp_b_peer_ip" {
  value = cidrhost(var.tunnel_b_inside_cidr, 1)
}
