# tools/setup

**Purpose:** Install system prerequisites for HybridOps.

Use `hyops setup ...` to install required tools for init targets and drivers.

## Commands

```bash
hyops setup check
hyops setup base --sudo
hyops setup cloud-azure --sudo
hyops setup cloud-gcp --sudo
hyops setup ansible
hyops setup all --sudo
```

## Notes

- System installers require sudo.
- `hyops setup cloud-gcp --sudo` installs both `gcloud` and `gke-gcloud-auth-plugin`; it also repairs older machines where `gcloud` is already present but the GKE auth plugin is missing.
- Ansible Galaxy dependencies are installed into the selected runtime root:
  - `<runtime_root>/state/ansible/galaxy_collections`
  - `<runtime_root>/state/ansible/roles`
  - `<runtime_root>/state/ansible/modules/<module_id>/galaxy_collections` (module-scoped sets)
- The default shared dependency set explicitly pins the released `hybridops.common`,
  `hybridops.helper`, and `hybridops.app` collections in
  [tools/setup/requirements/ansible.galaxy.yml](./requirements/ansible.galaxy.yml).
- The default shared dependency set now installs released `hybridops.common`, `hybridops.helper`, and `hybridops.app` from Ansible Galaxy.
- Temporary internal fallback path:
  - `hyops setup ansible --hybridops-source git`
  - this builds/install pinned `hybridops.common`, `hybridops.helper`, and `hybridops.app` from Git into runtime state
  - this path is for internal validation or emergency fallback and is not the primary public install contract
- Drivers and modules do not install dependencies automatically; they fail fast and instruct which `hyops setup` command to run.

## Documentation

- [Global prerequisites guide](https://docs.hybridops.tech/guides/getting-started/00-quickstart/)
