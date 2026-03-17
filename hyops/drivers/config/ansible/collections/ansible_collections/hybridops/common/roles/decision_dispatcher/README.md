# decision_dispatcher

Deploys a deterministic dispatcher runtime as a systemd service.

Role scope (v1):

- Watches the decision-service records directory.
- Writes normalized dispatch requests under its own state directory.
- Does not execute HyOps directly.

Default behavior is `record-only`.
