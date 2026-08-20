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
`hyops setup galaxy`.

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

## Candidate builds

CI produces installable candidate artifacts for pull requests and manually
selected refs. Candidate artifacts are temporary test outputs, not published
HybridOps.Core releases.

For a pull request, the quality checks and downloadable candidate are both tied
to the prospective merge with `main`. This means the package represents the
exact tree that CI accepted for that pull request.

For branch-specific testing without a release, run the `HybridOps.Core CI`
workflow manually from GitHub Actions and select the branch or ref. A manual
candidate is built from the exact selected commit.

Candidate labels identify the tested source, for example:

```text
pr304-05216dd9e76a
candidate-3eb4f37e1c12
```

The full source commit and build context are retained in the bundle metadata and
in the uploaded build provenance file. Candidate artifacts are retained for 30
days and include checksums.

The Linux/general release archive is verified through `pkg/verify_release.sh`,
which installs the built archive into an isolated prefix and runs the installed
`hyops` without relying on the source checkout. macOS candidates are built for
Intel and Apple silicon, checksum-verified, installed with the native installer,
smoke-tested and removed before upload.

A version tag is still required for permanent GitHub Release assets. Candidate
artifacts are never promoted to GitHub Releases automatically.

Local `dist/` output remains disposable and is intentionally not committed.
Git records source; CI records build artifacts; tagged releases publish the
permanent distribution assets.

## Commands

Build a bundle from the current source tree:

```bash
./pkg/build_release.sh
```

Optionally set an explicit label:

```bash
HYOPS_RELEASE_LABEL=0.1.0 ./pkg/build_release.sh
```

On macOS, build a native installer from the release archive:

```bash
./pkg/build_macos_pkg.sh \
  --archive dist/releases/hybridops-core-0.1.0.tar.gz \
  --version 0.1.0
```

The resulting package is unsigned unless `--sign "Developer ID Installer: ..."`
is supplied. Local unsigned packages are intended for acceptance testing;
public distribution requires the normal Apple signing and notarisation process.

The package installs Core for the signed-in macOS user and places `hyops` in
`/usr/local/bin`. Package installation output is retained at
`/Library/Logs/HybridOps/core-install.log`. The package supports Intel and
Apple silicon Macs running macOS 13 or newer. Python 3.11 or newer must be
installed before the package is opened. To remove the installed software
while retaining runtime environments, logs and vault data:

```bash
sudo /usr/local/share/hybridops-core/uninstall-macos.sh
```

Pass `--purge-runtime` only when the retained runtime data should also be
removed.

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
- the installed runtime resolves its shipped packs without wrapper environment variables
- the bundle and installed payload do not include vendored HybridOps collection source
- installed `hyops` exposes `setup galaxy` and the compatible `setup ansible` path
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
