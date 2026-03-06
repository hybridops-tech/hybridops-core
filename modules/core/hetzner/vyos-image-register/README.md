# core/hetzner/vyos-image-register

Register a pre-imported Hetzner custom image or snapshot reference into HyOps state for downstream VyOS edge modules.

Use this when you already have an official VyOS image available in Hetzner and want HyOps to consume it state-first instead of hardcoding the image name or snapshot reference in every edge blueprint.

Typical usage:

```bash
hyops validate --env dev --skip-preflight \
  --module core/hetzner/vyos-image-register \
  --inputs "$HYOPS_CORE_ROOT/modules/core/hetzner/vyos-image-register/examples/inputs.min.yml"
```

Downstream modules consume:

- `image_state_ref`
- `image_key`

and HyOps resolves:

- `image`

without duplicating image references in every blueprint.

Compatibility note:

- Prefer [`core/hetzner/vyos-image-seed`](/home/user/hybridops-studio/hybridops-core/modules/core/hetzner/vyos-image-seed/README.md) for the default seed-or-skip path.
- Use this register-only module when the Hetzner custom image is managed outside HyOps and you only want to publish its reference into state.
