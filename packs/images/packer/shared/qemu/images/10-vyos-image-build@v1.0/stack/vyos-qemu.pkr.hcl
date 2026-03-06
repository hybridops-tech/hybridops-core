packer {
  required_plugins {
    qemu = {
      version = ">= 1.1.0"
      source  = "github.com/hashicorp/qemu"
    }
  }
}

variable "source_iso_path" {
  type        = string
  description = "Local path to the VyOS installer ISO prepared by the wrapper."
}

variable "build_output_directory" {
  type        = string
  description = "Directory where the stage-1 qemu builder writes its installed disk output."
}

variable "vm_name" {
  type        = string
  default     = "hyops-vyos-build"
  description = "Temporary VM name used during the local qemu build."
}

variable "cpus" {
  type        = number
  default     = 2
  description = "vCPU count for the local qemu build VM."
}

variable "memory" {
  type        = number
  default     = 2048
  description = "Memory in MB for the local qemu build VM."
}

variable "disk_size" {
  type        = string
  default     = "8192M"
  description = "Disk size for the local qemu build VM."
}

variable "headless" {
  type        = bool
  default     = true
  description = "Run qemu without a graphical console."
}

variable "qemu_accelerator" {
  type        = string
  default     = "kvm"
  description = "QEMU accelerator to use for the build host. KVM is the expected production path; use 'tcg' only for explicit debug on non-KVM builders."
}

variable "qemu_binary" {
  type        = string
  default     = "qemu-system-x86_64"
  description = "QEMU system binary path."
}

variable "boot_wait" {
  type        = string
  default     = "30s"
  description = "Wait time before Packer starts sending stage-1 install boot commands."
}

variable "boot_command" {
  type        = list(string)
  default     = []
  description = "Release-specific console automation that installs the VyOS ISO onto the local disk and powers the VM off."
}

variable "shutdown_timeout" {
  type        = string
  default     = "15m"
  description = "How long Packer waits for the stage-1 installer flow to power the VM off after the final reboot command."
}

variable "serial_device" {
  type        = string
  default     = "stdio"
  description = "QEMU serial backend for stage-1 debugging. Use values like 'stdio' or 'file:/tmp/vyos-stage1-serial.log'."
}

variable "monitor_device" {
  type        = string
  default     = "none"
  description = "QEMU monitor backend for stage-1 debugging. Use values like 'none' or 'unix:/tmp/vyos-stage1-monitor.sock,server,nowait'."
}

source "qemu" "vyos" {
  accelerator       = var.qemu_accelerator
  iso_url           = var.source_iso_path
  iso_checksum      = "none"
  output_directory  = var.build_output_directory
  vm_name           = var.vm_name
  headless          = var.headless
  memory            = var.memory
  cpus              = var.cpus
  disk_size         = var.disk_size
  disk_interface    = "virtio"
  net_device        = "virtio-net"
  boot_wait         = var.boot_wait
  boot_command      = var.boot_command
  shutdown_timeout  = var.shutdown_timeout
  communicator      = "none"
  qemu_binary       = var.qemu_binary
  qemuargs = [
    ["-serial", var.serial_device],
    ["-monitor", var.monitor_device],
  ]
}

build {
  sources = ["source.qemu.vyos"]
}
