# ubuntu-24.04.pkrvars.hcl
# Purpose: Define Ubuntu 24.04 LTS template parameters for Proxmox build
# Maintainer: HybridOps.Tech
# Date: 2025-11-13

name        = "ubuntu-24.04-template"
description = "Ubuntu 24.04.3 LTS - Proxmox Template"
pool        = ""

iso_file     = "ubuntu-24.04.3-live-server-amd64.iso"
iso_url      = "https://releases.ubuntu.com/noble/ubuntu-24.04.3-live-server-amd64.iso"
iso_checksum = "sha256:c3514bf0056180d09376462a7a1b4f213c1d6e8ea67fae5c25099c6fd3d8274b"

boot_wait      = "12s"
boot_command   = [
  "<esc><wait5s>",
  "c<wait5s>",
  "linux /casper/vmlinuz --- autoinstall ds=nocloud-net\\;s=http://{{ .HTTPIP }}:{{ .HTTPPort }}/<enter><wait5s>",
  "initrd /casper/initrd<enter><wait5s>",
  "boot<enter>"
]

# Some environments take longer (ISO cache miss, slow mirrors, etc).
ssh_timeout = "20m"

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
  "echo 'Ubuntu 24.04 template ready'"
]
