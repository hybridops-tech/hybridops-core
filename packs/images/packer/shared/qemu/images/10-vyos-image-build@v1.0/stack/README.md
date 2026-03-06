# shared/qemu/images/10-vyos-image-build@v1.0

Packaged Packer scaffold for building a reusable VyOS disk image from the official installer ISO.

This stack is intentionally generic:

- local `qemu` builder
- not tied to Proxmox directly
- not tied to Hetzner directly

It exists to produce one canonical disk artifact that downstream seed modules can consume:

- `core/onprem/vyos-template-seed`
- `core/hetzner/vyos-image-seed`

Files:

- `vyos-qemu.pkr.hcl`
  - Packer template scaffold
- `vyos-qemu.auto.pkrvars.hcl.example`
  - starting-point variables including a conservative `boot_command`

The default helper path is:

- `${HYOPS_CORE_ROOT:-$HOME/.hybridops/core/app}/packs/images/packer/shared/qemu/images/10-vyos-image-build@v1.0/stack/vyos-qemu.pkr.hcl`

Treat the vars file as a release-specific scaffold, not a guaranteed universal unattended install sequence.
