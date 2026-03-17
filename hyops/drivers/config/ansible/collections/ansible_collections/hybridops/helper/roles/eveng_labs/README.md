# eveng_labs

**Purpose:** Deploy and maintain EVE-NG lab files under `/opt/unetlab/labs` from controller, Git, or remote sources.  
**Design reference:** ADR-XXXX (EVE-NG lab content management)  
---

## 1. Overview

The role:

- Synchronises EVE-NG lab content into `/opt/unetlab/labs`.
- Supports three source modes: `local`, `git`, and `remote`.
- Applies a shared rsync exclude set to keep lab trees clean.
- Normalises ownership and permissions after each run.

Typical usage includes rebuilding lab libraries on EVE-NG hosts for lab, CI, or training environments.

---

## 2. Source modes

The source mode is selected with:

```yaml
eveng_labs_source: local   # local | git | remote
```

### 2.1 Local source (`eveng_labs_source: local`)

Lab content is pulled from the Ansible controller filesystem, staged on the EVE host, then installed into the final lab tree.

```yaml
eveng_labs_source: local

# Single file or directory on the controller
eveng_labs_local_path: "{{ playbook_dir }}/files/labs"
```

Behaviour:

- When `eveng_labs_local_path` is a file (for example, a ZIP), it is unarchived into a staging directory on the EVE host and then rsynced into `/opt/unetlab/labs` or a specific folder when `eveng_lab_folders` is set.
- When it is a directory, `synchronize` (rsync) stages content on the EVE host before installation into `/opt/unetlab/labs`.
- Only relevant lab files are included; patterns are controlled by `eveng_labs_sync_exclude_patterns`.

### 2.2 Git source (`eveng_labs_source: git`)

Lab content is cloned from a Git repository on the EVE host and then staged and synced into `/opt/unetlab/labs`.

```yaml
eveng_labs_source: git

eveng_labs_git_repo: "git@github.com:example/eveng-labs.git"
# Optional branch, tag, or commit
eveng_labs_git_branch: "main"
```

Behaviour:

- Installs `git` if required.
- Clones `eveng_labs_git_repo` into a staging directory on the EVE host.
- Uses `synchronize` to push from the staging directory into `/opt/unetlab/labs` (or specific folders under it when `eveng_lab_folders` is set) with the shared exclude list and explicit chmod.
- Keeps the staging directory under the same lifecycle as the role; subsequent runs can clean and repopulate it.

### 2.3 Remote source (`eveng_labs_source: remote`)

Lab content is pulled from a remote host that is reachable over SSH/rsync, then staged and installed.

```yaml
eveng_labs_source: remote

eveng_labs_remote_host: filesrv-01
eveng_labs_remote_path: /data/eveng/labs
```

Behaviour:

- Uses `synchronize` from `eveng_labs_remote_path` into the staging directory on the EVE host.
- Installs staged content into `/opt/unetlab/labs` using the same logic as other sources.
- Applies the same exclude patterns and chmod as other sources.

---

## 3. Exclude patterns

The role centralises rsync excludes so that all source modes behave consistently.

Defaults:

```yaml
eveng_labs_sync_exclude_patterns:
  - "--exclude=.git"
  - "--exclude=*.md"
  - "--exclude=README*"
  - "--exclude=*.bak"
  - "--exclude=*~"
  - "--exclude=.DS_Store"
```

These patterns are combined into the `rsync_opts` list in each `synchronize` task, together with `--chmod=D775,F664`. They can be overridden in inventory or playbooks when needed.

---

## 4. Permissions

After synchronisation and installation, the role:

- Normalises ownership to `www-data:www-data`.
- Sets directory and file modes suitable for EVE-NG lab trees.

This keeps lab content consistent regardless of the source type.

---

## 5. Usage examples

### 5.1 Deploy labs from controller filesystem

```yaml
- name: Deploy EVE-NG labs from controller
  hosts: eve
  become: true

  vars:
    eveng_labs_source: local
    eveng_labs_local_path: "{{ playbook_dir }}/files/labs"

  roles:
    - hybridops.helper.eveng_labs
```

### 5.2 Deploy labs from Git

```yaml
- name: Deploy EVE-NG labs from Git repository
  hosts: eve
  become: true

  vars:
    eveng_labs_source: git
    eveng_labs_git_repo: "git@github.com:example/eveng-labs.git"
    eveng_labs_git_branch: "main"

  roles:
    - hybridops.helper.eveng_labs
```

### 5.3 Deploy labs from remote file server

```yaml
- name: Deploy EVE-NG labs from remote file server
  hosts: eve
  become: true

  vars:
    eveng_labs_source: remote
    eveng_labs_remote_host: filesrv-01
    eveng_labs_remote_path: /data/eveng/labs

  roles:
    - hybridops.helper.eveng_labs
```

---

## 6. CI and smoke testing

A compact smoke test can be used in CI pipelines to validate that lab content is synchronised correctly.

```yaml
# file: tests/eveng_labs.smoke.yml

- name: Smoke test EVE-NG lab deployment
  hosts: cicd_test
  become: true

  vars:
    eveng_labs_source: local
    eveng_labs_local_path: "{{ playbook_dir }}/tests/fixtures/labs"

  roles:
    - hybridops.helper.eveng_labs
```

Typical CI runs archive:

- The resulting lab tree under `/opt/unetlab/labs/` (or a subset).
- Ansible logs for the run.

This role stays focused on synchronisation and permissions; higher-level test logic (for example, EVE-NG API checks) can be layered on top in platform playbooks or pipelines.

---

## License

See the [HybridOps.Tech licensing overview](https://docs.hybridops.tech/briefings/legal/licensing/)
for project-wide licence details, including branding and trademark notes.
