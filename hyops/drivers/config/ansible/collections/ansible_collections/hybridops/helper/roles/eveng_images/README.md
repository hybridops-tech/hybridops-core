# eveng_images

**Purpose:** Standardized deployment and maintenance of EVE-NG image files (archives and raw images) for lab environments.  
**Design reference:** ADR-XXXX (EVE-NG image management and verification model)  
---

## 1. Overview

The role:

- Acquires images from one of three sources:
  - `url` – HTTP/HTTPS or MEGA URLs
  - `local` – filesystem on the Ansible controller
  - `remote` – remote file server accessed over SSH/rsync
- Caches content on the EVE-NG host.
- Installs images into `/opt/unetlab/addons/*` with predictable layouts.
- Emits logs and reports suitable for review, CI, and troubleshooting.

Typical usage includes ad-hoc lab builds, CI smoke tests, and governed platform runs where image state and provenance require documentation.

---

## 2. Sources

### 2.1 URL source (`eveng_images_source: url`)

```yaml
eveng_images_source: url

eveng_images_list:
  - url: "https://mega.nz/folder/30p3TKob#42_S__9wwPVO0zHIfC4xow/file/u1ByjDLC"
    name: android-9.1-x64.tar.gz
    type: qemu

  - url: "https://labhub.eu.org/api/raw/?path=/addons/qemu/Windows/winserver-S2019-R2-x64-rev3.tgz"
    name: winserver-S2019-R2-x64-rev3.tgz
    type: qemu
```

Entry fields:

- `url` – required.
- `type` – required; one of `qemu`, `iol`, `dynamips`.
- `name` – optional; used as the cache filename and for report mapping when present.

MEGA URLs (`mega.nz`) are handled via MEGAcmd (`mega-get`), installed on demand when first used.

### 2.2 Local source (`eveng_images_source: local`)

```yaml
eveng_images_source: local

# Single file
eveng_images_local_path: /srv/eveng/images/windows/winserver-S2019-R2-x64-rev3.tgz

# Or directory
# eveng_images_local_path: /srv/eveng/images/
```

Behaviour:

- When `eveng_images_local_path` is a file, it is copied into the cache directory.
- When `eveng_images_local_path` is a directory, only image files are rsynced:
  - `*.tar.gz`, `*.tgz`, `*.zip`, `*.gz`, `*.qcow2`, `*.img`, `*.bin`.

### 2.3 Remote source (`eveng_images_source: remote`)

```yaml
eveng_images_source: remote

eveng_images_remote_host: filesrv-01
eveng_images_remote_path: /data/eveng-images
```

Behaviour:

- Uses `synchronize` (rsync over SSH) from `eveng_images_remote_host`.
- Accepts either a directory (filtered by image patterns) or a single file path.

---

## 3. Cache and install behaviour

### 3.1 Cache directory

```yaml
eveng_images_cache_dir: /tmp/eveng_images_cache
eveng_images_keep_cache: false
```

All downloads and copies land in `eveng_images_cache_dir`. When `eveng_images_keep_cache: false`, the cache directory is removed after installation.

### 3.2 File types and detection

Supported inputs:

- Archives: `*.tar.gz`, `*.tgz`, `*.zip`, `*.gz`
- Raw QEMU disks: `*.qcow2`, `*.img`
- Raw IOL/Dynamips binaries: `*.bin`

Type detection:

1. When `eveng_images_list` is defined and `name` matches, `type` is taken from the list.
2. Otherwise, extension-based classification:
   - `qcow2`, `img` → `raw:qemu`
   - `bin` → `raw:iol`
3. For archives, `tar -tzf` is used to inspect the first directory entry:
   - Root directories `iol/`, `qemu/`, `dynamips/` → `structured:<type>`
   - Other cases → `qemu` (generic default).

### 3.3 Install layout

Target root is `/opt/unetlab/addons` following EVE-NG conventions.

```yaml
eveng_images_raw_qemu_layout: generic   # generic | foldered
eveng_images_raw_qemu_disk_name: virtioa.qcow2
```

Behaviour:

- **Structured archives** (for example `qemu/veos-4.23.2/…`):
  - Extracted directly into `/opt/unetlab/addons/`.
- **Generic archives**:
  - Extracted into `/opt/unetlab/addons/<type>/`.
- **Raw QEMU images**:
  - `generic`: copied into `/opt/unetlab/addons/qemu/<basename>`.
  - `foldered`:
    - Directory created at `/opt/unetlab/addons/qemu/<basename-without-ext>/`.
    - Disk copied to `<dir>/<eveng_images_raw_qemu_disk_name>` (default `virtioa.qcow2`).
- **Raw IOL/Dynamips**:
  - IOL: `/opt/unetlab/addons/iol/bin/<basename>`
  - Dynamips: `/opt/unetlab/addons/dynamips/<basename>`

After installation, `/opt/unetlab/addons/` is normalised to `root:root` ownership with `0755` permissions.

---

## 4. Corrupt or partial archives

Archives that cannot be listed with `tar -tzf` are marked as `invalid` and skipped by the installer.

Control is via:

```yaml
eveng_images_fail_on_corrupt: true
```

- `true` – invalid archives are reported and the role fails the play.
- `false` – invalid archives are reported and the play continues.

Corrupt archives are always included in the debug summary and in the report document for audit purposes.

---

## 5. Logging and reports

The role aligns with the HybridOps.Tech reporting layout:

- Logs under `var/log/hybridops/eveng-images/…`.
- Reports under `var/lib/hybridops/reports/eveng-images/…`.

Controller defaults:

```yaml
eveng_images_logging_enabled: true

eveng_images_log_dir_controller: "{{ playbook_dir | default('.', true) }}/var/log/hybridops/eveng-images"
eveng_images_download_log: "{{ eveng_images_log_dir_controller }}/downloads-{{ inventory_hostname }}.log"

eveng_images_generate_report: true
eveng_images_report_dir_controller: "{{ playbook_dir | default('.', true) }}/var/lib/hybridops/reports/eveng-images"
```

### 5.1 Download log

When logging is enabled, a per-host log file is written and appended to on each run:

- `var/log/hybridops/eveng-images/downloads-<host>.log`

Each line summarises a run, including:

- Timestamp.
- Target host.
- Cache directory.
- Number of images and number marked corrupt.
- Image names and corrupt filenames (if any).

### 5.2 Report documents

Structured YAML reports are written as:

- Per-run: `var/lib/hybridops/reports/eveng-images/report-<host>-<runid>.yml`
- Latest snapshot: `var/lib/hybridops/reports/eveng-images/report-<host>-latest.yml`

Example schema:

```yaml
run_at: 2026-01-16T13:45:12+00:00
host: eve-ng
cache_dir: /tmp/eveng_images_cache
files:
  - name: android-9.1-x64.tar.gz
    path: /tmp/eveng_images_cache/android-9.1-x64.tar.gz
    size_bytes: 1056899072
    type: qemu
    source_url: https://mega.nz/...
    status: ok
  - name: winserver-S2019-R2-x64-rev3.tgz
    path: /tmp/eveng_images_cache/winserver-S2019-R2-x64-rev3.tgz
    size_bytes: 6024011776
    type: qemu
    source_url: https://labhub.eu.org/...
    status: corrupt
```

Reports are suitable for verification records, change reviews, and troubleshooting for failed or partial runs.

---

## 6. Usage patterns

### 6.1 URL-based image load

```yaml
- name: Load core EVE-NG images from URLs
  hosts: cicd_test
  become: true

  vars:
    eveng_images_source: url
    eveng_images_cache_dir: /tmp/eveng_images_cache
    eveng_images_keep_cache: false

    eveng_images_list:
      - url: "https://mega.nz/folder/30p3TKob#42_S__9wwPVO0zHIfC4xow/file/K44jUbIY"
        name: linux-centos-9-stream.tar.gz
        type: qemu

      - url: "https://mega.nz/folder/30p3TKob#42_S__9wwPVO0zHIfC4xow/file/mtwx2IpZ"
        name: linux-kali-large-2019.3.tar.gz
        type: qemu

  roles:
    - hybridops.helper.eveng_images
```

### 6.2 Local file or directory

```yaml
- name: Load images from local cache
  hosts: cicd_test
  become: true

  vars:
    eveng_images_source: local
    eveng_images_local_path: "{{ playbook_dir }}/files/eveng-images"

  roles:
    - hybridops.helper.eveng_images
```

### 6.3 Remote file server

```yaml
- name: Load images from remote file server
  hosts: cicd_test
  become: true

  vars:
    eveng_images_source: remote
    eveng_images_remote_host: filesrv-01
    eveng_images_remote_path: /data/eveng-images/core

  roles:
    - hybridops.helper.eveng_images
```

---

## 7. CI and smoke testing

The role is exercised via a compact smoke test in CI rather than a Molecule scenario.

```yaml
# file: tests/eveng_images.smoke.yml

- name: Smoke test EVE-NG images deployment
  hosts: cicd_test
  become: true

  vars:
    eveng_images_source: url
    eveng_images_cache_dir: /tmp/eveng_images_cache
    eveng_images_keep_cache: false
    eveng_images_fail_on_corrupt: false

    eveng_images_list:
      - url: "https://labhub.eu.org/api/raw/?path=/addons/qemu/alpine-base-3-19-1/alpine-base-3-19-1.qcow2"
        name: alpine-base-3-19-1.qcow2
        type: qemu

  roles:
    - hybridops.helper.eveng_images
```

Typical CI integration retains or publishes:

- `var/log/hybridops/eveng-images/`
- `var/lib/hybridops/reports/eveng-images/`

as part of the run record.

---

## 8. Behaviour summary

- Idempotent with respect to repeated downloads and installs.
- Corrupt archives are always reported and optionally fail the play.
- Raw image handling is controlled by `eveng_images_raw_qemu_layout`:
  - `generic` for existing third-party layouts.
  - `foldered` for a consistent “one directory per image” layout.

---

## License

See the [HybridOps.Tech licensing overview](https://docs.hybridops.tech/briefings/legal/licensing/)
for project-wide licence details, including branding and trademark notes.
