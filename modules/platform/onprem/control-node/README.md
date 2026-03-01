# platform/onprem/control-node

Creates or converges the control-plane VM on Proxmox.

## Usage
`hyops deploy --module platform/onprem/control-node --inputs modules/platform/onprem/control-node/examples/inputs.typical.yml`

## Inputs
- `examples/inputs.min.yml` smallest practical overlay.
- `examples/inputs.typical.yml` common production-ready overlay.
- `examples/inputs.enterprise.yml` advanced enterprise override.

Defaults remain in `spec.yml`; overlays are preferred for customization.
