# decision_service

Deploys a deterministic edge decision loop runtime as a systemd service.

Role scope (v1):

- Writes policy and runtime config.
- Installs a local decision loop service.
- Persists decision state, decision records, and logs for health and troubleshooting.

Default behavior is `emit-only`: the service writes structured decision records and
does not execute HyOps actions directly.

An explicit transitional mode, `local-hyops`, can still execute `hyops apply`
locally when enabled by the caller.

When `decision_service_runtime_root` is set, the role also seeds the minimal
runtime directories needed for host-local module actions and can inject selected
controller environment variables into the service environment file.
