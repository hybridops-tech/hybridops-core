# Modules internals

A module is declarative intent. It does not contain tool execution logic.

## Supported today

- `spec.yml` with `inputs.defaults` and `execution.{driver,profile,pack_ref.id}`
- Optional operator inputs YAML overrides defaults

## Not implemented yet

- Constraints engine
- Probes runner
- `outputs.publish` mapping
- Apply readiness markers

## Resolution behavior

- Start from `inputs.defaults`.
- Overlay operator inputs file.
- Validate `execution.driver`, `execution.profile`, `execution.pack_ref.id` are present.
- When `inputs.addressing.mode` is set, enforce `static|ipam` contract.
- For `inputs.addressing.mode=ipam`, enforce `ipam.provider=netbox` and NetBox preflight before driver.
