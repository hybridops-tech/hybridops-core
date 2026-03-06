# docker_compose_stack

Manage a Docker Compose stack behind a systemd unit.

This role is intended as the common lifecycle layer for HybridOps services that:

- render their own `docker-compose.yml`
- optionally render an env file
- want systemd-managed `docker compose up -d`

Typical callers still own:

- stack-specific directories
- stack-specific templates
- stack-specific readiness checks
- stack-specific handlers
