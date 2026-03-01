# org/hetzner/wan-edge-foundation

Provision Hetzner WAN edge baseline infrastructure:

- 2 edge VMs (`edge-01`, `edge-02`)
- private network/subnet
- firewall policy (SSH + IPsec)
- floating IPv4 assignment to active edge node

## Usage

```bash
hyops preflight --env <env> --strict \
  --module org/hetzner/wan-edge-foundation \
  --inputs "$HYOPS_CORE_ROOT/modules/org/hetzner/wan-edge-foundation/examples/inputs.min.yml"

hyops apply --env <env> \
  --module org/hetzner/wan-edge-foundation \
  --inputs "$HYOPS_CORE_ROOT/modules/org/hetzner/wan-edge-foundation/examples/inputs.min.yml"
```

## Notes

- `inputs.ssh_public_key` must be a real SSH public key (not a placeholder).
- Fast way to test with your workstation key:

```bash
cp "$HYOPS_CORE_ROOT/modules/org/hetzner/wan-edge-foundation/examples/inputs.min.yml" /tmp/hyops-wan-edge.yml
sed -i "s|ssh_public_key:.*|ssh_public_key: \"$(tr -d '\n' < ~/.ssh/id_ed25519.pub)\"|" /tmp/hyops-wan-edge.yml
hyops preflight --env <env> --strict --module org/hetzner/wan-edge-foundation --inputs /tmp/hyops-wan-edge.yml
```
