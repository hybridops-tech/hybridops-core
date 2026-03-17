locals {
  effective_range_name         = trimspace(var.allocated_ip_range_name) != "" ? trimspace(var.allocated_ip_range_name) : "${var.instance_name}-sql-psa"
  effective_network_project_id = trimspace(var.network_project_id) != "" ? trimspace(var.network_project_id) : var.project_id
}

resource "google_project_service" "sqladmin" {
  project            = var.project_id
  service            = "sqladmin.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "servicenetworking" {
  project            = var.project_id
  service            = "servicenetworking.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "servicenetworking_network_project" {
  count = local.effective_network_project_id != var.project_id ? 1 : 0

  project            = local.effective_network_project_id
  service            = "servicenetworking.googleapis.com"
  disable_on_destroy = false
}

resource "google_compute_shared_vpc_service_project" "service_project_attachment" {
  count = var.manage_shared_vpc_attachment && local.effective_network_project_id != var.project_id ? 1 : 0

  host_project    = local.effective_network_project_id
  service_project = var.project_id
}

resource "google_compute_global_address" "private_service_range" {
  count = var.create_private_service_connection ? 1 : 0

  project       = local.effective_network_project_id
  name          = local.effective_range_name
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = var.private_network

  depends_on = [
    google_project_service.servicenetworking,
    google_project_service.servicenetworking_network_project,
  ]
}

resource "google_service_networking_connection" "private_vpc_connection" {
  count = var.create_private_service_connection ? 1 : 0

  network                 = var.private_network
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_service_range[0].name]

  depends_on = [
    google_project_service.servicenetworking,
    google_project_service.servicenetworking_network_project,
  ]
}

resource "google_sql_database_instance" "instance" {
  project          = var.project_id
  region           = var.region
  name             = var.instance_name
  database_version = var.database_version

  deletion_protection = var.deletion_protection

  settings {
    edition           = var.edition
    tier              = var.tier
    availability_type = var.availability_type
    disk_size         = var.disk_size_gb
    disk_type         = var.disk_type
    user_labels       = var.labels

    backup_configuration {
      enabled                        = var.backup_enabled
      point_in_time_recovery_enabled = var.point_in_time_recovery_enabled
    }

    ip_configuration {
      ipv4_enabled       = var.ipv4_enabled
      private_network    = var.private_network
      allocated_ip_range = local.effective_range_name
    }

    dynamic "database_flags" {
      for_each = var.database_flags
      content {
        name  = database_flags.key
        value = database_flags.value
      }
    }
  }

  depends_on = [
    google_project_service.sqladmin,
    google_project_service.servicenetworking,
    google_service_networking_connection.private_vpc_connection,
    google_compute_shared_vpc_service_project.service_project_attachment,
  ]
}
