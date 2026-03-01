# Changelog — postgresql_service

All notable changes to the `postgresql_service` role will be documented in this file.

The format is based on *Keep a Changelog*, and this role follows *Semantic Versioning*.

## [Unreleased]

### Added
- Optional evidence capture (`systemctl-status.txt`, `pg_isready.txt`, `timestamp.txt`) gated by `hybridops_evidence_enabled`.
- Declarative allowlist input `hybridops_postgres_allowed_clients` to generate TCP host rules in `pg_hba.conf`.

### Changed
- Default posture is secure-by-default: localhost-only listen unless additional addresses are configured.
- Privilege entries follow upstream schema; use `db` for database selection (not `database`).
- Sensitive output suppression is enabled by default via `hybridops_postgres_users_no_log` (debug override supported).

### Fixed
- Guardrails and smoke-test behaviour tightened to avoid accidental remote exposure without an allowlist.
- Evidence capture and service checks hardened against unit-name variance across distros.

## [0.1.0] - 2026-01-10

### Added
- Initial release of `postgresql_service` wrapper role around `geerlingguy.postgresql`.
- Stable variable schema prefixed with `hybridops_postgres_*` for:
  - Core settings (`port`, `listen_addresses`, `log_directory`)
  - HBA defaults and allowlisting
  - Database/user/privilege management (pass-through to upstream role)
  - Service control (`started`, `enabled`)
- Input validation tasks with guardrails for remote listen configuration.
- Minimal smoke test playbook for CI verification.
