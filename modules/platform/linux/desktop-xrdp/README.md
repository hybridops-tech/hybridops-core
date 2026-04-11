# platform/linux/desktop-xrdp

Install XFCE4 and XRDP on an Ubuntu 22.04 host. After the module runs, the VM is reachable via any
standard RDP client on port 3389.

## Prereqs

- Target VM is running Ubuntu 22.04 and is reachable via SSH.
- `XRDP_USER_PASSWORD` is present in the bootstrap vault. Generate it if not already set:
  ```bash
  hyops secrets ensure --env <env> XRDP_USER_PASSWORD
  ```
  Retrieve it after deployment with `hyops secrets show --env <env>`.
- Port 3389 is open to your client (use `platform/gcp/vm-firewall-rules` or equivalent).

## How it works

1. Installs `xfce4`, `xfce4-goodies`, and `xrdp` via apt.
2. Writes an `.xsession` file for the target user selecting the XFCE4 session.
3. Sets the login password for the RDP user from `XRDP_USER_PASSWORD`.
4. Enables and starts the `xrdp` systemd service.

## Inputs

| Input | Default | Notes |
|---|---|---|
| `inventory_state_ref` | — | State ref to `platform/gcp/platform-vm` output |
| `inventory_vm_groups` | — | VM group → key list for Ansible inventory |
| `target_user` | `opsadmin` | SSH user for Ansible connection; also the default RDP login user |
| `xrdp_user` | `""` | Override the RDP session user (defaults to `target_user`) |
| `xrdp_user_password_env` | `XRDP_USER_PASSWORD` | Vault env var holding the RDP login password |
| `ssh_access_mode` | `direct` | `direct` for public IP VMs; `gcp-iap` for private VMs |
| `ssh_private_key_file` | `""` | Path to SSH private key |

## Usage

```bash
hyops apply --env dev \
  --module platform/linux/desktop-xrdp \
  --inputs "$HYOPS_CORE_ROOT/modules/platform/linux/desktop-xrdp/examples/inputs.min.yml"
```

## Outputs

- `rdp_host` — IP or hostname to connect to
- `rdp_port` — always `3389`
- `rdp_user` — the configured RDP login user
