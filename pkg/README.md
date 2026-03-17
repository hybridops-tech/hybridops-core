# HybridOps.Core Release Bundle Tooling

This directory defines the public release-bundle path for `hybridops-core`.

## Purpose

The bundle is the product boundary for HybridOps.Core. It is broader than the
Python wheel because operators need the runtime payload as shipped:

- `hyops/`
- `modules/`
- `packs/`
- `blueprints/`
- `tools/`
- `install.sh`

## Commands

Build a bundle from the current source tree:

```bash
bash pkg/build_release.sh
```

Optionally set an explicit label:

```bash
HYOPS_RELEASE_LABEL=0.1.0 bash pkg/build_release.sh
```

Verify a bundle through an isolated install:

```bash
bash pkg/verify_release.sh dist/releases/hybridops-core-<label>.tar.gz
```

If the local filesystem is tight, point the verifier at a larger temporary
filesystem:

```bash
TMPDIR=/dev/shm bash pkg/verify_release.sh dist/releases/hybridops-core-<label>.tar.gz
```

## Verification contract

`pkg/verify_release.sh` validates:

- the bundle extracts cleanly
- the shipped checksum manifest matches the extracted payload
- `install.sh` can install the bundle into an isolated runtime root
- installed `hyops` runs without relying on the source checkout
- the installed payload matches the shipped checksum manifest
- the temporary filesystem has enough free space before extraction begins

This is the authoritative release gate for HybridOps.Core. It keeps source,
bundle, and installed runtime aligned before a public release is cut.

`build_release.sh` also warns when the temporary filesystem looks tight for the
current source payload, with a `TMPDIR` hint instead of failing late and
silently.

GitHub Actions also runs the reusable quality workflow before bundle build and
publication. The blocking checks are Python compile/import integrity, Ansible
playbook syntax, and Terraform `fmt`/`validate`/`tflint`. Repo-wide
`ansible-lint` runs in advisory mode until the remaining legacy role debt is
removed.
