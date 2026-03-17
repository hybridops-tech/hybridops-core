# Ansible Role: EVE-NG

Automated installation and configuration of the EVE-NG (Emulated Virtual Environment – Next Generation) network emulation platform on Ubuntu 22.04 LTS.

This role provisions EVE-NG Community Edition with configurable resource profiles, multi-user support, system optimisation, and optional health validation. It is intended for governed platform deployments that require repeatable and auditable infrastructure.

## Requirements

### System

- Ubuntu 22.04 LTS (Jammy)
- Minimum 4GB RAM (8GB+ recommended for production)
- Minimum 40GB disk space
- CPU with hardware virtualisation extensions (Intel VT-x or AMD-V)
- Nested virtualisation enabled on the hypervisor

### Ansible

- Ansible==10.* or later
- Python 3.8 or later
- Root privileges (`become: yes`)

## Role Variables

### Installation

```yaml
eveng_force_reinstall: false
```

Controls whether EVE-NG is reinstalled when an existing installation is detected.

### Resource Profiles

```yaml
eveng_resource_profile: standard  # minimal | standard | performance
```

Profile presets:

| Profile        | Upload Max | Post Max | Memory | Execution | Workload                       |
|----------------|-----------:|---------:|-------:|----------:|--------------------------------|
| `minimal`      |      500M  |     500M |  256M  |     300s  | Testing, constrained resources |
| `standard`     |        2G  |       2G |  512M  |     600s  | Small to medium topologies    |
| `performance`  |       10G  |      10G |    2G  |    1200s  | Production, large deployments |

Profiles adjust PHP limits and other runtime settings automatically.

### System Configuration

```yaml
eveng_configure_sysctl: true   # Apply kernel networking parameters
eveng_disable_swap: true       # Disable swap for VM performance
eveng_hostname: "{{ inventory_hostname }}"
```

Kernel parameters applied when `eveng_configure_sysctl: true`:

- `net.ipv4.ip_forward=1`
- `net.ipv4.conf.all.rp_filter=0`
- `net.ipv4.conf.default.rp_filter=0`

### Credentials

```yaml
eveng_root_password: "{{ lookup('env', 'EVENG_ROOT_PASSWORD') | default('eve', true) }}"
eveng_admin_password: "{{ lookup('env', 'EVENG_ADMIN_PASSWORD') | default('eve', true) }}"
```

Default credentials (`admin/eve`) are not suitable for production and must be changed as part of a governed deployment.

Credential management options:

#### Environment variables

```bash
export EVENG_ROOT_PASSWORD="platform-root-pass"
export EVENG_ADMIN_PASSWORD="platform-admin-pass"

ansible-playbook deploy.yml
```

#### Ansible Vault

```yaml
# group_vars/eveng/vault.yml (encrypted)
vault_eveng_root_password: "platform-root-pass"
vault_eveng_admin_password: "platform-admin-pass"
```

```yaml
# playbook variables
eveng_root_password: "{{ vault_eveng_root_password }}"
eveng_admin_password: "{{ vault_eveng_admin_password }}"
```

#### CLI override

```bash
ansible-playbook deploy.yml   -e eveng_root_password="platform-root-pass"   -e eveng_admin_password="platform-admin-pass"
```

### User Management

```yaml
eveng_users: []
```

Defines additional user accounts with automatic lab directory provisioning:

```yaml
eveng_users:
  - username: operator1
    name: Platform Operator
    email: operator1@example.com
    password: "{{ vault_operator1_password }}"
    role: admin
  - username: engineer1
    name: Network Engineer
    email: engineer1@example.com
    password: "{{ vault_engineer1_password }}"
    role: user
```

Roles:

- `admin` – system administration, user management, full access
- `user` – lab access only

Lab directories are created at `/opt/unetlab/labs/<username>/` with `www-data:www-data` ownership.

### PHP Configuration

```yaml
eveng_configure_php: true
eveng_php_upload_max: "2G"
eveng_php_post_max: "2G"
eveng_php_max_execution: "600"
eveng_php_memory_limit: "512M"
```

Resource profiles override these defaults where appropriate.

### Optional

```yaml
eveng_db_password: ""          # Custom MySQL password for the EVE-NG database user
eveng_environment_name: ""     # Environment label (for example: production, staging, dev)
```

## Dependencies

Ansible collections:

```yaml
# requirements.yml
collections:
  - name: community.mysql
  - name: ansible.posix
```

Install collections:

```bash
ansible-galaxy collection install -r requirements.yml
```

## Example Playbooks

### Basic Deployment

```yaml
---
- name: Deploy EVE-NG
  hosts: eveng
  become: yes

  roles:
    - role: hybridops.app.eveng
      vars:
        eveng_admin_password: "{{ vault_eveng_admin_password }}"
        eveng_root_password: "{{ vault_eveng_root_password }}"
```

### Production Configuration

```yaml
---
- name: Deploy EVE-NG Production
  hosts: eveng_production
  become: yes

  vars:
    eveng_resource_profile: performance
    eveng_admin_password: "{{ vault_eveng_admin_password }}"
    eveng_root_password: "{{ vault_eveng_root_password }}"
    eveng_disable_swap: true
    eveng_hostname: "eveng-prod-01"
    eveng_environment_name: production

  roles:
    - hybridops.app.eveng
```

### Multi-User Topology

```yaml
---
- name: Deploy Multi-User EVE-NG
  hosts: eveng_lab
  become: yes

  vars:
    eveng_resource_profile: performance
    eveng_admin_password: "{{ vault_eveng_admin_password }}"
    eveng_users:
      - username: lead_operator
        name: Lead Network Operator
        email: lead@example.com
        password: "{{ vault_lead_password }}"
        role: admin
      - username: engineer1
        email: engineer1@example.com
        password: "{{ vault_engineer1_password }}"
        role: user
      - username: engineer2
        email: engineer2@example.com
        password: "{{ vault_engineer2_password }}"
        role: user

  roles:
    - hybridops.app.eveng
```

### With Health Validation

```yaml
---
- name: Deploy and validate EVE-NG
  hosts: eveng
  become: yes

  tasks:
    - name: Install EVE-NG
      include_role:
        name: hybridops.app.eveng
      vars:
        eveng_resource_profile: standard
        eveng_admin_password: "{{ vault_eveng_admin_password }}"

    - name: Validate installation
      include_role:
        name: hybridops.helper.eveng_healthcheck
      vars:
        health_check_level: basic
        health_check_fail_on_warning: true
```

## Testing

Role testing is intended to use Molecule with backing infrastructure that supports nested virtualisation.

Test coverage targets:

- Package installation and service configuration
- Database schema initialisation
- API authentication and endpoint reachability
- KVM and nested virtualisation support
- Directory structure and file permissions
- User account and lab directory provisioning

Example commands:

```bash
cd roles/eveng
molecule test
```

Health check validation:

```bash
ansible-playbook -i inventory playbooks/healthcheck.yml
```

## Post-Installation

### Access

- Web interface: `https://<server-ip>`  
  - Administrator account: `admin` with the value of `eveng_admin_password`
- SSH: `ssh root@<server-ip>`  
  - Password: value of `eveng_root_password`

### Validation

Health checks can be executed using the associated healthcheck playbook:

```bash
ansible-playbook -i inventory playbooks/healthcheck.yml
```

The healthcheck role validates:

- Service status (Apache, MySQL)
- Database schema and connectivity
- API authentication and endpoints
- Virtualisation support (KVM module, nested virtualisation)
- Directory structure and permissions

### Next Steps

- Upload network device images using the associated image management role
- Deploy lab topologies using the associated lab deployment role
- Integrate with monitoring and backup procedures

## Available Tags

Tags enable targeted execution of subsets of the role.

Examples:

```bash
ansible-playbook playbook.yml --tags install    # Installation only
ansible-playbook playbook.yml --tags users      # User management only
ansible-playbook playbook.yml --tags profiles   # Resource profiles only
ansible-playbook playbook.yml --tags eveng      # Full deployment
```

Common tags:

- `eveng` – all tasks
- `install` – installation
- `setup` – configuration and setup
- `config` – configuration only
- `profiles` – resource profile application
- `users` – user management

## Troubleshooting

### Virtualisation Not Available

Check CPU virtualisation support:

```bash
egrep -c '(vmx|svm)' /proc/cpuinfo
```

A value of `0` indicates that hardware virtualisation is not exposed to the guest. Required actions in that case:

- Enable virtualisation extensions in system firmware (BIOS or UEFI)
- For nested virtualisation, enable the relevant setting in the hypervisor configuration

### Permission Errors

Ensure that privilege escalation is enabled in the playbook:

```yaml
- hosts: eveng
  become: yes
  roles:
    - hybridops.app.eveng
```

### Verification Failures

Execute a detailed health check to obtain diagnostics:

```bash
ansible-playbook -i inventory playbooks/healthcheck.yml   -e health_check_level=full
```

## Security

### Credentials

- Default credentials are not acceptable for production deployments.
- Use Ansible Vault or environment variables for all sensitive values.
- Avoid committing plaintext credentials to version control.

### File Permissions

- Lab directories: `/opt/unetlab/labs/<username>/` owned by `www-data:www-data`, mode `0755`
- Configuration files: restricted permissions applied during installation
- SSH root login: enabled as required by the EVE-NG operating model and should be controlled by upstream access policies

### Network Security

Recommended controls for platform-grade deployments:

- Host firewall rules (for example, UFW or iptables)
- TLS for HTTPS access to the web interface
- VPN access for remote connectivity
- Network segmentation for isolating lab traffic

## Related Roles

- `hybridops.helper.eveng_healthcheck` – health monitoring and validation
- `hybridops.helper.eveng_images` – device image management
- `hybridops.helper.eveng_labs` – lab topology deployment

## Documentation

Further context is provided in the HybridOps.Tech documentation set, including:

- Platform documentation and operational runbooks
- Lifecycle guidance for EVE-NG platform operations
- Licensing overview

## License

MIT.

See the [HybridOps.Tech licensing overview](https://docs.hybridops.tech/briefings/legal/licensing/)
for project-wide licence details, including branding and trademark notes.

## Author

HybridOps Team.

Repository and collection metadata are maintained in the central HybridOps.Tech namespace.
