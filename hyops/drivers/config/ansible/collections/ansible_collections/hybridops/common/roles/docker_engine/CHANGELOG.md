# Changelog

All notable changes to the `docker_engine` role are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this role follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-01-04

### Added

- Initial release of `hybridops.common.docker_engine` aligned with ADR-0602
  (Docker Engine baseline).
- Docker CE baseline for Ubuntu 22.04 (jammy) using the official Docker APT
  repository and packages.
- Docker CE baseline for Rocky Linux 9 / RHEL 9 using the official Docker YUM
  repository and packages.
- Installation of Docker Engine, CLI, `containerd.io`, and Docker Compose v2
  plugin on supported platforms.
- Service management for the `docker` daemon, including optional enablement on
  boot via `docker_engine_enable`.
- User management for the `docker` group via `docker_engine_users`, enabling
  non-root Docker usage.
- Fast-fail behavior on unsupported OS families with a clear error message.
- Optional evidence hook that runs `docker version` and emits a debug message
  without failing the play if the command is unavailable.
- Role README describing supported platforms, variables, and usage patterns
  across the HybridOps.Tech platform.
