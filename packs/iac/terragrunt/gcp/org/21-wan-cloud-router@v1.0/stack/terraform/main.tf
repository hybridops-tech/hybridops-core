locals {
  prefix_raw  = join("-", compact([trimspace(var.name_prefix), trimspace(var.context_id)]))
  prefix_1    = lower(replace(local.prefix_raw, "/[^0-9a-z-]/", "-"))
  prefix_2    = replace(local.prefix_1, "/-+/", "-")
  prefix      = trim(local.prefix_2, "-")
  router_name = local.prefix != "" ? "${local.prefix}-${var.router_name}" : var.router_name
}

resource "google_compute_router" "hub" {
  project = var.project_id
  name    = local.router_name
  region  = var.region
  network = var.network_self_link

  bgp {
    asn = var.bgp_asn
  }
}
