# Driver plugin model (notes)

Goal: allow third-party drivers without editing HybridOps.Core.

## Recommended approach

- Built-in drivers: packaged in `hyops/drivers/...`
- External drivers: installed as Python packages that expose entrypoints.

Entry point group:

- `hyops.drivers`

Entry point value:

- A callable that returns a `DriverFunc` or a module path exposing `run(request) -> result`.

## Resolution

- Core resolves `execution.driver` (string ref) to a registered `DriverFunc`.
- Registration can occur from:
  - built-ins (import-time bootstrap)
  - entrypoint discovery at runtime (optional lazy load)

## Constraints

- Driver refs must be stable strings.
- Driver results must always include `normalized_outputs`.
- Evidence must never include secrets.
