# core/shared/vyos-image-build

Build one canonical VyOS disk artifact contract for HyOps state. The production path is artifact-first (prebuilt qcow2/raw URL), with local ISO/Packer builds kept as an explicit opt-in path.

Implementation note:

- This module executes through `driver: "config/ansible"` and calls wrapper scripts under `tools/build/vyos/*`.
- It does **not** use the generic `images/packer` driver directly.
- The packaged Packer scaffold still lives under `packs/images/packer/shared/...` and is consumed by the wrappers when ISO/Packer mode is enabled.

This is the clean bridge between:

- official VyOS ISO source material
- a local build toolchain such as `packer`, `qemu-img`, or a wrapper script
- a pinned published artifact URL

Typical usage:

```bash
hyops validate --env dev --skip-preflight \
  --module core/shared/vyos-image-build \
  --inputs "$HYOPS_CORE_ROOT/modules/core/shared/vyos-image-build/examples/inputs.min.yml"
```

State-first publish target example:

```bash
hyops validate --env dev --skip-preflight \
  --module core/shared/vyos-image-build \
  --inputs "$HYOPS_CORE_ROOT/modules/core/shared/vyos-image-build/examples/inputs.gcs-state.yml"
```

Inputs:

- `source_iso_url`: source artifact URL (qcow2/raw preferred; ISO is opt-in)
- `artifact_local_path`: local build output path, for example `/tmp/vyos-1.5.qcow2`
- `repo_state_ref`: optional object-repo state used by publish helpers to discover the target bucket/container
- `build_command`: local command that creates `artifact_local_path`
- `smoke_verify_command`: optional command that validates the built local artifact before publish (when omitted, the packaged default smoke helper is used)
- `smoke_verify_required`: whether smoke verification is a hard gate (default: `true`)
- `publish_command`: optional local command that uploads the built artifact
- `artifact_url`: final downloadable artifact URL; if omitted and `publish_command` is set, HyOps expects the command to print the URL on stdout
- `allow_iso_build`: optional boolean (default `false`); set `true` only when intentionally using ISO/Packer build flow

For GCS publishing without `gcloud`/`gsutil`:

- the packaged publish helper now supports direct upload to GCS with a service-account JSON
- provide one of:
  - `HYOPS_VYOS_GCS_SA_JSON`
  - `HYOPS_VYOS_GCS_SA_JSON_FILE`
- this keeps the builder path tarball-safe and avoids requiring Google CLI tools on the build runner

For ISO sources (opt-in):

- `build-vyos-qcow2.sh` will dispatch to `build-vyos-from-iso.sh`
- `build-vyos-from-iso.sh` now defaults to `HYOPS_VYOS_ISO_BUILD_METHOD=vyos-vm-images`
- use `HYOPS_VYOS_ISO_BUILD_METHOD=packer` only for explicit debug/fallback
- the official `vyos-vm-images` Ansible builder is the recommended ISO path because it produces a VyOS cloud-init-capable image (includes the VyOS cloud-init module)
- run the official builder on a standard Debian/Ubuntu host with passwordless sudo (the Proxmox host blocks the package install via `pve-apt-hook`)
- `build-vyos-from-iso-packer.sh` defaults to the packaged two-stage Packer scaffold if `HYOPS_VYOS_PACKER_TEMPLATE` is not set
- this keeps the product honest: the official installer ISO is valid source material, but it is not treated as directly seedable
- the packaged vars scaffold now does:
  - stage 1: console-driven `install image` from the live ISO
  - stage 2: recover the console login prompt, enable DHCP plus SSH/password auth on the installed disk, install and enable `cloud-init` plus `qemu-guest-agent` for Proxmox/NoCloud consumers, then boot over SSH and sanitize the template state
- validate and adjust the stage-1 install prompt timing/order for the exact pinned VyOS release you ship
- the packaged KVM wait profile is now tuned for a normal `/dev/kvm` builder, not a slow `tcg` fallback; if your pinned VyOS release still needs more time, adjust the vars scaffold rather than relying on gigantic default waits
- the packaged stage-1 template also supports `serial_device`; point it at a file while debugging installer behavior if the live console needs direct inspection
- the packaged stage-1 template also supports `monitor_device`; point it at a unix socket and use `screendump` over the QEMU monitor when you need to inspect the actual KVM/VNC console instead of guessing from the serial log
- the installed-disk stage now assumes a KVM-backed builder with moderate waits; if login or DHCP still races on your pinned build, tune `installed_boot_wait` and `installed_boot_command` in the vars file

Optional ISO path (set `allow_iso_build: true`):

```bash
export HYOPS_VYOS_ISO_BUILD_METHOD=vyos-vm-images

export HYOPS_VYOS_PACKER_TEMPLATE="${HYOPS_CORE_ROOT:-$HOME/.hybridops/core/app}/packs/images/packer/shared/qemu/images/10-vyos-image-build@v1.0/stack/vyos-qemu.pkr.hcl"

hyops apply --env dev \
  --module core/shared/vyos-image-build \
  --inputs "$HYOPS_CORE_ROOT/modules/core/shared/vyos-image-build/examples/inputs.min.yml"
```

Packer stage-1 template contract:

- `source_iso_path`
- `build_output_directory`

Packer stage-2 template contract:

- `source_disk_path`
- `build_output_directory`

The packaged wrapper then moves/converts the validated stage-2 disk into:

- `artifact_local_path`
- `artifact_format`

Current packaged stage behavior:

- stage 1: boot the live VyOS ISO, reassert the console login prompt, run the documented `install image` flow through console automation, then follow the installer's reboot prompt
- stage 2: boot the installed disk, recover the login prompt, enable DHCP and SSH/password auth explicitly, install and enable `cloud-init` plus `qemu-guest-agent` for Proxmox `ciuser`/`ipconfig`/`cicustom` consumers, then let Packer switch to the SSH communicator and clean cloud-init state plus builder-specific ethernet config for templating
- if `cloud-init` or `qemu-guest-agent` cannot be installed, the build now fails explicitly instead of silently producing a non-cloud image
- stage-1 boot waits are conservative; current rolling ISO shows the login prompt around ~150s in serial logs, so the scaffold sets `boot_wait` to 180s and retries `<enter>` to catch the prompt
- stage-2 runs on a single QEMU user-mode NIC that enumerates as `eth0`; the bundled vars file enables DHCP on `eth0` to ensure a default route for apt
- stage-2 now fails fast when the VyOS cloud-init module (`cc_vyos.py`) is missing, to prevent publishing a broken artifact that ignores `vyos_config_commands`

Do not assume the packaged `boot_command` is already universal for every rolling build. Validate and adjust it per pinned VyOS release. The packaged scaffold now follows the documented `reboot`/`Yes` installer exit instead of trying to force a live-ISO poweroff, and it explicitly selects the KVM console during install so stage 2 can continue over the VNC/KVM path. The default wrapper now auto-loads the packaged `vyos-qemu.auto.pkrvars.hcl.example` scaffold unless you override `HYOPS_VYOS_PACKER_VARS_FILE`. The default wrapper preserves the stage-1 disk on failure (`packer build -on-error=abort`) so installer/reboot mismatches can be inspected instead of losing the only useful artifact.

Builder posture:

- the packaged Packer scaffold now defaults `qemu_accelerator` to `kvm`
- this is the expected product path for ISO-based VyOS builds
- recommended builder: on-prem/Proxmox or another host that exposes `/dev/kvm`
- the wrapper fails fast if the ISO build is attempted on `tcg`, unless you explicitly opt into debug mode with:
  - `HYOPS_VYOS_ALLOW_TCG=1`
- use `tcg` only to debug installer timing, not as the default artifact build path

Alternative explicit builder:

```bash
export HYOPS_VYOS_ISO_BUILD_COMMAND='my-vyos-builder \
  --iso "$HYOPS_VYOS_SOURCE_ISO_PATH" \
  --output "$HYOPS_VYOS_ARTIFACT_LOCAL_PATH"'
```

Behavior:

- if `artifact_local_path` already exists and `rebuild_if_exists=false`, the build step is skipped
- if `build_command` is set and the local artifact is missing, HyOps runs it
- if `smoke_verify_command` is set, HyOps runs it before publish; by default this is a hard gate (`smoke_verify_required=true`)
- if `publish_command` is set, HyOps runs it after the local artifact exists
- if `repo_state_ref` is set, HyOps resolves bucket/container settings from upstream object-repo state before the publish step
- if `artifact_sha256` is empty and the local artifact exists, HyOps computes it

Fresh-user expectation:

- yes, a new HyOps user can build and persist the image through this module path
- they still need two explicit prerequisites:
  - a target object repo, for example `org/gcp/object-repo#vyos_artifacts`
  - an upload credential outside Terraform state, for example a GCS service-account key stored as `HYOPS_VYOS_GCS_SA_JSON`
- once those exist, the module can build and publish in one run
- this is intentional: HybridOps does not place object-store upload credentials into Terraform state

Recommended first-run sequence:

1. Apply the target object-repo module.
2. Store the upload credential in the selected secret source or env runtime vault.
3. Apply `core/shared/vyos-image-build`.
4. Consume the resulting artifact state from the Proxmox and Hetzner seed modules.

Examples:

- `inputs.min.yml`
  - standalone/runnable
  - explicit `artifact_url`
- `inputs.gcs-state.yml`
  - preferred state-first publish target
  - consumes `org/gcp/object-repo#vyos_artifacts`

Command execution notes:

- example commands use:
  - `${HYOPS_CORE_ROOT:-$HOME/.hybridops/core/app}/tools/build/vyos/...`
  - `${HYOPS_CORE_ROOT:-$HOME/.hybridops/core/app}/packs/images/packer/shared/qemu/images/10-vyos-image-build@v1.0/stack/...`
- this works from:
  - a source checkout when `HYOPS_CORE_ROOT` points at `hybridops-core`
  - the installed payload under `~/.hybridops/core/app`

Outputs match `core/shared/vyos-image-artifact`, so downstream modules can consume either module via:

- `artifact_state_ref`
- `artifact_key`

This keeps the product state-first:

- build once
- publish once
- register one canonical VyOS artifact contract
- let Proxmox and Hetzner seed modules consume it by default

Hetzner consumption note:

- prefer a public `https://...` artifact URL in state.
- `gs://...` is not directly reachable by Hetzner rescue; publish/resolve the equivalent public object URL (for example `https://storage.googleapis.com/...`).
