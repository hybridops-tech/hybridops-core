# core/azure/nat-gateway

Create or converge an Azure NAT Gateway and public IP via the Terragrunt Azure foundation pack.

## Usage

```bash
hyops preflight --env <env> --strict \
  --module core/azure/nat-gateway \
  --inputs "modules/core/azure/nat-gateway/examples/inputs.min.yml"

hyops apply --env <env> \
  --module core/azure/nat-gateway \
  --inputs "modules/core/azure/nat-gateway/examples/inputs.min.yml"
```

## Dependencies

- Imports `resource_group_name` and `location` from `core/azure/resource-group` when available.

## Outputs

- `nat_gateway_id`
- `nat_gateway_name`
- `public_ip_id`
- `public_ip_address`
