# Runtime internals

Runtime root is operator state (not repo state). Commands MUST NOT infer repo roots.

## Root precedence

1. `--root`
2. `HYOPS_RUNTIME_ROOT`
3. `~/.hybridops`

## Layout (minimum)

- `config/`
- `credentials/`
- `vault/`
- `meta/`
- `logs/`
- `state/`

## Evidence paths

- Init: `<root>/logs/init/<target>/<run_id>/`
- Module: `<root>/logs/module/<module_id>/<run_id>/`
- Driver: `<root>/logs/driver/<driver_id>/<run_id>/`

## Readiness

- `<root>/meta/<target>.ready.json`

## Stamp (best effort)

- `<root>/meta/runtime.json`
