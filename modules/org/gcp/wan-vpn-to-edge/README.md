# org/gcp/wan-vpn-to-edge

Provision GCP HA VPN + Cloud Router BGP peers to external edge endpoints.

This module can import:

- hub network contract from `org/gcp/wan-hub-network`
- router name from `org/gcp/wan-cloud-router`
- edge public IPs from `org/hetzner/vyos-edge-foundation`

PSKs are required for both tunnels.

The reusable default path is env-backed:

- `required_env`
- `shared_secret_a_env`
- `shared_secret_b_env`

By default both tunnels consume the same env key, `WAN_IPSEC_PSK`, which keeps the GCP
VPN step aligned with the current VyOS day-2 module contract.

You may still provide explicit `shared_secret_a` / `shared_secret_b` values for controlled
overrides, but shipped blueprints should prefer the env-backed contract.

Placeholder values such as `CHANGE_ME_PSK_A` and `CHANGE_ME_PSK_B` are rejected by
validation.
