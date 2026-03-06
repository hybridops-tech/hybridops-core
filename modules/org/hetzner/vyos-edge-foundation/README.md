# org/hetzner/vyos-edge-foundation

Provision two VyOS routed edge nodes on Hetzner using a state-published VyOS image reference.

State-first defaults:

- `image_state_ref`: resolves the Hetzner VyOS image from `core/hetzner/vyos-image-seed`
- outputs remain compatible with consumers that only need edge public/private IPs and the private network contract

Compatibility:

- `core/hetzner/vyos-image-register` remains supported when the Hetzner custom image is managed outside HyOps.

This module intentionally reuses the existing Hetzner VM/network Terraform substrate. It changes the routed-edge product path, not the shared-control host path.

SSH key behavior:

- If `ssh_key_name` already exists in Hetzner, the module reuses it.
- If `ssh_key_name` does not exist, provide `ssh_public_key` and the module creates it.
- If both are present but key material differs, apply fails fast with a clear mismatch error.

Default placement:

- Defaults target `location=ash` / `home_location=ash` with `server_type=cpx21`, which is a known working combo for the current VyOS image flow.
- Override `location`, `home_location`, and `server_type` together when your Hetzner project has different regional capacity.

Example:

```bash
hyops validate --env dev --skip-preflight \
  --module org/hetzner/vyos-edge-foundation \
  --inputs "$HYOPS_CORE_ROOT/modules/org/hetzner/vyos-edge-foundation/examples/inputs.min.yml"
```
