#cloud-config
# Ubuntu Packer template with dynamic SSH key injection.
# Template variables (replaced during rendering):
# Maintainer: HybridOps.Studio

autoinstall:
  version: 1
  locale: en_US.UTF-8
  keyboard:
    layout: us

  identity:
    hostname: localhost
    username: __VAR_ADMIN_USER__
    # Password: 'Temporary!' (must match ssh_password variable in Packer)
    password: __VAR_SSH_PASSWORD_HASH__

  ssh:
    install-server: true
    allow-pw: true
    authorized-keys:
    - __VAR_SSH_PUBLIC_KEY__

  network:
    version: 2
    ethernets:
      id0:
        match:
          name: "e*"
        dhcp4: true

  storage:
    layout:
      name: direct

  packages:
  - qemu-guest-agent
  - cloud-init
  - cloud-initramfs-growroot
  - openssh-server
  - python3

  late-commands:
  - curtin in-target --target=/target -- systemctl enable qemu-guest-agent
  - curtin in-target --target=/target -- systemctl enable ssh
  - |
    cat > /target/etc/sudoers.d/99-__VAR_ADMIN_USER__-ansible <<'SUDOEOF'
    # Bootstrap privilege for automated provisioning. Hardened later by configuration management.
    __VAR_ADMIN_USER__ ALL=(ALL) NOPASSWD:ALL
    SUDOEOF
  - chmod 0440 /target/etc/sudoers.d/99-__VAR_ADMIN_USER__-ansible
  - curtin in-target --target=/target -- visudo -c -f /etc/sudoers.d/99-__VAR_ADMIN_USER__-ansible
