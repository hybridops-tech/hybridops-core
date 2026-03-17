locals {
  prefix_raw = join("-", compact([trimspace(var.name_prefix), trimspace(var.context_id)]))
  prefix_1   = lower(replace(local.prefix_raw, "/[^0-9a-z-]/", "-"))
  prefix_2   = replace(local.prefix_1, "/-+/", "-")
  prefix     = trim(local.prefix_2, "-")

  private_network_name = local.prefix != "" ? "${local.prefix}-${var.private_network_name}" : var.private_network_name
}

resource "hcloud_network" "shared" {
  name     = local.private_network_name
  ip_range = var.private_network_cidr
  labels   = var.labels
}

resource "hcloud_network_subnet" "shared" {
  type         = "cloud"
  network_id   = hcloud_network.shared.id
  network_zone = var.network_zone
  ip_range     = var.private_network_cidr
}
