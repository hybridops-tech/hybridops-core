# Drivers internals

A driver is the execution engine selected by a module:
`execution.driver` + `execution.profile` + `execution.pack_ref.id`.

## Driver contract (minimum)

Driver input: request mapping (DriverRequest).

Driver output: mapping with at minimum:

- `status`
- `run_id`
- `normalized_outputs` (mapping)

Drivers may also register controller-readiness and live-state inspection
capabilities. Runtime planning consumes these capabilities through the registry.

## Location

Drivers live under: `hyops/drivers/<domain>/<driver>/...`

## Registration

- Built-ins are registered by `hyops.drivers.builtin.register`.
- Optional plugins are discovered via Python entrypoints group `hyops.drivers`.
