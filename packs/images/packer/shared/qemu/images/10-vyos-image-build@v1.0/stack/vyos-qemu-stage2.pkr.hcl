packer {
  required_plugins {
    qemu = {
      version = ">= 1.1.0"
      source  = "github.com/hashicorp/qemu"
    }
  }
}

variable "source_disk_path" {
  type        = string
  description = "Installed VyOS disk produced by the stage-1 ISO install."
}

variable "build_output_directory" {
  type        = string
  description = "Directory where the stage-2 qemu builder writes its validated disk output."
}

variable "vm_name" {
  type        = string
  default     = "hyops-vyos-build"
  description = "Temporary VM name used during the local qemu build VM."
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

variable "debian_host_ipv4" {
  type        = string
  default     = ""
  description = "Optional host-resolved IPv4 for deb.debian.org injected into /etc/hosts as a DNS fallback."
}

variable "security_host_ipv4" {
  type        = string
  default     = ""
  description = "Optional host-resolved IPv4 for security.debian.org injected into /etc/hosts as a DNS fallback."
}

variable "installed_boot_wait" {
  type        = string
  default     = "30s"
  description = "Wait time before Packer starts probing SSH on the installed VyOS disk."
}

variable "installed_boot_command" {
  type        = list(string)
  default     = []
  description = "Console commands used on the installed VyOS disk before Packer starts the SSH communicator."
}

variable "ssh_username" {
  type        = string
  default     = "vyos"
  description = "SSH username Packer should use after the installed system boots."
}

variable "ssh_password" {
  type        = string
  default     = "vyos"
  sensitive   = true
  description = "SSH password Packer should use after the installed system boots."
}

variable "ssh_timeout" {
  type        = string
  default     = "45m"
  description = "How long Packer waits for SSH after the installed system boots."
}

variable "shutdown_command" {
  type        = string
  default     = "sudo -n poweroff"
  sensitive   = true
  description = "Command used by Packer to stop the built VM after provisioning."
}

source "qemu" "vyos" {
  accelerator      = var.qemu_accelerator
  iso_url          = var.source_disk_path
  iso_checksum     = "none"
  output_directory = var.build_output_directory
  vm_name          = "${var.vm_name}-stage2"
  headless         = var.headless
  memory           = var.memory
  cpus             = var.cpus
  disk_image       = true
  disk_interface   = "virtio"
  net_device       = "virtio-net"
  boot_wait        = var.installed_boot_wait
  boot_command     = var.installed_boot_command
  communicator     = "ssh"
  ssh_username     = var.ssh_username
  ssh_password     = var.ssh_password
  ssh_timeout      = var.ssh_timeout
  shutdown_command = var.shutdown_command
  qemu_binary      = var.qemu_binary
  qemuargs = [
    ["-serial", "stdio"],
  ]
}

build {
  sources = ["source.qemu.vyos"]

  provisioner "file" {
    source      = "${path.root}/../../../../../../../../tools/build/vyos/assets/cc_vyos.py"
    destination = "/tmp/cc_vyos.py"
  }

  provisioner "shell" {
    inline = [
      "set -euxo pipefail",
      "if ! command -v apt-get >/dev/null 2>&1; then echo 'apt-get is required to install cloud-init on the built VyOS image' >&2; exit 1; fi",
      "if ! (grep -RqsE '^[[:space:]]*deb[[:space:]]' /etc/apt/sources.list /etc/apt/sources.list.d/*.list 2>/dev/null); then sudo -n sh -c \"cat > /etc/apt/sources.list.d/hybridops-debian.list <<'EOF'\ndeb http://deb.debian.org/debian bookworm main contrib non-free-firmware\ndeb http://deb.debian.org/debian bookworm-updates main contrib non-free-firmware\ndeb http://security.debian.org/debian-security bookworm-security main contrib non-free-firmware\nEOF\"; fi",
      "if ! ip route show default | grep -q . || ! ping -c1 -W1 10.0.2.2 >/dev/null 2>&1; then nic=\"$(ip -o link show | awk -F': ' '$2 !~ /^lo$/ {print $2; exit}')\"; if [ -n \"$nic\" ]; then sudo -n dhclient \"$nic\" || true; fi; fi",
      "if [ -f /etc/nsswitch.conf ]; then sudo -n sed -i -E 's/^hosts:.*/hosts: files dns/' /etc/nsswitch.conf; fi",
      "sudo -n sh -c \"printf '%s\\\\n' 'nameserver 10.0.2.3' 'nameserver 8.8.8.8' 'nameserver 1.1.1.1' > /etc/resolv.conf\"",
      "if [ -n '${var.debian_host_ipv4}' ]; then sudo -n sh -c \"printf '%s\\\\n' '${var.debian_host_ipv4} deb.debian.org' '${var.debian_host_ipv4} debian.map.fastlydns.net' >> /etc/hosts\"; fi",
      "if [ -n '${var.security_host_ipv4}' ]; then sudo -n sh -c \"printf '%s\\\\n' '${var.security_host_ipv4} security.debian.org' >> /etc/hosts\"; fi",
      "if ! getent hosts deb.debian.org >/dev/null 2>&1; then echo 'WARN: getent could not resolve deb.debian.org; continuing to apt probe'; cat /etc/hosts || true; fi",
      "if ! getent hosts security.debian.org >/dev/null 2>&1; then echo 'WARN: getent could not resolve security.debian.org; continuing to apt probe'; cat /etc/hosts || true; fi",
      "sudo -n sh -c \"cat > /etc/apt/apt.conf.d/99force-ipv4 <<'EOF'\nAcquire::ForceIPv4 \\\"true\\\";\nAcquire::Retries \\\"4\\\";\nEOF\"",
      "sudo -n env DEBIAN_FRONTEND=noninteractive apt-get update || { echo 'apt-get update failed'; cat /etc/resolv.conf || true; cat /etc/hosts || true; ip route || true; exit 1; }",
      "sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y cloud-init cloud-guest-utils qemu-guest-agent",
      "if ! command -v cloud-init >/dev/null 2>&1; then echo 'cloud-init install did not produce a cloud-init binary' >&2; exit 1; fi",
      "if ! dpkg-query -W -f='$${Status}' qemu-guest-agent 2>/dev/null | grep -q 'install ok installed'; then echo 'qemu-guest-agent package is required for Proxmox cloud images' >&2; exit 1; fi",
      "if [ -f /tmp/cc_vyos.py ]; then sudo -n install -D -m 0644 /tmp/cc_vyos.py /usr/lib/python3/dist-packages/cloudinit/config/cc_vyos.py; fi",
      "if [ ! -f /usr/lib/python3/dist-packages/cloudinit/config/cc_vyos.py ]; then echo 'VyOS cloud-init module (cc_vyos.py) is missing; this artifact will not process vyos_config_commands correctly. Use the official vyos-vm-images cloud_init=true builder path.' >&2; exit 1; fi",
      "sudo -n python3 - <<'PY'\nfrom pathlib import Path\n\npath = Path('/etc/cloud/cloud.cfg')\ntext = path.read_text(encoding='utf-8')\nlines = text.splitlines()\n\nif any(line.strip() == '- vyos' for line in lines):\n    raise SystemExit(0)\n\nstart = None\nfor idx, line in enumerate(lines):\n    if line.strip() == 'cloud_config_modules:':\n        start = idx\n        break\n\nif start is None:\n    lines.extend(['', 'cloud_config_modules:', ' - vyos'])\nelse:\n    insert_at = start + 1\n    while insert_at < len(lines):\n        row = lines[insert_at]\n        stripped = row.strip()\n        if stripped == '' or row.startswith(' - ') or row.startswith('- '):\n            insert_at += 1\n            continue\n        break\n    lines.insert(insert_at, ' - vyos')\n\npath.write_text('\\n'.join(lines) + '\\n', encoding='utf-8')\nPY",
      "sudo -n install -d -m 0755 /etc/cloud/cloud.cfg.d",
      "sudo -n sh -c \"printf '%s\\\\n' 'datasource_list: [ NoCloud, Hetzner, ConfigDrive, None ]' 'ssh_pwauth: true' 'preserve_hostname: false' 'network: {config: enabled}' > /etc/cloud/cloud.cfg.d/99-hybridops.cfg\"",
      "sudo -n rm -f /etc/cloud/cloud.cfg.d/99-hybridops-proxmox.cfg",
      "if command -v systemctl >/dev/null 2>&1; then sudo -n systemctl enable cloud-init-local.service cloud-init.service cloud-config.service cloud-final.service qemu-guest-agent.service; fi",
      "sudo -n cloud-init clean --logs",
      "sudo -n rm -rf /var/lib/cloud/instance /var/lib/cloud/instances /var/lib/cloud/data /var/lib/cloud/sem",
      "# Preserve baseline interface DHCP config written during stage-2 console bootstrap.",
      "if [ ! -d /etc/cloud ] || [ ! -f /etc/cloud/cloud.cfg.d/99-hybridops.cfg ]; then echo 'cloud-init configuration was not written to /etc/cloud in the image build context' >&2; exit 1; fi",
      "sudo -n sync",
    ]
  }
}
