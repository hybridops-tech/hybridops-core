#
# windows-11-enterprise.pkrvars.hcl
#
# Maintainer: HybridOps.Tech
# Organization: HybridOps.Tech
# Last Modified: 2025-11-13 09:58:00 UTC

name        = "windows-11-enterprise-template"
description = "Windows 11 Enterprise Evaluation - Proxmox Template"

iso_file     = "windows-11-enterprise-eval.iso"
iso_url      = "https://software-static.download.prss.microsoft.com/dbazure/888969d5-f34g-4e03-ac9d-1f9786c66749/26200.6584.250915-1905.25h2_ge_release_svc_refresh_CLIENTENTERPRISEEVAL_OEMRET_x64FRE_en-us.iso"
iso_checksum = "sha256:a61adeab895ef5a4db436e0a7011c92a2ff17bb0357f58b13bbc4062e535e7b9"

os   = "win11"
bios = "seabios"

cpu_type  = "host"
cpu_cores = 4
memory    = 8192

# CRITICAL: Use SATA disk (no VirtIO driver issues)
disk_type   = "sata"
disk_size   = "20G"
disk_format = "raw"

communicator = "winrm"

windows_edition        = "Windows 11 Enterprise Evaluation"
windows_language       = "en-US"
windows_input_language = "en-US"

http_directory = ""
boot_command   = []

additional_iso_files = [
  {
    iso_file     = "virtio-win-0.1.285.iso"
    iso_url      = "https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/archive-virtio/virtio-win-0.1.285-1/virtio-win-0.1.285.iso"
    iso_checksum = "sha256:e14cf2b94492c3e925f0070ba7fdfedeb2048c91eea9c5a5afb30232a3976331"
  }
]

unattended_content = {
  "/Autounattend.xml" = {
    template = "http/Autounattend-client.xml.pkrtpl"
    vars = {
      driver_version = "w11"
    }
  }
}