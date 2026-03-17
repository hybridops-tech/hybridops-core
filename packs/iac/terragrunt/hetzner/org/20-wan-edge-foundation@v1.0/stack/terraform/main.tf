locals {
  prefix_raw = join("-", compact([trimspace(var.name_prefix), trimspace(var.context_id)]))
  prefix_1   = lower(replace(local.prefix_raw, "/[^0-9a-z-]/", "-"))
  prefix_2   = replace(local.prefix_1, "/-+/", "-")
  prefix     = trim(local.prefix_2, "-")

  edge01_name                      = local.prefix != "" ? "${local.prefix}-${var.edge01_name}" : var.edge01_name
  edge02_name                      = local.prefix != "" ? "${local.prefix}-${var.edge02_name}" : var.edge02_name
  ssh_key_name                     = local.prefix != "" ? "${local.prefix}-${var.ssh_key_name}" : var.ssh_key_name
  firewall_name                    = local.prefix != "" ? "${local.prefix}-${var.firewall_name}" : var.firewall_name
  floating_ip_name                 = local.prefix != "" ? "${local.prefix}-${var.floating_ip_name}" : var.floating_ip_name
  private_network_name             = local.prefix != "" ? "${local.prefix}-${var.private_network_name}" : var.private_network_name
  create_private_network           = trimspace(var.private_network_id) == ""
  effective_private_network_id     = local.create_private_network ? tostring(hcloud_network.edge[0].id) : trimspace(var.private_network_id)
  effective_private_network_id_num = tonumber(local.effective_private_network_id)
  private_gateway_ip               = cidrhost(var.private_network_cidr, 1)
  edge01_private_cidr              = "${var.edge01_private_ip}/32"
  edge02_private_cidr              = "${var.edge02_private_ip}/32"

  ssh_public_key_trimmed    = trimspace(var.ssh_public_key)
  existing_ssh_keys_by_name = [for k in data.hcloud_ssh_keys.existing.ssh_keys : k if k.name == local.ssh_key_name]
  ssh_key_exists            = length(local.existing_ssh_keys_by_name) > 0
  ssh_key_mismatch          = length(local.existing_ssh_keys_by_name) > 0 && local.ssh_public_key_trimmed != "" && trimspace(local.existing_ssh_keys_by_name[0].public_key) != local.ssh_public_key_trimmed
  must_create_ssh_key       = !local.ssh_key_exists && local.ssh_public_key_trimmed != ""
  effective_ssh_key_name    = local.must_create_ssh_key ? hcloud_ssh_key.edge[0].name : local.ssh_key_name
  effective_ssh_public_key  = length(local.existing_ssh_keys_by_name) > 0 ? trimspace(local.existing_ssh_keys_by_name[0].public_key) : local.ssh_public_key_trimmed

  edge01_cloud_init = <<-EOT
#cloud-config
users:
  - name: vyos
    shell: /bin/vbash
    sudo: ALL=(ALL) NOPASSWD:ALL
    ssh_authorized_keys:
      - ${local.effective_ssh_public_key}
vyos_config_options:
  network_config: disabled
vyos_config_commands:
  - "set system host-name '${local.edge01_name}'"
  # Reset imported interface stanzas so stale hw-id values from source images
  # cannot prevent interface bring-up on Hetzner NICs.
  - "delete interfaces ethernet eth0"
  - "delete interfaces ethernet eth1"
  - "set interfaces ethernet eth0 address 'dhcp'"
  # Hetzner Cloud Networks are routed. Keep the private NIC as /32 and install
  # the routed subnet via the standard network gateway on eth1.
  - "set interfaces ethernet eth1 address '${local.edge01_private_cidr}'"
  - "set protocols static route '${local.private_gateway_ip}/32' interface 'eth1'"
  - "set protocols static route '${var.private_network_cidr}' next-hop '${local.private_gateway_ip}'"
  # Hetzner public networking on custom images is /32-style; pin the standard
  # host route and default route so first boot remains deterministic on VyOS.
  - "set protocols static route '172.31.1.1/32' interface 'eth0'"
  - "set protocols static route '0.0.0.0/0' next-hop '172.31.1.1'"
  - "set service ssh port '22'"
  - "set service ssh listen-address '0.0.0.0'"
power_state:
  mode: reboot
  timeout: 30
  message: "HyOps: reboot to activate first-boot VyOS config"
EOT

  edge02_cloud_init = <<-EOT
#cloud-config
users:
  - name: vyos
    shell: /bin/vbash
    sudo: ALL=(ALL) NOPASSWD:ALL
    ssh_authorized_keys:
      - ${local.effective_ssh_public_key}
vyos_config_options:
  network_config: disabled
vyos_config_commands:
  - "set system host-name '${local.edge02_name}'"
  # Reset imported interface stanzas so stale hw-id values from source images
  # cannot prevent interface bring-up on Hetzner NICs.
  - "delete interfaces ethernet eth0"
  - "delete interfaces ethernet eth1"
  - "set interfaces ethernet eth0 address 'dhcp'"
  # Hetzner Cloud Networks are routed. Keep the private NIC as /32 and install
  # the routed subnet via the standard network gateway on eth1.
  - "set interfaces ethernet eth1 address '${local.edge02_private_cidr}'"
  - "set protocols static route '${local.private_gateway_ip}/32' interface 'eth1'"
  - "set protocols static route '${var.private_network_cidr}' next-hop '${local.private_gateway_ip}'"
  # Hetzner public networking on custom images is /32-style; pin the standard
  # host route and default route so first boot remains deterministic on VyOS.
  - "set protocols static route '172.31.1.1/32' interface 'eth0'"
  - "set protocols static route '0.0.0.0/0' next-hop '172.31.1.1'"
  - "set service ssh port '22'"
  - "set service ssh listen-address '0.0.0.0'"
power_state:
  mode: reboot
  timeout: 30
  message: "HyOps: reboot to activate first-boot VyOS config"
EOT

  # Use one merged SSH source allowlist to avoid overlapping firewall rules.
  ssh_allowed_cidrs = distinct(concat([var.private_network_cidr], var.ssh_source_cidrs))

  floating_target_server_id = lower(trimspace(var.assign_floating_to)) == "edge02" ? hcloud_server.edge02.id : hcloud_server.edge01.id
}

data "hcloud_ssh_keys" "existing" {}

resource "hcloud_network" "edge" {
  count    = local.create_private_network ? 1 : 0
  name     = local.private_network_name
  ip_range = var.private_network_cidr
  labels   = var.labels
}

resource "hcloud_network_subnet" "edge" {
  count        = local.create_private_network ? 1 : 0
  type         = "cloud"
  network_id   = hcloud_network.edge[0].id
  network_zone = var.network_zone
  ip_range     = var.private_network_cidr
}

resource "hcloud_firewall" "edge" {
  name   = local.firewall_name
  labels = var.labels

  # Keep edge-to-control/private traffic unrestricted within the private subnet.
  rule {
    direction       = "out"
    protocol        = "tcp"
    port            = "1-65535"
    destination_ips = [var.private_network_cidr]
  }

  rule {
    direction       = "out"
    protocol        = "udp"
    port            = "1-65535"
    destination_ips = [var.private_network_cidr]
  }

  rule {
    direction       = "out"
    protocol        = "icmp"
    destination_ips = [var.private_network_cidr]
  }

  # Allow bootstrap control-plane egress required for first boot and metadata.
  # Tight WAN data-plane restrictions are enforced separately by explicit IPsec rules below.
  rule {
    direction       = "out"
    protocol        = "udp"
    port            = "67-68"
    destination_ips = ["0.0.0.0/0"]
  }

  rule {
    direction       = "out"
    protocol        = "udp"
    port            = "53"
    destination_ips = ["0.0.0.0/0"]
  }

  rule {
    direction       = "out"
    protocol        = "tcp"
    port            = "53"
    destination_ips = ["0.0.0.0/0"]
  }

  rule {
    direction       = "out"
    protocol        = "udp"
    port            = "123"
    destination_ips = ["0.0.0.0/0"]
  }

  rule {
    direction       = "out"
    protocol        = "tcp"
    port            = "80"
    destination_ips = ["0.0.0.0/0"]
  }

  rule {
    direction       = "out"
    protocol        = "tcp"
    port            = "443"
    destination_ips = ["0.0.0.0/0"]
  }

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "22"
    source_ips = local.ssh_allowed_cidrs
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

  # Explicitly allow IPsec data-plane egress to configured peers.
  rule {
    direction       = "out"
    protocol        = "udp"
    port            = "500"
    destination_ips = var.ipsec_source_cidrs
  }

  rule {
    direction       = "out"
    protocol        = "udp"
    port            = "4500"
    destination_ips = var.ipsec_source_cidrs
  }

  rule {
    direction       = "out"
    protocol        = "esp"
    destination_ips = var.ipsec_source_cidrs
  }
}

resource "hcloud_ssh_key" "edge" {
  count      = local.must_create_ssh_key ? 1 : 0
  name       = local.ssh_key_name
  public_key = local.ssh_public_key_trimmed
  labels     = var.labels
}

resource "hcloud_server" "edge01" {
  name        = local.edge01_name
  image       = var.image
  server_type = var.server_type
  location    = var.location
  ssh_keys    = [local.effective_ssh_key_name]
  user_data   = local.edge01_cloud_init
  labels      = merge(var.labels, { role = "wan-edge" })

  lifecycle {
    precondition {
      condition     = !local.must_create_ssh_key || local.ssh_public_key_trimmed != ""
      error_message = "No SSH key named '${local.ssh_key_name}' exists in Hetzner, and inputs.ssh_public_key is empty. Provide inputs.ssh_public_key or pre-create the key."
    }
    precondition {
      condition     = !local.ssh_key_mismatch
      error_message = "Existing SSH key '${local.ssh_key_name}' has a different public key than inputs.ssh_public_key. Use a unique ssh_key_name or align ssh_public_key."
    }
  }

  network {
    network_id = local.effective_private_network_id_num
    ip         = var.edge01_private_ip
  }
}

resource "hcloud_server" "edge02" {
  name        = local.edge02_name
  image       = var.image
  server_type = var.server_type
  location    = var.location
  ssh_keys    = [local.effective_ssh_key_name]
  user_data   = local.edge02_cloud_init
  labels      = merge(var.labels, { role = "wan-edge" })

  network {
    network_id = local.effective_private_network_id_num
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
