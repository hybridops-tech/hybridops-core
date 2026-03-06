# core/hetzner/vyos-image-seed

Seed or discover a Hetzner VyOS custom image, then publish the image contract into HyOps state for downstream edge modules.

Default behavior:

- If `image_ref` is provided, HyOps verifies and publishes that image reference.
- If `image_ref` is empty, HyOps looks for an existing snapshot using the effective image description.
- If no matching image exists and `seed_if_missing=true`, HyOps runs the seeding tool once, captures the created image id, and publishes it.
- If `artifact_state_ref` is set, HyOps resolves the shared VyOS artifact contract from upstream state first and uses that artifact URL by default.

The default seeding path expects the `hcloud-upload-image` helper to be installed on the execution host.

Practical note for VyOS:

- if `image_source_url` points to a directly downloadable `qcow2` artifact (for example the same qcow2 you use on Proxmox), HyOps will auto-wrap it into a temporary raw image for Hetzner seeding
- when using that qcow2 auto-wrap path, set `seed_wrapper_public_base_url` to a publicly reachable base URL for the execution host so Hetzner rescue can fetch the temporary wrapped artifact
- if your Hetzner project restricts import locations, set `seed_location` (for example `nbg1`) so `hcloud-upload-image` creates its temporary import server in an allowed location
- if your image virtual disk is larger than the default import server disk, set `seed_server_type` (for example `cpx21` for 80G) so the temporary import server has enough disk
- if your only upstream source is an installer ISO, keep `image_source_url` empty and provide a custom `seed_command` that performs the ISO-to-image workflow before snapshot creation

HybridOps defaults to a shared artifact-first contract:

- build and publish one canonical VyOS disk artifact
- register/publish it into HyOps state
- let Proxmox and Hetzner seed modules consume that state

Recommended upstream state reference:

- `artifact_state_ref: core/shared/vyos-image-build#vyos_default_build`

Direct `image_source_url` is the override path when you intentionally bypass the shared artifact contract.

HybridOps does not prescribe how you build or store that disk image. The clean contract is:

- operator provides one canonical, directly downloadable disk image artifact URL
- Proxmox can consume the qcow2 directly
- Hetzner can consume the same qcow2 by using the built-in wrapper path
- if your upstream source is ISO-only, provide a custom `seed_command` instead

The qcow2 auto-wrap path is intended for runners or shared control hosts with a public address. If the execution host is not publicly reachable, either:

- pre-convert and host a raw image URL directly, or
- provide a custom `seed_command`

URL validation behavior:

- HyOps now probes `image_source_url` reachability before launching the seeding command.
- If the URL is invalid/unreachable, the module fails fast with guidance to run `core/shared/vyos-image-build` and consume `artifact_state_ref`/`artifact_key`.

Typical usage:

```bash
hyops validate --env dev --skip-preflight \
  --module core/hetzner/vyos-image-seed \
  --inputs "$HYOPS_CORE_ROOT/modules/core/hetzner/vyos-image-seed/examples/inputs.min.yml"
```

Compatibility:

- Use [`core/hetzner/vyos-image-register`](/home/user/hybridops-studio/hybridops-core/modules/core/hetzner/vyos-image-register/README.md) when you already seeded a Hetzner image outside HyOps and only want to register it into state.
