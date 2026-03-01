# core/azure/resource-group

Create or converge an Azure Resource Group via the Terragrunt Azure foundation pack.

## Usage

```bash
hyops preflight --env <env> --strict \
  --module core/azure/resource-group \
  --inputs "modules/core/azure/resource-group/examples/inputs.min.yml"

hyops apply --env <env> \
  --module core/azure/resource-group \
  --inputs "modules/core/azure/resource-group/examples/inputs.min.yml"
```

## Outputs

- `resource_group_id`
- `resource_group_name`
- `location`
