# HybridOps.Core Release Bundle

This directory defines the public release bundle for `hybridops-core`.

## Purpose

The bundle is the product boundary for HybridOps.Core. It is broader than the
Python wheel because operators need the runtime payload as shipped:

- `hyops/`
- `modules/`
- `packs/`
- `blueprints/`
- `tools/`
- `install.sh`

HybridOps Ansible collection source is not part of the public bundle contract.
Operators install the pinned released `hybridops.*` collection artifacts through
`hyops setup ansible`.

## Public Product Boundary

Keep the shipped bundle focused on reusable platform capabilities.

What belongs in the public bundle:
- reusable modules
- reusable packs
- neutral blueprints
- generic validation and execution logic

What does not belong in the public bundle:
- application recovery chains tied to one private operator lane
- customer or HybridOps specific target names
- blueprints that only make sense for one private operator lane

Application composition should stay in the selected workloads repository and
target path. Public Core should consume that through generic inputs such as:
- `workloads_repo_url`
- `workloads_revision`
- `workloads_target_path`

## Commands

Build a bundle from the current source tree:

```bash
./pkg/build_release.sh
```

Optionally set an explicit label:

```bash
HYOPS_RELEASE_LABEL=0.1.0 ./pkg/build_release.sh
```

Verify a bundle through an isolated install:

```bash
./pkg/verify_release.sh dist/releases/hybridops-core-<label>.tar.gz
```

If the local filesystem is tight, point the verifier at a larger temporary
filesystem:

```bash
TMPDIR=/dev/shm ./pkg/verify_release.sh dist/releases/hybridops-core-<label>.tar.gz
```

## Verification contract

`pkg/verify_release.sh` validates:

- the bundle extracts cleanly
- the shipped checksum manifest matches the extracted payload
- `install.sh` can install the bundle into an isolated runtime root
- installed `hyops` runs without relying on the source checkout
- the bundle and installed payload do not include vendored HybridOps collection source
- installed `hyops` still exposes the `setup ansible` operator path
- the installed payload matches the shipped checksum manifest
- the temporary filesystem has enough free space before extraction begins

This is the authoritative release gate for HybridOps.Core. It keeps source,
bundle, and installed runtime aligned before a public release.

`build_release.sh` also warns when the temporary filesystem looks tight for the
current source payload, with a `TMPDIR` hint instead of failing late and
silently.

GitHub Actions also runs the reusable quality workflow before bundle build and
publication. The blocking checks are Python compile/import integrity, Ansible
playbook syntax and pack-surface lint, and Terraform `fmt`/`validate`/`tflint`.
