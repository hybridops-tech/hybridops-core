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
hyops setup ansible --hybridops-source git
hyops setup ansible --root /path/to/hybridops-core --hybridops-source git
hyops setup all --sudo
```

## Notes

- System installers require sudo.
- `hyops setup cloud-gcp --sudo` installs both `gcloud` and `gke-gcloud-auth-plugin`; it also repairs older machines where `gcloud` is already present but the GKE auth plugin is missing.
- Ansible Galaxy dependencies are installed into the selected runtime root:
  - `<runtime_root>/state/ansible/galaxy_collections`
  - `<runtime_root>/state/ansible/roles`
  - `<runtime_root>/state/ansible/modules/<module_id>/galaxy_collections` (module-scoped sets)
- The public install contract uses the pinned released `hybridops.common`,
  `hybridops.helper`, and `hybridops.app` collections from
  [tools/setup/requirements/ansible.galaxy.yml](./requirements/ansible.galaxy.yml).
- Git-based install path (for iteration or a pinned Git-based flow):
  - `hyops setup ansible --hybridops-source git`
  - `hyops setup ansible --hybridops-source git --hybridops-git-manifest /path/to/manifest.json`
  - builds and installs pinned `hybridops.common`, `hybridops.helper`, and `hybridops.app` from Git into runtime state
  - the primary public install contract remains the released collection set
- For local source-tree iteration, point `hyops setup` at the checkout you want to use:
  - `hyops setup ansible --root /path/to/hybridops-core --hybridops-source git`
- Drivers and modules do not install dependencies automatically; they fail fast and instruct which `hyops setup` command to run.

## Documentation

- [Global prerequisites guide](https://docs.hybridops.tech/guides/getting-started/00-quickstart/)
