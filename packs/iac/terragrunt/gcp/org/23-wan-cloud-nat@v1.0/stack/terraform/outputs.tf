output "project_id" {
  value = var.project_id
}

output "region" {
  value = var.region
}

output "network_self_link" {
  value = var.network_self_link
}

output "router_name" {
  value = var.router_name
}

output "nat_name" {
  value = google_compute_router_nat.hub.name
}

output "nat_self_link" {
  value = google_compute_router_nat.hub.id
}

output "subnetwork_self_links" {
  value = var.subnetwork_self_links
}
