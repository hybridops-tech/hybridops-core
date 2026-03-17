# NetBox Inventory Driver (Core)

This package hosts NetBox export/import tooling for HybridOps.Core with runtime paths resolved from the installed environment.

## Package layout

```text
hyops/drivers/inventory/netbox
├── README.md
├── profiles/
├── schema/
├── templates/
└── tools/
    ├── contract.py
    ├── csv_io.py
    ├── export_infra.py
    ├── import_devices_to_netbox.py
    ├── import_infra_to_netbox.py
    ├── import_prefixes_to_netbox.py
    ├── netbox_api.py
    ├── paths.py
    └── terraform_export.py
```

## Runtime path model

All defaults resolve from:

1. `HYOPS_NETBOX_ROOT` (if set)
2. `HYOPS_RUNTIME_ROOT` (if set)
3. current working directory

Default outputs:

- `state/netbox/vms/vms.auto.csv`
- `state/netbox/vms/vms.auto.json`
- `state/netbox/network/ipam-prefixes.csv`
- `state/netbox/network/ipam-prefixes.json`

Override via env vars in `tools/paths.py`.

## Commands

Run as modules:

```bash
python3 -m hyops.drivers.inventory.netbox.tools.export_infra --list-targets
python3 -m hyops.drivers.inventory.netbox.tools.export_infra --target cloud-azure --terragrunt-root /path/to/live
python3 -m hyops.drivers.inventory.netbox.tools.import_infra_to_netbox --validate-only
python3 -m hyops.drivers.inventory.netbox.tools.import_devices_to_netbox --validate-only
python3 -m hyops.drivers.inventory.netbox.tools.import_prefixes_to_netbox --target cloud --validate-only
```

NetBox API env:

- `NETBOX_API_URL`
- `NETBOX_API_TOKEN`

Optional fallback file:

- `CONTROL_SECRETS_ENV` (default `credentials/netbox.env` under runtime root)

## Terragrunt hook integration

Recommended profile hook command template:

```yaml
hooks:
  export_infra:
    command:
      - python3
      - -m
      - hyops.drivers.inventory.netbox.tools.export_infra
      - --target
      - "{target}"
      - --terragrunt-root
      - "{hook_root}"
      - --only-module
      - .
      - --changed-only
    hook_root_env: HYOPS_EXPORT_HOOK_ROOT
    hook_root_default: "."
    strict: false
    redact: true
```

With this profile setting, modules can opt in via `spec.execution.hooks.export_infra.enabled: true`.
