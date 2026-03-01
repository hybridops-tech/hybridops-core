# generic.pkr.hcl
# Universal VM template builder for Proxmox
# Supports Linux (Ubuntu, Rocky, Debian) and Windows
# Author: HybridOps Platform Team
# Last modified: 2025-12-24

locals {
  unattended_content = {
    for key, value in var.unattended_content : key => templatefile(
      value.template,
      merge(value.vars, {
        winrm_username         = var.winrm_username
        winrm_password         = var.winrm_password
        windows_edition        = lookup(value.vars, "windows_edition", var.windows_edition)
        windows_language       = lookup(value.vars, "windows_language", var.windows_language)
        windows_input_language = lookup(value.vars, "windows_input_language", var.windows_input_language)
        driver_version         = lookup(value.vars, "driver_version", "")
      })
    )
  }

  unattended_as_cd = length(var.unattended_content) > 0 ? [{
    type    = "sata"
    index   = 3 + length(var.unattended_content)
    content = local.unattended_content
    label   = "Windows Unattended CD"
  }] :  []

  additional_cd_files = concat(var.additional_cd_files, local.unattended_as_cd)

  ssh_key_path = var.ssh_private_key_file != "" ? var.ssh_private_key_file : "${path.root}/keys/packer_rsa"
  use_ssh_key  = fileexists(local.ssh_key_path)

  ssh_key_file  = local.use_ssh_key ? local.ssh_key_path : null
  ssh_password  = local.use_ssh_key ? null : var.ssh_password
  sudo_password = var.ssh_password
}

source "proxmox-iso" "vm" {
  proxmox_url              = var.proxmox_url
  username                 = var.proxmox_token_id
  token                    = var.proxmox_token_secret
  insecure_skip_tls_verify = var.proxmox_skip_tls

  node                 = var.proxmox_node
  vm_id                = var.vmid
  vm_name              = var.name
  template_description = var.description != "" ? var.description : "${var.name} - Built ${timestamp()}"
  pool                 = var.pool

  cpu_type        = var.cpu_type
  sockets         = var.cpu_sockets
  cores           = var.cpu_cores
  memory          = var.memory
  scsi_controller = var.scsi_controller

  disks {
    type         = var.disk_type
    disk_size    = var.disk_size
    storage_pool = var.storage_pool
    format       = var.disk_format
    cache_mode   = var.disk_cache
  }

  network_adapters {
    bridge      = var.network_bridge
    model       = var.network_adapter_model
    mac_address = var.network_adapter_mac
    vlan_tag    = var.network_adapter_vlan == -1 ? null :  var.network_adapter_vlan
    firewall    = var.network_adapter_firewall
  }

  vga {
    type   = var.vga_type
    memory = var.vga_memory
  }

  os         = var.os
  bios       = var.bios
  qemu_agent = var.qemu_agent
  onboot     = var.start_at_boot

  boot_iso {
    iso_file         = var.iso_download ? "" : "${var.storage_iso}:iso/${var.iso_file}"
    iso_storage_pool = var.storage_iso
    iso_url          = var.iso_download ? var.iso_url : ""
    iso_checksum     = var.iso_checksum
    iso_download_pve = var.iso_download_pve
    unmount          = var.iso_unmount
  }

  dynamic "additional_iso_files" {
    for_each = var.additional_iso_files
    content {
      iso_file         = var.iso_download ? "" : "${var.storage_iso}:iso/${additional_iso_files.value.iso_file}"
      iso_storage_pool = var.storage_iso
      iso_url          = var.iso_download ? additional_iso_files.value.iso_url :  ""
      iso_checksum     = additional_iso_files.value.iso_checksum
      iso_download_pve = var.iso_download_pve
      unmount          = var.iso_unmount
    }
  }

  dynamic "additional_iso_files" {
    for_each = local.additional_cd_files
    iterator = iso
    content {
      type             = iso.value.type
      index            = iso.value.index
      iso_storage_pool = var.storage_iso
      cd_files         = contains(keys(iso.value), "files") ? iso.value.files : []
      cd_content       = contains(keys(iso.value), "content") ? iso.value.content : {}
      cd_label         = contains(keys(iso.value), "label") ? iso.value.label :  ""
      unmount          = var.iso_unmount
    }
  }

  cloud_init              = var.cloud_init
  cloud_init_storage_pool = var.storage_pool

  http_directory    = var.http_directory != "" ? var.http_directory : "${path.root}/http"
  http_bind_address = var.http_bind_address
  http_port_min     = var.http_port
  http_port_max     = var.http_port

  boot         = "order=${var.disk_type}0;ide2;net0"
  boot_wait    = var.boot_wait
  boot_command = var.boot_command
  task_timeout = var.task_timeout

  communicator         = var.communicator
  ssh_username         = var.ssh_username
  ssh_private_key_file = local.ssh_key_file
  ssh_password         = local.ssh_password
  ssh_timeout          = var.ssh_timeout

  winrm_username = var.winrm_username
  winrm_password = var.winrm_password
  winrm_insecure = var.winrm_insecure
  winrm_use_ssl  = var.winrm_use_ssl
}

build {
  name    = "linux"
  sources = ["source.proxmox-iso.vm"]

  provisioner "shell" {
    execute_command = "echo '${local.sudo_password}' | {{ .Vars }} sudo -S -E sh -eux '{{ .Path }}'"
    inline          = length(var.provisioner) > 0 ? var.provisioner : ["echo 'No provisioning commands specified'"]
  }
}

build {
  name    = "windows"
  sources = ["source.proxmox-iso.vm"]

  provisioner "file" {
    content = templatefile("${path.root}/../shared/http/sysprep-unattend.xml.pkrtpl", {
      winrm_password         = var.winrm_password
      windows_language       = var.windows_language
      windows_input_language = var.windows_input_language
    })
    destination = "C:\\Windows\\Panther\\unattend.xml"
  }

  provisioner "powershell" {
    script = "${path.root}/../shared/scripts/prepare-template.ps1"
  }
}