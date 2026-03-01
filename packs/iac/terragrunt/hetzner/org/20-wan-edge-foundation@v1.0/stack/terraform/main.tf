locals {
  prefix_raw = join("-", compact([trimspace(var.name_prefix), trimspace(var.context_id)]))
  prefix_1   = lower(replace(local.prefix_raw, "/[^0-9a-z-]/", "-"))
  prefix_2   = replace(local.prefix_1, "/-+/", "-")
  prefix     = trim(local.prefix_2, "-")

  edge01_name          = local.prefix != "" ? "${local.prefix}-${var.edge01_name}" : var.edge01_name
  edge02_name          = local.prefix != "" ? "${local.prefix}-${var.edge02_name}" : var.edge02_name
  ssh_key_name         = local.prefix != "" ? "${local.prefix}-${var.ssh_key_name}" : var.ssh_key_name
  firewall_name        = local.prefix != "" ? "${local.prefix}-${var.firewall_name}" : var.firewall_name
  floating_ip_name     = local.prefix != "" ? "${local.prefix}-${var.floating_ip_name}" : var.floating_ip_name
  private_network_name = local.prefix != "" ? "${local.prefix}-${var.private_network_name}" : var.private_network_name

  floating_target_server_id = lower(trimspace(var.assign_floating_to)) == "edge02" ? hcloud_server.edge02.id : hcloud_server.edge01.id
}

resource "hcloud_network" "edge" {
  name     = local.private_network_name
  ip_range = var.private_network_cidr
  labels   = var.labels
}

resource "hcloud_network_subnet" "edge" {
  type         = "cloud"
  network_id   = hcloud_network.edge.id
  network_zone = var.network_zone
  ip_range     = var.private_network_cidr
}

resource "hcloud_firewall" "edge" {
  name   = local.firewall_name
  labels = var.labels

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "22"
    source_ips = var.ssh_source_cidrs
  }

  rule {
    direction  = "in"
    protocol   = "udp"
    port       = "500"
    source_ips = var.ipsec_source_cidrs
  }

  rule {
    direction  = "in"
    protocol   = "udp"
    port       = "4500"
    source_ips = var.ipsec_source_cidrs
  }
}

resource "hcloud_ssh_key" "edge" {
  name       = local.ssh_key_name
  public_key = var.ssh_public_key
  labels     = var.labels
}

resource "hcloud_server" "edge01" {
  name        = local.edge01_name
  image       = var.image
  server_type = var.server_type
  location    = var.location
  ssh_keys    = [hcloud_ssh_key.edge.name]
  labels      = merge(var.labels, { role = "wan-edge" })

  network {
    network_id = hcloud_network.edge.id
    ip         = var.edge01_private_ip
  }
}

resource "hcloud_server" "edge02" {
  name        = local.edge02_name
  image       = var.image
  server_type = var.server_type
  location    = var.location
  ssh_keys    = [hcloud_ssh_key.edge.name]
  labels      = merge(var.labels, { role = "wan-edge" })

  network {
    network_id = hcloud_network.edge.id
    ip         = var.edge02_private_ip
  }
}

resource "hcloud_firewall_attachment" "edge" {
  firewall_id = hcloud_firewall.edge.id
  server_ids  = [hcloud_server.edge01.id, hcloud_server.edge02.id]
}

resource "hcloud_floating_ip" "edge" {
  type          = var.floating_ip_type
  name          = local.floating_ip_name
  home_location = var.home_location
  labels        = var.labels
}

resource "hcloud_floating_ip_assignment" "active" {
  floating_ip_id = hcloud_floating_ip.edge.id
  server_id      = local.floating_target_server_id
}
