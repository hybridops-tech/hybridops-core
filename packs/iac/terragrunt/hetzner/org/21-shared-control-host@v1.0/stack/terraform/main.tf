locals {
  prefix_raw = join("-", compact([trimspace(var.name_prefix), trimspace(var.context_id)]))
  prefix_1   = lower(replace(local.prefix_raw, "/[^0-9a-z-]/", "-"))
  prefix_2   = replace(local.prefix_1, "/-+/", "-")
  prefix     = trim(local.prefix_2, "-")

  vm_name       = local.prefix != "" ? "${local.prefix}-${var.host_name}" : var.host_name
  firewall_name = local.prefix != "" ? "${local.prefix}-${var.firewall_name}" : var.firewall_name

  cloud_init = <<-EOT
    #cloud-config
    users:
      - default
      - name: ${var.ssh_username}
        groups: [sudo]
        shell: /bin/bash
        sudo: ALL=(ALL) NOPASSWD:ALL
        ssh_authorized_keys:
${join("\n", [for key in var.ssh_keys : "          - ${key}"])}
    package_update: true
    package_upgrade: false
  EOT
}

resource "hcloud_firewall" "control" {
  count  = var.firewall_enabled ? 1 : 0
  name   = local.firewall_name
  labels = var.labels

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "22"
    source_ips = var.ssh_source_cidrs
  }
}

resource "hcloud_server" "control" {
  name        = local.vm_name
  image       = var.image
  server_type = var.server_type
  location    = var.location
  user_data   = local.cloud_init
  labels      = merge(var.labels, { role = "shared-control" })

  public_net {
    ipv4_enabled = var.public_ipv4_enabled
    ipv6_enabled = var.public_ipv6_enabled
  }

  network {
    network_id = tonumber(var.private_network_id)
    ip         = var.private_ip
  }
}

resource "hcloud_firewall_attachment" "control" {
  count       = var.firewall_enabled ? 1 : 0
  firewall_id = hcloud_firewall.control[0].id
  server_ids  = [hcloud_server.control.id]
}
