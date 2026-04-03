# core/shared/vyos-image-artifact

Register one canonical VyOS disk artifact contract into HybridOps state so both Proxmox and Hetzner seed modules consume the same source by default.

This is the lightweight compatibility path. It does not build the image itself; it registers the pinned artifact URL and metadata that downstream seed modules can resolve state-first.

For the default build-and-publish path, use `core/shared/vyos-image-build`.

Typical usage:

```bash
hyops validate --env dev --skip-preflight \
  --module core/shared/vyos-image-artifact \
  --inputs "$HYOPS_CORE_ROOT/modules/core/shared/vyos-image-artifact/examples/inputs.min.yml"
```

Inputs:

- `artifact_key`: logical family key, for example `vyos-1.5
- `artifact_url`: directly downloadable disk image artifact URL
- `artifact_format`: `qcow2`, `raw`, or `img`
- `artifact_version`: optional operator-visible version label
- `artifact_sha256`: optional checksum for provenance
- `source_iso_url`: optional upstream ISO URL used to build the artifact

Downstream modules consume:

- `artifact_state_ref`
- `artifact_key`

and HybridOps resolves:

- `image_source_url`
- `template_source_url`
- version/provenance fields

This keeps the product state-first:

- build and publish one canonical VyOS artifact once
- publish it into HybridOps state
- let Proxmox and Hetzner seed modules consume it by default

Direct `image_source_url` remains the explicit override path when you intentionally bypass the shared artifact contract.
