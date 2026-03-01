# variables.global.pkr.hcl
# Global variable definitions for Packer OS template builds
# Author: HybridOps Platform Team
# Last modified: 2025-12-24

# Proxmox connection
variable "proxmox_url" {
  type        = string
  description = "Proxmox API URL"
  default     = ""
}

variable "proxmox_token_id" {
  type        = string
  description = "Proxmox API token ID (format: user@realm! tokenname)"
  default     = ""
}

variable "proxmox_token_secret" {
  type        = string
  description = "Proxmox API token secret"
  sensitive   = true
  default     = ""
}

variable "proxmox_node" {
  type        = string
  description = "Proxmox node name"
  default     = ""
}

variable "proxmox_skip_tls" {
  type        = bool
  description = "Skip TLS certificate verification"
  default     = false
}

variable "proxmox_ssh_username" {
  type        = string
  description = "SSH username for Proxmox host (used by Packer plugin)"
  default     = "root"
}

variable "proxmox_ssh_key" {
  type        = string
  description = "Path to SSH private key for Proxmox host"
  default     = "~/.ssh/id_ed25519"
}

# Storage
variable "storage_pool" {
  type        = string
  description = "Storage pool for VM disks and cloud-init"
  default     = ""
}

variable "storage_snippets" {
  type        = string
  description = "Storage pool for cloud-init snippets (Terraform only)"
  default     = ""
}

variable "storage_iso" {
  type        = string
  description = "Storage pool for ISO files"
  default     = ""
}

variable "ssh_password_hash" {
  type        = string
  description = "SHA-512 password hash for Linux autoinstall/cloud-init identity.password"
  sensitive   = true
  default     = ""
}

# Network
variable "network_bridge" {
  type        = string
  description = "Network bridge"
  default     = "vmbr0"
}

variable "network_adapter_model" {
  type        = string
  description = "Network model"
  default     = "virtio"
}

variable "network_adapter_mac" {
  type        = string
  description = "Override MAC address"
  default     = null
}

variable "network_adapter_vlan" {
  type        = number
  description = "VLAN tag (-1 = none)"
  default     = -1
}

variable "network_adapter_firewall" {
  type        = bool
  description = "Enable Proxmox firewall"
  default     = false
}

# HTTP server for kickstart delivery
variable "http_bind_address" {
  type        = string
  description = "HTTP server bind address"
  default     = ""
}

variable "http_port" {
  type        = number
  description = "HTTP server port"
  default     = 0
}

variable "http_directory" {
  type        = string
  description = "HTTP directory path"
  default     = "http"
}

# VM metadata
variable "vmid" {
  type        = number
  description = "VM ID (auto-assigned if 0)"
  default     = 0
}

variable "name" {
  type        = string
  description = "VM template name"
}

variable "description" {
  type        = string
  description = "VM template description"
  default     = ""
}

variable "pool" {
  type        = string
  description = "Resource pool name"
  default     = ""
}

# ISO configuration
variable "iso_file" {
  type        = string
  description = "ISO filename on Proxmox storage"
}

variable "iso_url" {
  type        = string
  description = "ISO download URL"
  default     = ""
}

variable "iso_checksum" {
  type        = string
  description = "ISO checksum (format: sha256:...)"
  default     = ""
}

variable "iso_download" {
  type        = bool
  description = "Download ISO if not found"
  default     = false
}

variable "iso_download_pve" {
  type        = bool
  description = "Download ISO directly from PVE node"
  default     = false
}

variable "iso_unmount" {
  type        = bool
  description = "Unmount ISO after installation"
  default     = true
}

variable "additional_iso_files" {
  type = list(object({
    iso_file     = string
    iso_url      = string
    iso_checksum = string
  }))
  description = "Additional ISO files (e.g. VirtIO drivers)"
  default     = []
}

# Hardware
variable "disk_size" {
  type        = string
  description = "Disk size (e.g. 20G)"
  default     = "10G"
}

variable "disk_format" {
  type        = string
  description = "Disk format"
  default     = "raw"
}

variable "disk_type" {
  type        = string
  description = "Disk type (scsi, sata, virtio)"
  default     = "scsi"
}

variable "disk_cache" {
  type        = string
  description = "Disk cache mode"
  default     = "none"
}

variable "cpu_type" {
  type        = string
  description = "CPU type to emulate"
  default     = "host"
}

variable "cpu_sockets" {
  type        = number
  description = "Number of CPU sockets"
  default     = 1
}

variable "cpu_cores" {
  type        = number
  description = "Cores per socket"
  default     = 2
}

variable "memory" {
  type        = number
  description = "RAM in MB"
  default     = 4096
}

variable "os" {
  type        = string
  description = "OS type (l26/win10/win11)"
  default     = "l26"
}

variable "scsi_controller" {
  type        = string
  description = "SCSI controller model"
  default     = "virtio-scsi-pci"
}

variable "vga_type" {
  type        = string
  description = "VGA type"
  default     = "std"
}

variable "vga_memory" {
  type        = number
  description = "VGA memory (MiB)"
  default     = 32
}

variable "bios" {
  type        = string
  description = "BIOS type (seabios/ovmf)"
  default     = "seabios"
}

variable "qemu_agent" {
  type        = bool
  description = "Enable QEMU guest agent"
  default     = true
}

variable "start_at_boot" {
  type        = bool
  description = "Auto-start VM"
  default     = true
}

# Boot configuration
variable "boot_wait" {
  type        = string
  description = "Delay before boot command"
  default     = "5s"
}

variable "boot_command" {
  type        = list(string)
  description = "Boot command sequence"
  default     = []
}

variable "communicator" {
  type        = string
  description = "Packer communicator (ssh/winrm)"
  default     = "ssh"
}

variable "task_timeout" {
  type        = string
  description = "Proxmox task timeout"
  default     = "5m"
}

# SSH configuration
variable "ssh_username" {
  type        = string
  description = "SSH username"
  default     = "opsadmin"
}

variable "ssh_password" {
  type        = string
  description = "SSH password"
  default     = "Temporary!"
  sensitive   = true
}

variable "ssh_private_key_file" {
  type        = string
  description = "Path to private key"
  default     = "~/.ssh/id_ed25519"
}

variable "ssh_public_key" {
  type        = string
  description = "SSH public key for authorized_keys"
  default     = ""
}

variable "ssh_timeout" {
  type        = string
  description = "SSH timeout"
  default     = "10m"
}

# Windows configuration
variable "winrm_username" {
  type        = string
  description = "WinRM username"
  default     = "Administrator"
}

variable "winrm_password" {
  type        = string
  description = "WinRM password"
  default     = "Temporary!"
  sensitive   = true
}

variable "winrm_insecure" {
  type        = bool
  description = "Skip WinRM SSL validation"
  default     = true
}

variable "winrm_use_ssl" {
  type        = bool
  description = "Use WinRM SSL"
  default     = false
}

variable "windows_edition" {
  type        = string
  description = "Windows edition"
  default     = ""
}

variable "windows_language" {
  type        = string
  description = "Windows display language"
  default     = "en-US"
}

variable "windows_input_language" {
  type        = string
  description = "Windows keyboard language"
  default     = "en-US"
}

variable "driver_version" {
  type        = string
  description = "VirtIO driver version (e.g., 2k22, 2k19)"
  default     = ""
}

# Cloud-init and unattended install
variable "cloud_init" {
  type        = bool
  description = "Enable Cloud-Init"
  default     = true
}

variable "unattended_content" {
  type = map(object({
    template = string
    vars     = map(string)
  }))
  description = "Unattended install templates"
  default     = {}
}

variable "additional_cd_files" {
  type = list(object({
    type  = string
    index = number
    files = list(string)
  }))
  description = "Additional CD/ISO attachments"
  default     = []
}

variable "provisioner" {
  type        = list(string)
  description = "Custom provisioning commands"
  default     = []
}

variable "windows_provisioner" {
  type        = list(string)
  description = "Custom PowerShell provisioning commands for Windows"
  default     = []
}
