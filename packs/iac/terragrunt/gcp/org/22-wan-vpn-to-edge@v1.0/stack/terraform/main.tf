locals {
  prefix_raw = join("-", compact([trimspace(var.name_prefix), trimspace(var.context_id)]))
  prefix_1   = lower(replace(local.prefix_raw, "/[^0-9a-z-]/", "-"))
  prefix_2   = replace(local.prefix_1, "/-+/", "-")
  prefix     = trim(local.prefix_2, "-")

  ha_vpn_gateway_name       = local.prefix != "" ? "${local.prefix}-${var.ha_vpn_gateway_name}" : var.ha_vpn_gateway_name
  external_vpn_gateway_name = local.prefix != "" ? "${local.prefix}-${var.external_vpn_gateway_name}" : var.external_vpn_gateway_name

  tunnel_a_peer_ip = cidrhost(var.tunnel_a_inside_cidr, 1)
  tunnel_a_gcp_ip  = cidrhost(var.tunnel_a_inside_cidr, 2)

  tunnel_b_peer_ip = cidrhost(var.tunnel_b_inside_cidr, 1)
  tunnel_b_gcp_ip  = cidrhost(var.tunnel_b_inside_cidr, 2)

  advertised_prefixes_effective = distinct(compact(concat(
    var.advertised_prefixes,
    var.auto_include_cloud_core_cidr ? [trimspace(var.cloud_core_cidr)] : [],
    var.auto_include_cloud_workloads_cidr ? [trimspace(var.cloud_workloads_cidr)] : [],
    var.auto_include_cloud_workloads_pods_cidr ? [trimspace(var.cloud_workloads_pods_cidr)] : []
  )))
}

resource "google_compute_ha_vpn_gateway" "hub" {
  name    = local.ha_vpn_gateway_name
  project = var.project_id
  region  = var.region
  network = var.network_self_link
}

resource "google_compute_external_vpn_gateway" "peer" {
  name            = local.external_vpn_gateway_name
  project         = var.project_id
  redundancy_type = "TWO_IPS_REDUNDANCY"

  interface {
    id         = 0
    ip_address = var.peer_ip_a
  }

  interface {
    id         = 1
    ip_address = var.peer_ip_b
  }
}

resource "google_compute_vpn_tunnel" "tunnel_a" {
  name                  = "${local.ha_vpn_gateway_name}-tunnel-a"
  project               = var.project_id
  region                = var.region
  vpn_gateway           = google_compute_ha_vpn_gateway.hub.self_link
  vpn_gateway_interface = 0

  peer_external_gateway           = google_compute_external_vpn_gateway.peer.self_link
  peer_external_gateway_interface = 0

  shared_secret = var.shared_secret_a
  router        = var.router_name
}

resource "google_compute_vpn_tunnel" "tunnel_b" {
  name                  = "${local.ha_vpn_gateway_name}-tunnel-b"
  project               = var.project_id
  region                = var.region
  vpn_gateway           = google_compute_ha_vpn_gateway.hub.self_link
  vpn_gateway_interface = 1

  peer_external_gateway           = google_compute_external_vpn_gateway.peer.self_link
  peer_external_gateway_interface = 1

  shared_secret = var.shared_secret_b
  router        = var.router_name
}

resource "google_compute_router_interface" "if_a" {
  name       = "${var.router_name}-if-a"
  project    = var.project_id
  region     = var.region
  router     = var.router_name
  ip_range   = "${local.tunnel_a_gcp_ip}/${split("/", var.tunnel_a_inside_cidr)[1]}"
  vpn_tunnel = google_compute_vpn_tunnel.tunnel_a.name
}

resource "google_compute_router_interface" "if_b" {
  name       = "${var.router_name}-if-b"
  project    = var.project_id
  region     = var.region
  router     = var.router_name
  ip_range   = "${local.tunnel_b_gcp_ip}/${split("/", var.tunnel_b_inside_cidr)[1]}"
  vpn_tunnel = google_compute_vpn_tunnel.tunnel_b.name
}

resource "google_compute_router_peer" "bgp_a" {
  name            = "${var.router_name}-bgp-a"
  project         = var.project_id
  region          = var.region
  router          = var.router_name
  interface       = google_compute_router_interface.if_a.name
  ip_address      = local.tunnel_a_gcp_ip
  peer_asn        = var.peer_asn
  peer_ip_address = local.tunnel_a_peer_ip

  lifecycle {
    replace_triggered_by = [google_compute_router_interface.if_a]
  }

  advertise_mode            = "CUSTOM"
  advertised_route_priority = var.advertised_route_priority

  dynamic "advertised_ip_ranges" {
    for_each = toset(local.advertised_prefixes_effective)
    content {
      range = advertised_ip_ranges.value
    }
  }
}

resource "google_compute_router_peer" "bgp_b" {
  name            = "${var.router_name}-bgp-b"
  project         = var.project_id
  region          = var.region
  router          = var.router_name
  interface       = google_compute_router_interface.if_b.name
  ip_address      = local.tunnel_b_gcp_ip
  peer_asn        = var.peer_asn
  peer_ip_address = local.tunnel_b_peer_ip

  lifecycle {
    replace_triggered_by = [google_compute_router_interface.if_b]
  }

  advertise_mode            = "CUSTOM"
  advertised_route_priority = var.advertised_route_priority

  dynamic "advertised_ip_ranges" {
    for_each = toset(local.advertised_prefixes_effective)
    content {
      range = advertised_ip_ranges.value
    }
  }
}
