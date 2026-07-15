# platform/linux/gns3-images

Install declared QEMU images and register them as templates on an authenticated
GNS3 server. Every URL requires a SHA-256 checksum. Existing matching templates
are retained; conflicting template names fail without replacement.

```bash
hyops apply --env lab \
  --module platform/linux/gns3-images \
  --inputs modules/platform/linux/gns3-images/examples/inputs.min.yml
```

No proprietary image is bundled. Operators remain responsible for image
licensing and distribution rights.
