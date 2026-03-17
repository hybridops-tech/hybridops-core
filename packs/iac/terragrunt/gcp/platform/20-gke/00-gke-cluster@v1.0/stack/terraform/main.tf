locals {
  prefix_raw   = join("-", compact([trimspace(var.name_prefix), trimspace(var.context_id)]))
  prefix_1     = lower(replace(local.prefix_raw, "/[^0-9a-z-]/", "-"))
  prefix_2     = replace(local.prefix_1, "/-+/", "-")
  prefix       = trim(local.prefix_2, "-")
  cluster_name = local.prefix != "" ? "${local.prefix}-${var.cluster_name}" : var.cluster_name
  node_sa_id_raw = trimspace(var.node_service_account_id) != "" ? trimspace(var.node_service_account_id) : format(
    "%s-nodes",
    substr(local.cluster_name, 0, 24)
  )
  node_sa_id                     = trim(local.node_sa_id_raw, "-")
  managed_node_service_account   = trimspace(var.node_service_account) == ""
  effective_node_service_account = local.managed_node_service_account ? google_service_account.nodes[0].email : trimspace(var.node_service_account)
}

resource "google_project_service" "container" {
  project            = var.project_id
  service            = "container.googleapis.com"
  disable_on_destroy = false
}

resource "google_service_account" "nodes" {
  count        = local.managed_node_service_account ? 1 : 0
  project      = var.project_id
  account_id   = local.node_sa_id
  display_name = "GKE nodes (${local.cluster_name})"
}

resource "google_project_iam_member" "nodes_default_role" {
  count   = local.managed_node_service_account ? 1 : 0
  project = var.project_id
  role    = "roles/container.defaultNodeServiceAccount"
  member  = "serviceAccount:${google_service_account.nodes[0].email}"
}

resource "google_container_cluster" "cluster" {
  project  = var.project_id
  name     = local.cluster_name
  location = var.location

  network    = var.network
  subnetwork = var.subnetwork

  remove_default_node_pool = true
  initial_node_count       = 1
  deletion_protection      = var.deletion_protection
  networking_mode          = "VPC_NATIVE"
  datapath_provider        = "ADVANCED_DATAPATH"
  logging_service          = "logging.googleapis.com/kubernetes"
  monitoring_service       = "monitoring.googleapis.com/kubernetes"

  release_channel {
    channel = upper(var.release_channel)
  }

  ip_allocation_policy {
    cluster_secondary_range_name  = var.pods_secondary_range_name
    services_secondary_range_name = var.services_secondary_range_name
  }

  private_cluster_config {
    enable_private_nodes    = var.enable_private_nodes
    enable_private_endpoint = var.enable_private_endpoint
    master_ipv4_cidr_block  = var.master_ipv4_cidr_block
  }

  dynamic "master_authorized_networks_config" {
    for_each = length(var.master_authorized_networks) > 0 ? [1] : []
    content {
      dynamic "cidr_blocks" {
        for_each = var.master_authorized_networks
        content {
          cidr_block   = cidr_blocks.value.cidr
          display_name = try(cidr_blocks.value.display_name, null)
        }
      }
    }
  }

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  resource_labels = var.labels

  depends_on = [
    google_project_service.container,
    google_project_iam_member.nodes_default_role,
  ]
}

resource "google_container_node_pool" "default" {
  project        = var.project_id
  cluster        = google_container_cluster.cluster.name
  location       = google_container_cluster.cluster.location
  name           = var.node_pool_name
  node_count     = var.node_count
  node_locations = length(var.node_locations) > 0 ? var.node_locations : null

  management {
    auto_repair  = true
    auto_upgrade = true
  }

  node_config {
    machine_type    = var.machine_type
    disk_size_gb    = var.disk_size_gb
    tags            = var.tags
    labels          = var.labels
    oauth_scopes    = ["https://www.googleapis.com/auth/cloud-platform"]
    service_account = local.effective_node_service_account

    metadata = {
      disable-legacy-endpoints = "true"
    }
  }
}
