# platform/linux/gns3-healthcheck

Validate an installed GNS3 server and its local compute runtime. The module
checks service state, API authentication, nested KVM, emulator commands and
writable data directories.

Set `gns3_healthcheck_deep: true` to run a disposable VPCS lifecycle. The
temporary project is removed after the check.

```bash
hyops apply --env lab \
  --module platform/linux/gns3-healthcheck \
  --inputs modules/platform/linux/gns3-healthcheck/examples/inputs.min.yml
```
