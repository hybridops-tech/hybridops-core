# eveng_healthcheck

Health monitoring and validation for EVE-NG installations.

## Description

The `eveng_healthcheck` role executes structured health checks against an EVE-NG deployment, validating configuration, core services, database access, API behaviour, virtualisation support, and optional images and labs. Multiple levels of verification are available to support smoke tests, operational checks, and scheduled audits.

## Requirements

- EVE-NG installed and reachable
- Ansible 2.9 or later
- Python 3.8 or later
- Root or sudo access (`become: yes`)
- `community.mysql` collection

## Role Variables

### Health Check Configuration

```yaml
# Scope of verification
# Options:
#   basic  – services, database, API, KVM
#   images – basic plus image inventory
#   full   – images plus lab-related checks
health_check_level: basic

# Control whether warnings cause playbook failure
health_check_fail_on_warning: false

# Report output format
# Options: summary, detailed, json
health_check_report_format: summary
```

### Component Control

Health checks are controlled by both the overall level and component flags.

- `health_check_level` defines the default scope.
- Component flags enable or disable specific checks.

A component runs only when the selected level includes it and the corresponding flag is `true`.

```yaml
# Component flags (auto-derived from health_check_level, but overridable)
health_check_services: true     # Apache, MySQL service status
health_check_database: true     # Database existence, tables, users
health_check_api: true          # API status, authentication
health_check_kvm: true          # KVM module, virtualisation support
health_check_images: false      # Image inventory (enabled for 'images' and 'full')
health_check_labs: false        # Lab checks (enabled for 'full')
```

### Authentication

```yaml
# Admin credentials for API authentication tests
eveng_admin_password: "{{ lookup('env', 'EVENG_ADMIN_PASSWORD') | default('eve', true) }}"
```

## Dependencies

Ansible collections:

- `community.mysql`

## Health Check Levels

### `basic` (default)

Scope:

- Service status (Apache, MySQL)
- Port listening checks (80, 443, 3306)
- Database connectivity
- API authentication
- KVM module status

Typical use cases: quick health checks, CI/CD validations, post-deployment smoke tests.

### `images`

Scope:

- All `basic` checks
- QEMU image inventory
- IOL image count
- Dynamips image count
- Common vendor image classification

Typical use cases: image deployment validation, pre-class readiness checks.

### `full`

Scope:

- All `basic` and `images` checks
- Lab file discovery
- Running node count
- Temporary directory usage
- Zombie process detection

Typical use cases: scheduled audits, detailed troubleshooting, pre-change verification in production environments.

## Example Playbooks

### Basic Health Check

```yaml
---
- name: Quick EVE-NG health check
  hosts: eveng
  become: yes

  roles:
    - hybridops.helper.eveng_healthcheck
```

### Full System Audit

```yaml
---
- name: Comprehensive EVE-NG audit
  hosts: eveng
  become: yes

  vars:
    health_check_level: full
    health_check_report_format: detailed
    health_check_fail_on_warning: true

  roles:
    - hybridops.helper.eveng_healthcheck
```

### Image Verification

```yaml
---
- name: Verify EVE-NG images
  hosts: eveng
  become: yes

  vars:
    health_check_level: images
    health_check_report_format: detailed

  roles:
    - hybridops.helper.eveng_healthcheck
```

### Custom Component Selection

```yaml
---
- name: Custom health checks
  hosts: eveng
  become: yes

  vars:
    health_check_level: basic
    health_check_images: true  # Add image checks to basic
    health_check_api: false    # Skip API checks

  roles:
    - hybridops.helper.eveng_healthcheck
```

### JSON Export for Monitoring

```yaml
---
- name: Export health metrics
  hosts: eveng
  become: yes

  vars:
    health_check_level: full
    health_check_report_format: json

  roles:
    - hybridops.helper.eveng_healthcheck

  post_tasks:
    - name: Save health report
      copy:
        content: "{{ health_check_results | to_nice_json }}"
        dest: "/var/log/eveng_health_{{ ansible_date_time.iso8601_basic_short }}.json"
```

## Tags

Tags support selective execution of specific health check components.

### Primary Component Tags

| Tag                     | Description          | Scope                                          |
|-------------------------|----------------------|------------------------------------------------|
| `health`                | All enabled checks   | All components allowed by `health_check_level` |
| `services`              | Service checks       | Apache, MySQL status and ports                 |
| `database`              | Database checks      | Database existence, tables, users              |
| `api`                   | API checks           | Status, authentication, endpoints              |
| `virtualisation`, `kvm` | Virtualisation checks| KVM module, device, CPU support                |
| `images`                | Image inventory      | QEMU, IOL, Dynamips counts                     |
| `labs`                  | Lab checks           | Lab files, running nodes, temporary usage      |
| `report`                | Report generation    | Formatting and output of the health report     |

### Usage Examples

```bash
# Services only
ansible-playbook healthcheck.yml --tags services

# Services and database
ansible-playbook healthcheck.yml --tags services,database

# Virtualisation and images
ansible-playbook healthcheck.yml --tags virtualization,images

# Skip API checks
ansible-playbook healthcheck.yml --skip-tags api

# Full check with detailed report
ansible-playbook healthcheck.yml   -e health_check_level=full   -e health_check_report_format=detailed

# Images only
ansible-playbook healthcheck.yml --tags images -e health_check_level=images
```

### Advanced Tag Combinations

```bash
# Services and database only (fast critical checks)
ansible-playbook healthcheck.yml --tags services,database

# All components except lab checks
ansible-playbook healthcheck.yml --skip-tags labs

# API and images only
ansible-playbook healthcheck.yml --tags api,images -e health_check_level=images
```

## Health Check Results

### Summary Format

```text
=== EVE-NG Health Check Summary ===
Overall Status: HEALTHY

Services:        PASS  Apache2 running, MySQL running
Database:        PASS  eve_ng database accessible, 15 tables, admin user exists
API:             PASS  Authentication successful
Virtualisation:  PASS  KVM module loaded, /dev/kvm accessible
Images:          INFO  42 QEMU images, 15 IOL images found
Labs:            PASS  23 lab files, 5 running nodes

Timestamp: 2026-01-13 15:30:45 UTC
```

### Detailed Format

```text
=== EVE-NG Health Check Report ===
Timestamp: 2026-01-13 15:30:45 UTC
Host: eveng-prod-01 (10.10.0.141)

--- Services ---
Apache2:        Active (running)
MySQL:          Active (running)
Port 80:        Listening
Port 443:       Listening
Port 3306:      Listening

--- Database ---
Database:       eve_ng exists
Tables:         15 tables found
Users:          admin user exists
Connectivity:   Successful

--- API ---
Status endpoint:    Accessible
Authentication:     Successful (admin)
Cookie generation:  Valid

--- Virtualisation ---
KVM module:     Loaded (kvm_intel)
/dev/kvm:       Exists and accessible
CPU support:    Intel VT-x detected
QEMU directory: /opt/unetlab/qemu/ exists

--- Images ---
QEMU images:    42
  Cisco vIOS:   8
  Arista vEOS:  5
  Juniper vMX:  3
IOL images:     15
Dynamips:       0

--- Labs ---
Lab files:      23 .unl files
Running nodes:  5 active VMs
Temp usage:     2.3 GB
Zombie check:   No zombie processes

=== Overall Status: HEALTHY ===
```

### JSON Format

```json
{
  "timestamp": "2026-01-13T15:30:45Z",
  "host": "eveng-prod-01",
  "overall_status": "healthy",
  "services": {
    "status": "pass",
    "apache2": "active",
    "mysql": "active",
    "ports": {
      "80": "listening",
      "443": "listening",
      "3306": "listening"
    }
  },
  "database": {
    "status": "pass",
    "database_exists": true,
    "table_count": 15,
    "admin_user_exists": true
  },
  "api": {
    "status": "pass",
    "authentication": "success",
    "cookie_valid": true
  },
  "virtualisation": {
    "status": "pass",
    "kvm_module": "loaded",
    "kvm_device": "exists",
    "cpu_support": "intel_vtx"
  },
  "images": {
    "status": "info",
    "qemu_count": 42,
    "iol_count": 15,
    "dynamips_count": 0
  },
  "labs": {
    "status": "pass",
    "lab_files": 23,
    "running_nodes": 5,
    "temp_usage_gb": 2.3,
    "zombie_processes": 0
  }
}
```

## Troubleshooting

### Service Check Fails

Symptom: Apache or MySQL reported as inactive.

```bash
# Check service status
sudo systemctl status apache2
sudo systemctl status mysql

# Restart services
sudo systemctl restart apache2
sudo systemctl restart mysql

# Re-run health check
ansible-playbook healthcheck.yml --tags services
```

### API Authentication Fails

Symptom: API check reports authentication failure.

```bash
# Verify admin password
export EVENG_ADMIN_PASSWORD="actual_password"

# Test manually
curl -k -X POST https://localhost/api/auth/login   -d '{"username":"admin","password":"eve"}'   -H "Content-Type: application/json"

# Re-run with updated password
ansible-playbook healthcheck.yml --tags api   -e eveng_admin_password=actual_password
```

### KVM Not Available

Symptom: virtualisation check reports KVM module not loaded.

```bash
# Check if loaded
lsmod | grep kvm

# Load module
sudo modprobe kvm_intel  # or kvm_amd

# Check CPU support
egrep -c '(vmx|svm)' /proc/cpuinfo

# Re-run check
ansible-playbook healthcheck.yml --tags virtualization
```

### Images Check Duration

Symptom: image inventory takes a long time on large deployments.

```bash
# Skip image checks for faster validation
ansible-playbook healthcheck.yml --skip-tags images

# Or use the basic level
ansible-playbook healthcheck.yml -e health_check_level=basic
```

## Integration Examples

### Post-Installation Verification

```yaml
---
- name: Install and verify EVE-NG
  hosts: eveng
  become: yes

  roles:
    - name: Install EVE-NG
      role: hybridops.app.eveng
      vars:
        eveng_resource_profile: performance

    - name: Verify installation
      role: hybridops.helper.eveng_healthcheck
      vars:
        health_check_level: full
        health_check_fail_on_warning: true
```

### Scheduled Monitoring

```yaml
---
- name: Daily EVE-NG health audit
  hosts: eveng
  become: yes

  vars:
    health_check_level: full
    health_check_report_format: json

  roles:
    - hybridops.helper.eveng_healthcheck

  post_tasks:
    - name: Archive health report
      copy:
        content: "{{ health_check_results | to_nice_json }}"
        dest: "/var/log/eveng/health_{{ ansible_date_time.date }}.json"

    - name: Alert on failures
      mail:
        to: ops@company.com
        subject: "EVE-NG health check failed - {{ inventory_hostname }}"
        body: "{{ health_check_results | to_nice_yaml }}"
      when: health_check_results.overall_status != 'healthy'
```

### CI/CD Pipeline

```yaml
---
- name: Verify EVE-NG deployment
  hosts: eveng_staging
  become: yes

  vars:
    health_check_level: images
    health_check_fail_on_warning: true

  roles:
    - hybridops.helper.eveng_healthcheck
```

## Best Practices

- `basic` is suitable for frequent checks in CI/CD and monitoring flows.
- `images` is suitable immediately after image deployment or catalogue changes.
- `full` is suitable for scheduled audits and pre-change validation in production.
- In production, set `health_check_fail_on_warning: true` where failure on warning is required.
- For monitoring integration, set `health_check_report_format: json` and persist or forward the generated reports.

## Documentation

Further context is provided in the broader HybridOps.Tech documentation set, including platform runbooks, lifecycle guidance, and licensing information.

## License

MIT.

See the [HybridOps.Tech licensing overview](https://docs.hybridops.tech/briefings/legal/licensing/)
for project-wide licence details, including branding and trademark notes.

## Author

HybridOps Team.
