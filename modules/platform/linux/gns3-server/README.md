# platform/linux/gns3-server

Installs and configures an authenticated GNS3 server on Ubuntu 22.04 or 24.04 x86_64 and publishes the lab-platform readiness contract used by HybridOps blueprints.

This is the provider-neutral GNS3 server layer. Enclosing blueprints supply the execution host and access transport, the image module supplies declared lab images, and operator-side GNS3 clients consume the private server endpoint.

Supported access transports include direct SSH, a jump host and GCP IAP.

The module can enable KVM-backed local compute, install the open-source emulator runtime and configure the private management network used for topology-node automation.

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

The enclosing blueprint can combine this readiness contract with managed images, starter projects, deep health checks, private client access, topology-node automation and the GNS3 archive/restore lifecycle.
