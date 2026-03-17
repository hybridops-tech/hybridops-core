# rocky-9.pkrvars.hcl
# Purpose: Define Rocky Linux 9.6 template parameters for Proxmox build
# Maintainer: HybridOps.Tech
# Date: 2025-11-13

name           = "rocky-9-template"
description    = "Rocky Linux 9.6 - Proxmox Template"
# Leave vmid unset here so shipped defaults remain collision-safe across user Proxmox environments.
# Operators can set `vmid` in module inputs (for example 9001 in a reserved template range) if desired.
pool           = ""

iso_file       = "Rocky-9.6-x86_64-minimal.iso"
iso_url        = "https://download.rockylinux.org/pub/rocky/9.6/isos/x86_64/Rocky-9.6-x86_64-minimal.iso"
iso_checksum   = "sha256:aed9449cf79eb2d1c365f4f2561f923a80451b3e8fdbf595889b4cf0ac6c58b8"

http_directory = "http"
boot_wait      = "10s"
boot_command   = ["<tab> text inst.ks=http://{{ .HTTPIP }}:{{ .HTTPPort }}/ks.cfg<enter><wait>"]

provisioner = [
  "echo 'Rocky 9 template ready'"
]
