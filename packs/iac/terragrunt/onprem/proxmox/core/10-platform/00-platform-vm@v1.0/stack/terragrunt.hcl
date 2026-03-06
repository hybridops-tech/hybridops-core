include "root" {
  path   = "${get_terragrunt_dir()}/root.hcl"
  expose = true
}

locals {
  inputs = include.root.inputs
  # Single source of truth for the Proxmox vm-multi Terraform module.
  # Use Terragrunt's //subdir syntax so sibling nested modules (for example ../vm)
  # are copied into the cache.
  module_source_default = "git::https://github.com/hybridops-tech/hybridops-terraform-gitmods.git//proxmox/vm-multi?ref=v0.1.3"
  module_source_override = trimspace(get_env("HYOPS_PROXMOX_MODULE_SOURCE", ""))
  module_source = local.module_source_override != "" ? local.module_source_override : local.module_source_default

  hyops_env      = trimspace(get_env("HYOPS_ENV", ""))
  name_prefix_in = trimspace(try(tostring(local.inputs.name_prefix), ""))
  context_id_in  = trimspace(try(tostring(local.inputs.context_id), ""))
  vm_name_prefix = local.name_prefix_in != "" ? local.name_prefix_in : (local.context_id_in != "" ? local.context_id_in : local.hyops_env)

  vm_name      = trimspace(try(tostring(local.inputs.vm_name), ""))
  vm_id        = try(tonumber(local.inputs.vm_id), null)
  vm_ipv4_cidr = trimspace(try(tostring(local.inputs.vm_ipv4_cidr), ""))
  vm_gateway   = trimspace(try(tostring(local.inputs.vm_gateway), ""))
  vm_mac       = trimspace(try(tostring(local.inputs.vm_mac), ""))
  vm_name_physical = (
    local.vm_name != "" && local.vm_name_prefix != "" && !startswith(local.vm_name, "${local.vm_name_prefix}-")
    ? "${local.vm_name_prefix}-${local.vm_name}"
    : local.vm_name
  )

  default_interface = merge(
    { bridge = try(local.inputs.network_bridge, "vmbr0") },
    local.vm_mac != "" ? { mac_address = local.vm_mac } : {},
    local.vm_ipv4_cidr != "" ? {
      ipv4 = merge(
        { address = local.vm_ipv4_cidr },
        local.vm_gateway != "" ? { gateway = local.vm_gateway } : {}
      )
    } : {}
  )

  interfaces_in      = try(local.inputs.interfaces, [])
  default_interfaces = length(local.vm_ipv4_cidr) > 0 ? [local.default_interface] : []
  interfaces_raw     = length(local.interfaces_in) > 0 ? local.interfaces_in : local.default_interfaces
  interfaces = [
    for nic in local.interfaces_raw :
    merge(
      { bridge = trimspace(try(tostring(nic.bridge), try(local.inputs.network_bridge, "vmbr0"))) },
      try(nic.vlan_id, null) != null ? { vlan_id = tonumber(nic.vlan_id) } : {},
      trimspace(try(tostring(nic.mac_address), "")) != "" ? { mac_address = trimspace(tostring(nic.mac_address)) } : {},
      try(nic.ipv4, null) != null ? {
        ipv4 = merge(
          { address = trimspace(try(tostring(nic.ipv4.address), "dhcp")) },
          trimspace(try(tostring(nic.ipv4.gateway), "")) != "" ? { gateway = trimspace(tostring(nic.ipv4.gateway)) } : {}
        )
      } : {}
    )
  ]

  dns_servers_in = try(local.inputs.dns_servers, [])
  dns_servers    = length(local.dns_servers_in) > 0 ? local.dns_servers_in : ["8.8.8.8"]

  tags_in = try(local.inputs.tags, [])
  tags    = length(local.tags_in) > 0 ? local.tags_in : ["platform", "onprem"]

  dns_domain = trimspace(try(tostring(local.inputs.dns_domain), "")) != "" ? trimspace(tostring(local.inputs.dns_domain)) : "hybzone.local"

  ssh_username_effective = trimspace(try(tostring(local.inputs.ssh_username), try(tostring(local.inputs.proxmox_ssh_username), "root")))
  ssh_keys = (
    length(try(local.inputs.ssh_keys, [])) > 0
    ? local.inputs.ssh_keys
    : (
        trimspace(try(tostring(local.inputs.ssh_public_key), "")) != ""
        ? [trimspace(tostring(local.inputs.ssh_public_key))]
        : []
      )
  )
  vyos_users_keys_block = length(local.ssh_keys) > 0 ? trimspace(yamlencode({
    users = [{
      name                = local.ssh_username_effective
      ssh_authorized_keys = local.ssh_keys
    }]
  })) : ""

  cloud_init_user_data_in = trimspace(try(tostring(local.inputs.cloud_init_user_data), ""))
  cloud_init_network_data_in = trimspace(try(tostring(local.inputs.cloud_init_network_data), ""))
  cloud_init_meta_data_in = trimspace(try(tostring(local.inputs.cloud_init_meta_data), ""))
  cloud_init_user_data_base = local.cloud_init_user_data_in != "" ? local.cloud_init_user_data_in : <<-EOF
#cloud-config
hostname: ${local.vm_name}
fqdn: ${local.vm_name}.${local.dns_domain}
preserve_hostname: false
manage_etc_hosts: true
runcmd:
  - touch /var/lib/cloud/instance/ansible-ready
EOF
  cloud_init_user_data = (
    local.vyos_users_keys_block != ""
    && !can(regex("(?m)^\\s*users\\s*:", local.cloud_init_user_data_base))
    ? format("%s\n%s\n", trimspace(local.cloud_init_user_data_base), local.vyos_users_keys_block)
    : local.cloud_init_user_data_base
  )

  cloud_init_network_data = local.cloud_init_network_data_in != "" ? local.cloud_init_network_data_in : ""
  cloud_init_meta_data = local.cloud_init_meta_data_in != "" ? local.cloud_init_meta_data_in : ""

  vms_in = try(local.inputs.vms, {})
  vms_explicit = {
    for raw_name, raw_cfg in local.vms_in :
    trimspace(raw_name) => {
      role = trimspace(try(tostring(raw_cfg.role), "")) != "" ? trimspace(tostring(raw_cfg.role)) : "platform-vm"
      vm_id = try(raw_cfg.vm_id, null)
      vm_name = (
        trimspace(try(tostring(raw_cfg.vm_name), "")) != ""
        ? trimspace(tostring(raw_cfg.vm_name))
        : (
            local.vm_name_prefix != "" && !startswith(trimspace(raw_name), "${local.vm_name_prefix}-")
            ? "${local.vm_name_prefix}-${trimspace(raw_name)}"
            : trimspace(raw_name)
          )
      )
      interfaces = [
        for nic in jsondecode(
          length(try(raw_cfg.interfaces, [])) > 0
          ? jsonencode(try(raw_cfg.interfaces, []))
          : jsonencode(local.interfaces)
        ) :
        merge(
          { bridge = trimspace(try(tostring(nic.bridge), try(local.inputs.network_bridge, "vmbr0"))) },
          try(nic.vlan_id, null) != null ? { vlan_id = tonumber(nic.vlan_id) } : {},
          trimspace(try(tostring(nic.mac_address), "")) != "" ? { mac_address = trimspace(tostring(nic.mac_address)) } : {},
          try(nic.ipv4, null) != null ? {
            ipv4 = merge(
              { address = trimspace(try(tostring(nic.ipv4.address), "dhcp")) },
              trimspace(try(tostring(nic.ipv4.gateway), "")) != "" ? { gateway = trimspace(tostring(nic.ipv4.gateway)) } : {}
            )
          } : {}
        )
      ]
      cloud_init_user_data = (
        local.vyos_users_keys_block != ""
        && !can(regex("(?m)^\\s*users\\s*:", trimspace(try(tostring(raw_cfg.cloud_init_user_data), "")) != "" ? trimspace(tostring(raw_cfg.cloud_init_user_data)) : <<-EOF
#cloud-config
hostname: ${trimspace(raw_name)}
fqdn: ${trimspace(raw_name)}.${local.dns_domain}
preserve_hostname: false
manage_etc_hosts: true
runcmd:
  - touch /var/lib/cloud/instance/ansible-ready
EOF
))
        ? format("%s\n%s\n", trimspace(trimspace(try(tostring(raw_cfg.cloud_init_user_data), "")) != "" ? trimspace(tostring(raw_cfg.cloud_init_user_data)) : <<-EOF
#cloud-config
hostname: ${trimspace(raw_name)}
fqdn: ${trimspace(raw_name)}.${local.dns_domain}
preserve_hostname: false
manage_etc_hosts: true
runcmd:
  - touch /var/lib/cloud/instance/ansible-ready
EOF
), local.vyos_users_keys_block)
        : (trimspace(try(tostring(raw_cfg.cloud_init_user_data), "")) != "" ? trimspace(tostring(raw_cfg.cloud_init_user_data)) : <<-EOF
#cloud-config
hostname: ${trimspace(raw_name)}
fqdn: ${trimspace(raw_name)}.${local.dns_domain}
preserve_hostname: false
manage_etc_hosts: true
runcmd:
  - touch /var/lib/cloud/instance/ansible-ready
EOF
)
      )
      cloud_init_network_data = trimspace(try(tostring(raw_cfg.cloud_init_network_data), "")) != "" ? trimspace(tostring(raw_cfg.cloud_init_network_data)) : local.cloud_init_network_data
      cloud_init_meta_data = trimspace(try(tostring(raw_cfg.cloud_init_meta_data), "")) != "" ? trimspace(tostring(raw_cfg.cloud_init_meta_data)) : local.cloud_init_meta_data
    }
  }
  vms_single = {
    (local.vm_name) = {
      role  = trimspace(try(tostring(local.inputs.vm_role), "")) != "" ? trimspace(tostring(local.inputs.vm_role)) : "platform-vm"
      vm_name = local.vm_name_physical
      vm_id = local.vm_id
      interfaces = local.interfaces
      cloud_init_user_data = local.cloud_init_user_data
      cloud_init_network_data = local.cloud_init_network_data
      cloud_init_meta_data = local.cloud_init_meta_data
    }
  }
  vms = jsondecode(
    length(keys(local.vms_in)) > 0
    ? jsonencode(local.vms_explicit)
    : jsonencode(local.vms_single)
  )
}

terraform {
  source = local.module_source
}

  inputs = {
  node_name             = try(local.inputs.node_name, try(local.inputs.proxmox_node, ""))
  datastore_id          = try(local.inputs.datastore_id, try(local.inputs.storage_pool, "local-lvm"))
  snippets_datastore_id = try(local.inputs.snippets_datastore_id, try(local.inputs.storage_snippets, "local"))
  ssh_username          = local.ssh_username_effective
  ssh_keys              = local.ssh_keys

  template_vm_id       = try(tonumber(local.inputs.template_vm_id), null)
  cpu_cores            = try(tonumber(local.inputs.cpu_cores), 2)
  cpu_type             = try(local.inputs.cpu_type, "host")
  memory_mb            = try(tonumber(local.inputs.memory_mb), 4096)
  disk_size_gb         = try(tonumber(local.inputs.disk_size_gb), 32)
  guest_agent_enabled  = try(local.inputs.guest_agent_enabled, true)
  os_type              = try(local.inputs.os_type, "l26")
  on_boot              = try(local.inputs.on_boot, true)
  nameservers          = local.dns_servers
  tags                 = local.tags
  cloud_init_user_data = local.cloud_init_user_data
  cloud_init_network_data = local.cloud_init_network_data
  cloud_init_meta_data = local.cloud_init_meta_data
  interfaces           = local.interfaces
  vms                  = local.vms
}
