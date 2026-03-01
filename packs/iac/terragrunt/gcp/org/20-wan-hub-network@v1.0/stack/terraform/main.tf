locals {
  prefix_raw = join("-", compact([trimspace(var.name_prefix), trimspace(var.context_id)]))
  prefix_1   = lower(replace(local.prefix_raw, "/[^0-9a-z-]/", "-"))
  prefix_2   = replace(local.prefix_1, "/-+/", "-")
  prefix     = trim(local.prefix_2, "-")

  network_name = local.prefix != "" ? "${local.prefix}-${var.network_name}" : var.network_name
  subnet_core_name = local.prefix != "" ? "${local.prefix}-${var.subnet_core_name}-${var.region}" : "${var.subnet_core_name}-${var.region}"
  subnet_workloads_name = local.prefix != "" ? "${local.prefix}-${var.subnet_workloads_name}-${var.region}" : "${var.subnet_workloads_name}-${var.region}"
}

resource "google_compute_network" "hub" {
  project                 = var.project_id
  name                    = local.network_name
  auto_create_subnetworks = false
  routing_mode            = upper(var.routing_mode)
}

resource "google_compute_subnetwork" "core" {
  project                  = var.project_id
  name                     = local.subnet_core_name
  region                   = var.region
  network                  = google_compute_network.hub.id
  ip_cidr_range            = var.subnet_core_cidr
  private_ip_google_access = true
}

resource "google_compute_subnetwork" "workloads" {
  project                  = var.project_id
  name                     = local.subnet_workloads_name
  region                   = var.region
  network                  = google_compute_network.hub.id
  ip_cidr_range            = var.subnet_workloads_cidr
  private_ip_google_access = true
}

resource "google_compute_firewall" "allow_iap_ssh" {
  count   = var.enable_iap_ssh ? 1 : 0
  project = var.project_id
  name    = "${local.network_name}-allow-iap-ssh"
  network = google_compute_network.hub.name

  direction = "INGRESS"
  priority  = 1000

  source_ranges = ["35.235.240.0/20"]
  target_tags   = ["allow-iap-ssh"]

  allow {
    protocol = "tcp"
    ports    = ["22"]
  }
}

resource "google_compute_firewall" "allow_internal" {
  project = var.project_id
  name    = "${local.network_name}-allow-internal-rfc1918"
  network = google_compute_network.hub.name

  direction = "INGRESS"
  priority  = 1100

  source_ranges = var.internal_allow_cidrs

  allow {
    protocol = "tcp"
  }

  allow {
    protocol = "udp"
  }

  allow {
    protocol = "icmp"
  }
}
