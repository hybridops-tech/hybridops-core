# File: ks.cfg.tpl
# Purpose: Shared Kickstart template for Rocky Linux 9.x/10.x Packer builds
# Maintainer: HybridOps.Studio

cdrom
text

lang en_US.UTF-8
keyboard us
timezone UTC --utc

network --bootproto=dhcp --device=link --activate --onboot=yes
network --hostname=localhost.localdomain

rootpw --lock
    # Password: 'Temporary!' (must match ssh_password variable in Packer)
user --name=__VAR_ADMIN_USER__ --groups=wheel --iscrypted --password='__VAR_SSH_PASSWORD_HASH__'

firewall --disabled
selinux --permissive

zerombr
clearpart --all --initlabel
autopart --type=lvm
bootloader --location=mbr --boot-drive=sda

services --enabled=sshd,chronyd
skipx
reboot

%packages --ignoremissing
@core
@standard
qemu-guest-agent
sudo
curl
wget
python3
openssh-server
openssh-clients
-plymouth
%end

%post --log=/root/ks-post.log --interpreter=/bin/bash

ADMIN_USER="__VAR_ADMIN_USER__"
SUDOERS_FILE="/etc/sudoers.d/99-${ADMIN_USER}-ansible"

dnf install -y cloud-init cloud-utils-growpart || {
  echo "ERROR: Failed to install cloud-init" >> /root/ks-post.log
  exit 1
}

if rpm -q cloud-init >/dev/null 2>&1; then
  echo "cloud-init installed" >> /root/ks-post.log
  rpm -qa | grep cloud >> /root/ks-post.log
else
  echo "ERROR: cloud-init not installed" >> /root/ks-post.log
  exit 1
fi

authselect select sssd --force || true

install -d -m 0750 /etc/sudoers.d

cat > "${SUDOERS_FILE}" <<SUDOEOF
# Bootstrap privilege for automated provisioning. Hardened later by configuration management.
${ADMIN_USER} ALL=(ALL) NOPASSWD:ALL
SUDOEOF

chmod 0440 "${SUDOERS_FILE}"

visudo -c -f "${SUDOERS_FILE}" >/dev/null || {
  echo "ERROR: sudoers validation failed" >> /root/ks-post.log
  exit 1
}

install -d -m 0700 "/home/${ADMIN_USER}/.ssh"

cat > "/home/${ADMIN_USER}/.ssh/authorized_keys" <<'SSHEOF'
__VAR_SSH_PUBLIC_KEY__
SSHEOF

chmod 0600 "/home/${ADMIN_USER}/.ssh/authorized_keys"
chown -R "${ADMIN_USER}:${ADMIN_USER}" "/home/${ADMIN_USER}/.ssh"

mkdir -p /etc/ssh/sshd_config.d
cat > /etc/ssh/sshd_config.d/50-packer.conf <<'SSHDEOF'
PubkeyAuthentication yes
PasswordAuthentication yes
PermitRootLogin no
SSHDEOF

systemctl enable sshd.service
systemctl enable cloud-init-local.service
systemctl enable cloud-init.service
systemctl enable cloud-config.service
systemctl enable cloud-final.service
echo "cloud-init services enabled" >> /root/ks-post.log

if rpm -q qemu-guest-agent >/dev/null 2>&1; then
  systemctl unmask qemu-guest-agent.service || true
  systemctl enable qemu-guest-agent.service || true
  echo "qemu-guest-agent enabled" >> /root/ks-post.log
else
  echo "WARNING: qemu-guest-agent not installed" >> /root/ks-post.log
  dnf install -y qemu-guest-agent || echo "ERROR: Failed to install qemu-guest-agent" >> /root/ks-post.log
  systemctl enable qemu-guest-agent.service || true
fi

grubby --update-kernel=ALL --args="net.ifnames=0 biosdevname=0"
echo "Traditional network names enabled" >> /root/ks-post.log

mkdir -p /etc/cloud/cloud.cfg.d
cat > /etc/cloud/cloud.cfg.d/99_pve.cfg <<'CLOUDEOF'
datasource_list: [ ConfigDrive, NoCloud ]
disable_root: true
ssh_pwauth: true
manage_etc_hosts: true
preserve_hostname: false
CLOUDEOF

ROCKY_VERSION="$(grep -oP 'Rocky Linux release \K[0-9]+' /etc/rocky-release 2>/dev/null || echo "9")"
if [[ "${ROCKY_VERSION}" -ge 10 ]]; then
  cat > /etc/cloud/cloud.cfg.d/99-network-renderer.cfg <<'NETEOF'
system_info:
  network:
    renderers: ['network-manager']
NETEOF
  echo "cloud-init renderer: network-manager (Rocky ${ROCKY_VERSION})" >> /root/ks-post.log
else
  cat > /etc/cloud/cloud.cfg.d/99-network-renderer.cfg <<'NETEOF'
system_info:
  network:
    renderers: ['sysconfig']
NETEOF
  echo "cloud-init renderer: sysconfig (Rocky ${ROCKY_VERSION})" >> /root/ks-post.log
fi

passwd -l root

dnf clean all
rm -rf /var/cache/dnf /tmp/* /var/tmp/*
rm -f /etc/ssh/ssh_host_*
truncate -s 0 /etc/machine-id
rm -f /var/lib/dbus/machine-id
ln -sf /etc/machine-id /var/lib/dbus/machine-id
find /var/log -type f -exec truncate -s 0 {} \;

echo "Kickstart complete (Rocky ${ROCKY_VERSION})" >> /root/ks-post.log

%end
