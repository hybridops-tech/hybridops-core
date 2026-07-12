output "project_id" {
  value = google_compute_network.lab.project
}

output "region" {
  value = google_compute_subnetwork.lab.region
}

output "network_name" {
  value = google_compute_network.lab.name
}

output "network_self_link" {
  value = google_compute_network.lab.self_link
}

output "subnetwork_name" {
  value = google_compute_subnetwork.lab.name
}

output "subnetwork_self_link" {
  value = google_compute_subnetwork.lab.self_link
}

output "subnetwork_cidr" {
  value = google_compute_subnetwork.lab.ip_cidr_range
}

output "router_name" {
  value = google_compute_router.lab.name
}

output "router_self_link" {
  value = google_compute_router.lab.self_link
}

output "nat_name" {
  value = google_compute_router_nat.lab.name
}

output "nat_self_link" {
  value = google_compute_router_nat.lab.id
}

output "iap_firewall_rule_name" {
  value = try(google_compute_firewall.allow_iap_ssh[0].name, "")
}
