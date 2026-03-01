# apply command (notes)

## Flow

1. Resolve runtime root and ensure layout.
2. Resolve module spec and merge inputs.
3. Create run_id.
4. Create evidence dir:
   - `<root>/logs/module/<module_id>/<run_id>/`
5. Best-effort stamp to `<root>/meta/runtime.json`.
6. Resolve driver ref to a `DriverFunc`.
7. Build DriverRequest and invoke driver.
8. Persist:
   - `meta.json`
   - `result.json`
   - any driver artifacts

## Evidence minimum

- run metadata
- resolved non-secret paths
- subprocess results (argv redacted, rc, duration)

## Errors

- Operator errors: return non-zero exit code.
- Driver errors: persist evidence first, then return non-zero.
