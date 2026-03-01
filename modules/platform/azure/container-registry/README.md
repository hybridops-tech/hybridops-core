# platform/azure/container-registry

Create or converge Azure Container Registry (ACR) via the Terragrunt shared-services pack.

## Usage

```bash
hyops preflight --env <env> --strict \
  --module platform/azure/container-registry \
  --inputs "modules/platform/azure/container-registry/examples/inputs.min.yml"

hyops apply --env <env> \
  --module platform/azure/container-registry \
  --inputs "modules/platform/azure/container-registry/examples/inputs.min.yml"
```

## Dependencies

- Imports `resource_group_name` and `location` from `core/azure/resource-group` when available.

## Outputs

- `registry_id`
- `registry_name`
- `login_server`
