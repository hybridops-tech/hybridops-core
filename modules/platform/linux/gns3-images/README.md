# platform/linux/gns3-images

Install declared QEMU or IOU images and register them as templates on an
authenticated GNS3 server. Every URL requires a SHA-256 checksum. Existing
matching templates are retained; conflicting template names fail without
replacement.

```bash
hyops apply --env lab \
  --module platform/linux/gns3-images \
  --inputs modules/platform/linux/gns3-images/examples/inputs.min.yml
```

No proprietary image is bundled. Operators remain responsible for image
licensing and distribution rights.

For an authorised IOU image, store its licence separately:

```bash
hyops secrets set --env <env> --from-file GNS3_IOU_LICENSE=/path/to/iourc
```

Set `load_vault_env: true`, include both `GNS3_SERVER_PASSWORD` and
`GNS3_IOU_LICENSE` in `required_env`, and declare the image with `type: iou`.
The runtime installs IOU support, places the image, retains GNS3 licence
checking, and registers the template. It does not generate or archive licence
material. Licences activated inside QEMU guests remain guest-level state.
