locals {
  prefix_raw = join("-", compact([trimspace(var.name_prefix), trimspace(var.context_id)]))
  prefix_1   = lower(replace(local.prefix_raw, "/[^0-9a-z-]/", "-"))
  prefix_2   = replace(local.prefix_1, "/-+/", "-")
  prefix     = trim(local.prefix_2, "-")

  network_name      = local.prefix != "" ? "${local.prefix}-${var.network_name}" : var.network_name
  subnetwork_name   = local.prefix != "" ? "${local.prefix}-${var.subnetwork_name}-${var.region}" : "${var.subnetwork_name}-${var.region}"
  router_name       = local.prefix != "" ? "${local.prefix}-${var.router_name}-${var.region}" : "${var.router_name}-${var.region}"
  nat_name          = local.prefix != "" ? "${local.prefix}-${var.nat_name}-${var.region}" : "${var.nat_name}-${var.region}"
  iap_firewall_name = "${local.network_name}-allow-iap-ssh"
  effective_project = trimspace(var.project_id) != "" ? var.project_id : null
}

resource "google_compute_network" "lab" {
  project                 = local.effective_project
  name                    = local.network_name
  auto_create_subnetworks = false
  routing_mode            = upper(var.routing_mode)
}

resource "google_compute_subnetwork" "lab" {
  project                  = local.effective_project
  name                     = local.subnetwork_name
  region                   = var.region
  network                  = google_compute_network.lab.id
  ip_cidr_range            = var.subnetwork_cidr
  private_ip_google_access = var.enable_private_google_access
}

resource "google_compute_firewall" "allow_iap_ssh" {
  count   = var.enable_iap_ssh ? 1 : 0
  project = local.effective_project
  name    = local.iap_firewall_name
  network = google_compute_network.lab.name

  direction = "INGRESS"
  priority  = 1000

  source_ranges = var.iap_source_cidrs
  target_tags   = var.iap_target_tags

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_compute_router" "lab" {
  project = local.effective_project
  name    = local.router_name
  region  = var.region
  network = google_compute_network.lab.id
}

resource "google_compute_router_nat" "lab" {
  project = local.effective_project
  name    = local.nat_name
  region  = var.region
  router  = google_compute_router.lab.name

  nat_ip_allocate_option              = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat  = "LIST_OF_SUBNETWORKS"
  min_ports_per_vm                    = var.nat_min_ports_per_vm
  enable_endpoint_independent_mapping = var.nat_enable_endpoint_independent_mapping

  subnetwork {
    name                    = google_compute_subnetwork.lab.id
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
  }

  log_config {
    enable = true
    filter = upper(var.nat_log_filter)
  }
}
