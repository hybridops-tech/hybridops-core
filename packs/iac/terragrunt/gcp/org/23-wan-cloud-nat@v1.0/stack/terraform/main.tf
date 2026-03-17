locals {
  prefix_raw = join("-", compact([trimspace(var.name_prefix), trimspace(var.context_id)]))
  prefix_1   = lower(replace(local.prefix_raw, "/[^0-9a-z-]/", "-"))
  prefix_2   = replace(local.prefix_1, "/-+/", "-")
  prefix     = trim(local.prefix_2, "-")
  nat_name   = local.prefix != "" ? "${local.prefix}-${var.nat_name}" : var.nat_name
  nat_mode   = var.auto_allocate_external_ips ? "AUTO_ONLY" : "MANUAL_ONLY"
}

resource "google_compute_router_nat" "hub" {
  project = var.project_id
  name    = local.nat_name
  router  = var.router_name
  region  = var.region

  nat_ip_allocate_option              = local.nat_mode
  nat_ips                             = var.auto_allocate_external_ips ? null : var.nat_ip_self_links
  source_subnetwork_ip_ranges_to_nat  = "LIST_OF_SUBNETWORKS"
  min_ports_per_vm                    = var.min_ports_per_vm
  enable_endpoint_independent_mapping = var.enable_endpoint_independent_mapping

  dynamic "subnetwork" {
    for_each = toset(var.subnetwork_self_links)
    content {
      name                    = subnetwork.value
      source_ip_ranges_to_nat = [var.subnetwork_source_ip_ranges_to_nat]
    }
  }

  log_config {
    enable = true
    filter = upper(var.log_filter)
  }
}
