# tools/setup

**Purpose:** Install system prerequisites for HybridOps.Core.

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
- Ansible Galaxy dependencies are installed into the selected runtime root:
  - `<runtime_root>/state/ansible/galaxy_collections`
  - `<runtime_root>/state/ansible/roles`
  - `<runtime_root>/state/ansible/modules/<module_id>/galaxy_collections` (module-scoped sets)
- The default shared dependency set explicitly pins the released `hybridops.common`,
  `hybridops.helper`, and `hybridops.app` collections in
  [tools/setup/requirements/ansible.galaxy.yml](./requirements/ansible.galaxy.yml).
- Drivers and modules do not install dependencies automatically; they fail fast and instruct which `hyops setup` command to run.

## Documentation

- [Global prerequisites guide](https://docs.hybridops.studio/guides/getting-started/00-quickstart/)
