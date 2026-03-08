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

First-boot networking:

- The foundation cloud-init config now pins Hetzner's standard public host route and default route via `172.31.1.1` on `eth0`.
- This keeps custom VyOS images aligned with Hetzner's routed public network model and avoids relying on implicit DHCP route behavior alone.
- Hetzner Cloud Networks are also routed. The private NIC is therefore configured as `private_ip/32`, with an explicit route to `private_network_cidr` via the standard private gateway (`cidrhost(private_network_cidr, 1)`).
- The foundation also performs one intentional first-boot reboot after cloud-init writes `config.boot`.
- This is required because `vyos_config_commands` persist the target config for the next VyOS boot; without that second boot the public/private edge interfaces may not be active yet.

IPsec firewall allowlist:

- `ipsec_source_cidrs` must include every public peer that will terminate IPsec on the Hetzner edges.
- For the baseline GCP HA VPN path, include the Cloud VPN public gateway IPs.
- For the on-prem site-extension path, also include the on-prem peer endpoint (for example `198.51.100.10/32`).
- If a peer is omitted here, the VyOS responder will never answer IKE even if the day-2 config is otherwise correct.

Example:

```bash
hyops validate --env dev --skip-preflight \
  --module org/hetzner/vyos-edge-foundation \
  --inputs "$HYOPS_CORE_ROOT/modules/org/hetzner/vyos-edge-foundation/examples/inputs.min.yml"
```
