# platform/linux/gns3-server

Installs and configures an authenticated GNS3 server on an existing Ubuntu
22.04 or 24.04 x86_64 host. The module is provider-neutral and can use direct
SSH, a jump host or GCP IAP.

It installs the server and open-source emulator runtime. It does not provision
the host, install a desktop client or supply proprietary network images.

## Usage

```bash
hyops secrets ensure --env lab GNS3_SERVER_PASSWORD

hyops apply --env lab \
  --module platform/linux/gns3-server \
  --inputs modules/platform/linux/gns3-server/examples/inputs.min.yml
```

## Outputs

- `gns3_url`
- `gns3_api_port`
- `cap.lab.gns3 = ready`
