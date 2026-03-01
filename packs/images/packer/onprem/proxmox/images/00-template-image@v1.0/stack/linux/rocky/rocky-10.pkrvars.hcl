name           = "rocky-10-template"
description    = "Rocky Linux 10.0 - Proxmox Template"
pool           = ""

iso_file         = "Rocky-10.0-x86_64-minimal.iso"
iso_url          = "https://download.rockylinux.org/pub/rocky/10/isos/x86_64/Rocky-10.0-x86_64-minimal.iso"
iso_checksum     = "sha256:de75c2f7cc566ea964017a1e94883913f066c4ebeb1d356964e398ed76cadd12"

http_directory = "http"
boot_wait      = "10s"

boot_command = [
  "<up><wait>",
  "e<wait>",
  "<down><down><end>",
  " inst.text inst.ks=http://{{ .HTTPIP }}:{{ .HTTPPort }}/ks.cfg",
  "<leftCtrlOn>x<leftCtrlOff>"
]

provisioner = [
  "echo 'Rocky 10 template ready'"
]