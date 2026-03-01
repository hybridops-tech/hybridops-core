include "root" {
  path   = "${get_terragrunt_dir()}/root.hcl"
  expose = true
}

locals {
  inputs = include.root.inputs
  module_source = "tfr://registry.terraform.io/hybridops-studio/placeholder-vm/proxmox?version=0.0.0"

  vm_name      = trimspace(try(tostring(local.inputs.vm_name), "")) != "" ? trimspace(tostring(local.inputs.vm_name)) : "pg-core"
  vm_id        = try(tonumber(local.inputs.vm_id), 202)
  vm_ipv4_cidr = trimspace(try(tostring(local.inputs.vm_ipv4_cidr), "")) != "" ? trimspace(tostring(local.inputs.vm_ipv4_cidr)) : "10.12.0.10/24"
  vm_gateway   = trimspace(try(tostring(local.inputs.vm_gateway), "")) != "" ? trimspace(tostring(local.inputs.vm_gateway)) : "10.12.0.1"
  vm_mac       = trimspace(try(tostring(local.inputs.vm_mac), "")) != "" ? trimspace(tostring(local.inputs.vm_mac)) : "BC:24:11:00:00:21"

  default_interfaces = [
    {
      bridge      = try(local.inputs.network_bridge, "vmbr0")
      mac_address = local.vm_mac
      ipv4 = {
        address = local.vm_ipv4_cidr
        gateway = local.vm_gateway
      }
    }
  ]

  interfaces_in = try(local.inputs.interfaces, [])
  interfaces    = length(local.interfaces_in) > 0 ? local.interfaces_in : local.default_interfaces

  dns_servers_in = try(local.inputs.dns_servers, [])
  dns_servers    = length(local.dns_servers_in) > 0 ? local.dns_servers_in : ["8.8.8.8"]

  tags_in = try(local.inputs.tags, [])
  tags    = length(local.tags_in) > 0 ? local.tags_in : ["platform", "onprem", "postgresql", "database", "critical"]

  dns_domain = trimspace(try(tostring(local.inputs.dns_domain), "")) != "" ? trimspace(tostring(local.inputs.dns_domain)) : "hybzone.local"

  cloud_init_user_data_in = trimspace(try(tostring(local.inputs.cloud_init_user_data), ""))
  cloud_init_user_data = local.cloud_init_user_data_in != "" ? local.cloud_init_user_data_in : <<-EOF
#cloud-config
hostname: ${local.vm_name}
fqdn: ${local.vm_name}.${local.dns_domain}
preserve_hostname: false
manage_etc_hosts: true
runcmd:
  - touch /var/lib/cloud/instance/ansible-ready
EOF
}

terraform {
  source = local.module_source
}

inputs = {
  node_name             = try(local.inputs.node_name, try(local.inputs.proxmox_node, ""))
  datastore_id          = try(local.inputs.datastore_id, try(local.inputs.storage_pool, "local-lvm"))
  snippets_datastore_id = try(local.inputs.snippets_datastore_id, try(local.inputs.storage_snippets, "local"))
  ssh_username          = try(local.inputs.ssh_username, try(local.inputs.proxmox_ssh_username, "root"))
  ssh_keys              = try(local.inputs.ssh_keys, [])

  vm_name              = local.vm_name
  vm_id                = local.vm_id
  template_vm_id       = try(tonumber(local.inputs.template_vm_id), 9002)
  cpu_cores            = try(tonumber(local.inputs.cpu_cores), 4)
  cpu_type             = try(local.inputs.cpu_type, "host")
  memory_mb            = try(tonumber(local.inputs.memory_mb), 8192)
  disk_size_gb         = try(tonumber(local.inputs.disk_size_gb), 100)
  os_type              = try(local.inputs.os_type, "l26")
  on_boot              = try(local.inputs.on_boot, true)
  nameservers          = local.dns_servers
  interfaces           = local.interfaces
  tags                 = local.tags
  cloud_init_user_data = local.cloud_init_user_data
}
