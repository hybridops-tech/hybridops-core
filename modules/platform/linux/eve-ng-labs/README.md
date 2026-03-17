# platform/linux/eve-ng-labs

Load lab content onto an existing EVE-NG host.

Use this after `platform/linux/eve-ng` has already established the EVE-NG runtime.

## Sources

- `local`
- `git`
- `remote`

## Typical use

```bash
hyops apply --env dev \
  --module platform/linux/eve-ng-labs \
  --inputs modules/platform/linux/eve-ng-labs/examples/inputs.min.yml
```

## Destroy behaviour

Destroy is conservative.

- the staging directory is cleaned
- installed labs are removed only when `eveng_lab_folders` explicitly lists the managed folders

That keeps the module safe for shared lab libraries.
