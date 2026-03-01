# onprem/proxmox/images/00-template-image@v1.0

Packer pack for Proxmox Linux image templates.

Templates are selected by `inputs.template_key` from `packer.build.yml`.

Shared `.pkr.hcl` files live in `shared/` and are synced into the selected template directory at runtime by `hyops` (then cleaned up best-effort).

Current migrated keys:
- `ubuntu-22.04`
- `ubuntu-24.04`
- `rocky-9`
- `rocky-10`
