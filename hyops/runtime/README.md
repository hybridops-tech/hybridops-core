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

## Retention and cleanup

The runtime root belongs to the operator. HybridOps does not delete run records
on a fixed schedule, because retention needs differ between local evaluation,
debugging, audit, and operational handoff.

Files under `<root>/logs/` are run evidence and may be reviewed for removal when
they are no longer needed. The other runtime directories are not routine cleanup
targets:

- `config/`, `credentials/`, and `vault/` may contain environment configuration
  or secret material.
- `meta/` may contain readiness and runtime metadata.
- `state/` may contain active environment state.

For the default runtime root, list log files older than seven days with:

```bash
find ~/.hybridops/logs -type f -mtime +7 -print
```

This is a review command, not a retention policy or deletion command. Check the
output before removing files, preserve evidence required for audit or debugging,
and never commit runtime logs or sensitive runtime state to the repository.

## Readiness

- `<root>/meta/<target>.ready.json`

## Stamp (best effort)

- `<root>/meta/runtime.json`
