# org/gcp/wan-vpn-to-edge

Provision GCP HA VPN + Cloud Router BGP peers to external edge endpoints.

This module can import:

- hub network contract from `org/gcp/wan-hub-network`
- router name from `org/gcp/wan-cloud-router`
- edge public IPs from `org/hetzner/wan-edge-foundation`

PSKs are required (`shared_secret_a`, `shared_secret_b`).
