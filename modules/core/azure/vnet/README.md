# core/azure/vnet

Create or converge an Azure Virtual Network via the Terragrunt Azure foundation pack.

## Usage

```bash
hyops preflight --env <env> --strict \
  --module core/azure/vnet \
  --inputs "modules/core/azure/vnet/examples/inputs.min.yml"

hyops apply --env <env> \
  --module core/azure/vnet \
  --inputs "modules/core/azure/vnet/examples/inputs.min.yml"
```

## Dependencies

- Imports `resource_group_name` and `location` from `core/azure/resource-group` when available.

## Outputs

- `vnet_id`
- `vnet_name`
- `resource_group_name`
- `location`
