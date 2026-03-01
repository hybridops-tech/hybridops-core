# ubuntu-22.04.pkrvars.hcl
# Purpose: Define Ubuntu 22.04 LTS template parameters for Proxmox build
# Maintainer: HybridOps.Studio
# Date: 2025-11-13

name        = "ubuntu-22.04-template"
description = "Ubuntu 22.04.5 LTS - Proxmox Template"
pool        = ""

iso_file     = "ubuntu-22.04.5-live-server-amd64.iso"
iso_url      = "https://releases.ubuntu.com/jammy/ubuntu-22.04.5-live-server-amd64.iso"
iso_checksum = "sha256:9bc6028870aef3f74f4e16b900008179e78b130e6b0b9a140635434a46aa98b0"

boot_wait      = "12s"
boot_command   = [
  "<esc><wait5s>",
  "c<wait5s>",
  "linux /casper/vmlinuz --- autoinstall ds=nocloud-net\\;s=http://{{ .HTTPIP }}:{{ .HTTPPort }}/<enter><wait5s>",
  "initrd /casper/initrd<enter><wait5s>",
  "boot<enter>"
]

provisioner = [
  "cloud-init status --wait || true",
  "sudo rm -f /etc/cloud/cloud.cfg.d/90-installer-network.cfg",
  "sudo rm -f /etc/cloud/cloud.cfg.d/99-installer.cfg",
  "sudo rm -f /etc/netplan/00-installer-config.yaml",
  "sudo bash -c 'cat > /etc/netplan/01-netcfg.yaml <<EOF\nnetwork:\n  version: 2\n  ethernets:\n    id0:\n      match:\n        name: \"e*\"\n      dhcp4: true\nEOF'",
  "sudo netplan generate || true",
  "sudo rm -f /etc/machine-id /var/lib/dbus/machine-id",
  "sudo truncate -s 0 /etc/machine-id",
  "sudo ln -sf /etc/machine-id /var/lib/dbus/machine-id",
  "sudo rm -f /etc/ssh/ssh_host_*",
  "sudo cloud-init clean --logs --seed || true",
  "echo 'Ubuntu 22.04 template ready'"
]