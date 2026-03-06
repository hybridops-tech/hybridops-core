# core/onprem/vyos-template-import

Registers an already imported official VyOS Proxmox template into HyOps state.

This is the honest first step for the VyOS edge path:
- import the official VyOS cloud image into Proxmox once
- convert it to a reusable template
- publish that template into HyOps state
- let downstream modules consume it by `template_state_ref`

This module does **not** automate the Proxmox image import yet. It exists so the VyOS edge path can be state-first now without pretending the full template-import automation is already finished.

## Usage

`hyops apply --env dev --module core/onprem/vyos-template-import --inputs modules/core/onprem/vyos-template-import/examples/inputs.min.yml`

## Inputs

- `template_key`: logical template family key, for example `vyos-1.5`
- `template_vm_id`: existing Proxmox template VMID
- `template_name`: existing Proxmox template name
- `template_image_version`: optional operator-visible image version label
- `template_source_url`: optional source URL for evidence/provenance

## Outputs

- `template_key`
- `template_vm_id`
- `template_name`
- `template_image_version`
- `template_source_url`
- `templates`

Downstream VyOS modules should consume this state using:

```yaml
template_state_ref: "core/onprem/vyos-template-import"
template_key: "vyos-1.5"
```
