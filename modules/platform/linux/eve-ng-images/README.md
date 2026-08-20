# platform/linux/eve-ng-images

Load curated EVE-NG device images onto an existing EVE-NG host.

This module is intentionally separate from `platform/linux/eve-ng`:

- `platform/linux/eve-ng` installs and configures the base EVE-NG runtime
- `platform/linux/eve-ng-images` manages device images after the base host is ready

## Typical use

```bash
hyops apply --env dev \
  --module platform/linux/eve-ng-images \
  --inputs modules/platform/linux/eve-ng-images/examples/inputs.min.yml
```

## Access modes

The module supports the same target resolution and SSH access patterns as `platform/linux/eve-ng`:

- direct host access
- explicit bastion jump
- GCP IAP
- state-driven target resolution from a VM module

## IOL licence material

IOL binaries and their host-bound licence are separate inputs. Store an
authorised `iourc` without exposing it on the command line:

```bash
hyops secrets set --env <env> --from-file EVENG_IOL_LICENSE=/path/to/iourc
```

Then set `load_vault_env: true`, add `EVENG_IOL_LICENSE` to `required_env`,
and enable `eveng_images_iol_license_required`. Deployment places the licence
in the EVE-NG IOL directory and publishes only its readiness state. HybridOps
does not download, generate, log, or archive the licence material.

## Destroy behaviour

Destroy is conservative.

- the cache directory is always cleaned
- installed images are removed only when `eveng_images_destroy_paths` explicitly lists paths under `/opt/unetlab/addons/`

That avoids wiping a shared image library accidentally.
