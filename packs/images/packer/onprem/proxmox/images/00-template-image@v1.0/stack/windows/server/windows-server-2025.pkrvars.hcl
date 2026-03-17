#
# windows-server-2025.pkrvars.hcl
#
# Packer variable definitions for Windows Server 2025 Evaluation template.
# Configures VM resources, installation media, and unattended setup parameters
# for automated Proxmox template creation.
#
# Maintainer: HybridOps.Tech
# Organization: HybridOps.Tech
# Created: 2025-11-12
# Last Modified: 2025-11-12

name        = "windows-server-2025-template"
description = "Windows Server 2025 Evaluation - Proxmox Template"

iso_file     = "windows-server-2025-eval.iso"
iso_url      = "https://software-static.download.prss.microsoft.com/dbazure/888969d5-f34g-4e03-ac9d-1f9786c66749/26100.1742.240906-0331.ge_release_svc_refresh_SERVER_EVAL_x64FRE_en-us.iso"
iso_checksum = "sha256:d0ef4502e350e3c6c53c15b1b3020d38a5ded011bf04998e950720ac8579b23d"

os   = "win10"
bios = "seabios"

cpu_type    = "host"
cpu_cores   = 4
memory      = 8192
disk_size   = "60G"
disk_format = "raw"

communicator = "winrm"

windows_edition        = "Windows Server 2025 SERVERDATACENTER"
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
      driver_version = "2k25"
    }
  }
}
