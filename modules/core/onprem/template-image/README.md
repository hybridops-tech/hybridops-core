# Proxmox Template Image Build Module

`hyops` module for building reproducible Proxmox VM templates with Packer and publishing the resulting template contract into state for downstream VM modules to consume.

Use this when you want Proxmox templates to be rebuildable and verifiable rather than hand-maintained golden images that drift over time.

What this gives you:
- Packer-driven template builds for Linux and Windows families
- published `template_vm_id` / `template_name` outputs for downstream consumers
- automatic post-build smoke validation by cloning the template, booting it, waiting for guest-agent IP, then cleaning up

`hyops deploy` runs the same post-build smoke validation by default using the Proxmox API credentials already configured for the module. Smoke is warning-only by default and can be made required via `inputs.post_build_smoke.required: true`.

## Quick start

```bash
hyops deploy --env dev \
  --module core/onprem/template-image \
  --inputs modules/core/onprem/template-image/examples/inputs.typical.yml
```

To rebuild a template if it already exists, set `rebuild_if_exists: true` in your inputs overlay.

To tune post-build smoke validation:

```yaml
post_build_smoke:
  enabled: true      # default
  required: false    # default (warn-only on smoke failure)
  timeout_s: 300     # Linux default; Windows templates may need higher values
  # vmid_range_start: 990000
  # vmid_range_end: 990999
```

Lifecycle examples:
- `hyops destroy --env dev --module core/onprem/template-image --inputs modules/core/onprem/template-image/examples/inputs.typical.yml`
- `hyops rebuild --env dev --yes --confirm-module core/onprem/template-image --module core/onprem/template-image --inputs modules/core/onprem/template-image/examples/inputs.typical.yml`

## Inputs
- `examples/inputs.min.yml` minimal overlay (defaults template name/ID).
- `examples/inputs.typical.yml` common Linux template build (collision-safe defaults; optional override hints).
- `examples/inputs.enterprise.yml` larger template sizing override (collision-safe defaults; optional override hints).

Supported `template_key` values:
- `ubuntu-22.04`
- `ubuntu-24.04`
- `rocky-9`
- `rocky-10`
- `windows-server-2022`
- `windows-server-2025`
- `windows-11-enterprise`

Common use:
- build a base Ubuntu or Rocky template once
- publish the template contract into state
- let downstream VM modules consume it by `template_state_ref` instead of hardcoding VMIDs

## Outputs
- `template_key`
- `template_vm_id`
- `template_name`
- `template_vm_ids`
- `templates`

Use `template_state_ref` in `platform/onprem/platform-vm` to consume these outputs without hardcoding template IDs.

## Run Record Files

Template-image apply writes:

- `packer.log`
- `template_smoke.json` (automatic post-build smoke summary)
- `template_smoke.log` (smoke step status stream)
