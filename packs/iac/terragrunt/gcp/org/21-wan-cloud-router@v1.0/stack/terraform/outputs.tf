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
  value = google_compute_router.hub.name
}

output "router_self_link" {
  value = google_compute_router.hub.self_link
}

output "bgp_asn" {
  value = var.bgp_asn
}
