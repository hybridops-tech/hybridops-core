# org/gcp/wan-vpn-to-edge

Provision GCP HA VPN + Cloud Router BGP peers to external edge endpoints.

This module can import:

- `project_id` and `network_self_link` from `org/gcp/wan-hub-network`
- cloud subnet ranges from `org/gcp/wan-hub-network`, including the GKE pod secondary range
- `router_name` from `org/gcp/wan-cloud-router`
- `peer_ip_a` and `peer_ip_b` from `org/hetzner/vyos-edge-foundation`

Those imported values are the normal state-driven path for durable env overlays.
Keep the explicit fields only when you intentionally need to override upstream state.

Published state includes the resolved `project_id` and `network_self_link`, so recovery flows can detect when an env has moved to a different GCP project before reusing old Terraform Cloud state.

State driven cloud prefix note:

- when `auto_include_cloud_*` inputs are enabled, the module dedupes the effective
  `advertised_prefixes` set from `org/gcp/wan-hub-network` outputs and any explicit
  prefixes you still provide
- this is the correct path for GKE burst lanes because the pod secondary range must be
  advertised over HA VPN if burst pods are expected to reach on prem systems directly

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
