# core/onprem/vyos-template-seed

Seed or discover a Proxmox VyOS template, then publish it into HybridOps state for downstream VyOS edge modules.

Default behavior:

- If the target `template_vm_id` already exists and is a template, HybridOps publishes it.
- If the template is missing and `seed_if_missing=true`, HybridOps seeds it from a directly downloadable disk image or a custom `seed_command`.
- If the template already exists and `rebuild_if_exists=true`, HybridOps rebuilds it from scratch.
- If `artifact_state_ref` is set, HybridOps resolves the shared VyOS artifact contract from upstream state first and uses that artifact URL by default.
- Firmware mode is normalized to `seabios` during seed. If an existing template at the same VMID is not `seabios`, HybridOps fails fast unless `rebuild_if_exists=true`.
- After seed/rebuild, HybridOps runs a template smoke gate by default: an ephemeral clone boots with cloud-init and HybridOps verifies the expected marker landed in `config.boot` before publishing success.
- The smoke gate is transient by design. On success it must leave only the target template in Proxmox; leftover `smoke-*` VMs, `hyops-vyos-smoke-*` snippets, or `/var/tmp/hyops-vyos-smoke-mnt-*` directories indicate stale debug residue and should be cleaned before further work.
- The authoritative `cc_vyos.py` lives under `tools/build/vyos/assets/cc_vyos.py`. Seed and build paths must consume that single source of truth.

## Usage

`hyops apply --env dev --module core/onprem/vyos-template-seed --inputs modules/core/onprem/vyos-template-seed/examples/inputs.min.yml`

## Inputs

- `template_key`: logical template family key, for example `vyos-1.5`
- `artifact_state_ref`: optional shared VyOS artifact module state, for example `core/shared/vyos-image-build#vyos_default_build` (legacy artifact registration state is still supported)
- `artifact_key`: optional artifact key override; defaults to `template_key` when omitted
- `required_env`: optional env keys that HybridOps must hydrate before downloading a private shared artifact
- `template_vm_id`: target Proxmox template VMID
- `template_name`: target Proxmox template name
- `template_image_version`: optional operator-visible image version label
- `template_source_url`: optional source URL for provenance
- `image_source_url`: direct downloadable disk image artifact, not an installer ISO page
- `seed_command`: optional custom command when you need a non-default ISO-to-template workflow
- `template_smoke_gate`: enable/disable the default post-seed smoke gate (default `true`)
- `template_smoke_wait_s`: wait time before smoke verification inspects the clone disk (default `90`)
- `template_smoke_vmid`: optional fixed VMID for the temporary smoke clone (default `template_vm_id + 9000`)
- `template_smoke_bridge`: optional bridge override for smoke clone NIC0 (default resolved `network_bridge`)
- `template_smoke_marker`: optional marker string that must appear in clone `config.boot` for smoke success
- private GCS-backed shared artifacts are supported through:
  - `HYOPS_VYOS_GCS_SA_JSON`, or
  - `HYOPS_VYOS_GCS_SA_JSON_FILE`
- declare the selected key in `required_env` so HybridOps hydrates it before the seed step

HybridOps defaults to a shared artifact-first contract:

- build and publish one canonical VyOS disk artifact
- register/publish it into HybridOps state
- let Proxmox and Hetzner seed modules consume that state

Recommended operator path:

- build and publish with `core/shared/vyos-image-build`
- consume that state via `artifact_state_ref`
- use direct `image_source_url` only as the override path when you intentionally bypass the shared artifact contract

HybridOps does not prescribe how you build or store the image. The clean contract is:

- operator provides a usable, directly downloadable disk image artifact URL
- HybridOps consumes that URL to seed or rebuild the template
- when the shared artifact lives in a private GCS bucket, the controller downloads it locally with the supplied service-account credential and then copies the disk to Proxmox; the Proxmox host itself does not need direct bucket access
- if your upstream source is ISO-only, provide a custom `seed_command` instead

The default seed path reuses Proxmox init metadata from the selected HybridOps runtime. You can override:

- `proxmox_host`
- `proxmox_node`
- `storage_vm`
- `network_bridge`
- `ssh_username`
- `ssh_private_key`

## Outputs

- `template_key`
- `template_vm_id`
- `template_name`
- `template_image_version`
- `template_source_url`
- `template_seeded`
- `templates`

Downstream VyOS modules should consume this state using:

```yaml
template_state_ref: "core/onprem/vyos-template-seed"
template_key: "vyos-1.5"
```

Compatibility:

- Use [`core/onprem/vyos-template-import`](../vyos-template-import/README.md) when the Proxmox template is managed entirely outside HybridOps and you only want to register it into state.
