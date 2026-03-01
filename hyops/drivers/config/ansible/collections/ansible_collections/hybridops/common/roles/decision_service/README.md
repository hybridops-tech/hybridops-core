# decision_service

Deploys a deterministic edge decision loop runtime as a systemd service.

Role scope (v1):

- Writes policy and runtime config.
- Installs a local decision loop service.
- Persists decision state/log files for health and troubleshooting.

This role is observe-first in v1 and does not execute cutover actions directly.
