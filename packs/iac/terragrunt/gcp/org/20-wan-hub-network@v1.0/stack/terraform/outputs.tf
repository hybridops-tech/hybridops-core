output "project_id" {
  value = var.project_id
}

output "region" {
  value = var.region
}

output "network_name" {
  value = google_compute_network.hub.name
}

output "network_self_link" {
  value = google_compute_network.hub.self_link
}

output "subnet_core_name" {
  value = google_compute_subnetwork.core.name
}

output "subnet_core_self_link" {
  value = google_compute_subnetwork.core.self_link
}

output "subnet_core_cidr" {
  value = google_compute_subnetwork.core.ip_cidr_range
}

output "subnet_workloads_name" {
  value = google_compute_subnetwork.workloads.name
}

output "subnet_workloads_self_link" {
  value = google_compute_subnetwork.workloads.self_link
}

output "subnet_workloads_cidr" {
  value = google_compute_subnetwork.workloads.ip_cidr_range
}

output "subnet_workloads_pods_secondary_range_name" {
  value = var.enable_workloads_gke_secondary_ranges ? var.subnet_workloads_pods_secondary_range_name : ""
}

output "subnet_workloads_pods_secondary_range_cidr" {
  value = var.enable_workloads_gke_secondary_ranges ? var.subnet_workloads_pods_secondary_range_cidr : ""
}

output "subnet_workloads_services_secondary_range_name" {
  value = var.enable_workloads_gke_secondary_ranges ? var.subnet_workloads_services_secondary_range_name : ""
}

output "subnet_workloads_services_secondary_range_cidr" {
  value = var.enable_workloads_gke_secondary_ranges ? var.subnet_workloads_services_secondary_range_cidr : ""
}
