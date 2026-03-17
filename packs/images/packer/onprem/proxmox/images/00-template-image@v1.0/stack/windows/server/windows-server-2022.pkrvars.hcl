#
# windows-server-2022.pkrvars.hcl
#
# Packer variable definitions for Windows Server 2022 Evaluation template.
# Configures VM resources, installation media, and unattended setup parameters
# for automated Proxmox template creation.
#
# Maintainer: HybridOps.Tech
# Organization: HybridOps.Tech
# Created: 2025-11-12
# Last Modified: 2025-11-12

name        = "windows-server-2022-template"
description = "Windows Server 2022 Evaluation - Proxmox Template"

iso_file     = "windows-server-2022-eval.iso"
iso_url      = "https://go.microsoft.com/fwlink/p/?LinkID=2195280"
iso_checksum = "sha256:3e4fa6d8507b554856fc9ca6079cc402df11a8b79344871669f0251535255325"

os   = "win10"
bios = "seabios"

cpu_type    = "host"
cpu_cores   = 4
memory      = 8192
disk_size   = "60G"
disk_format = "raw"

communicator = "winrm"

windows_edition        = "Windows Server 2022 SERVERDATACENTER"
windows_language       = "en-US"
windows_input_language = "en-US"

additional_iso_files = [
  {
    iso_file     = "virtio-win-0.1.285.iso"
    iso_url      = "https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/archive-virtio/virtio-win-0.1.285-1/virtio-win-0.1.285.iso"
    iso_checksum = "sha256:e14cf2b94492c3e925f0070ba7fdfedeb2048c91eea9c5a5afb30232a3976331"
  }
]

unattended_content = {
  "/Autounattend.xml" = {
    template = "http/Autounattend-server.xml.pkrtpl"
    vars = {
      driver_version = "2k22"
    }
  }
}
