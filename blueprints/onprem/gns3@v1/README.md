# On-Prem GNS3 Platform Stack

Build a dedicated GNS3 server on Proxmox from a verified Ubuntu 22.04
template. The blueprint provisions the VM and configures the authenticated
GNS3 API through the provider-neutral Linux module.

The API listens on the VM loopback interface. A desktop-client access command
will provide the private tunnel in a separate change; the server is not exposed
to the local network by this blueprint.

## Execution chain

```text
core/onprem/template-image
  -> platform/onprem/platform-vm
  -> platform/linux/gns3-server
```

## Prerequisites

- Proxmox access is configured through `hyops init proxmox`.
- The configured Proxmox bridge provides DHCP connectivity.
- The Proxmox host permits nested virtualization for a VM using CPU type
  `host`.
- The GNS3 API password is stored in the environment vault.

```bash
hyops secrets ensure --env gns3-lab GNS3_SERVER_PASSWORD
```

## Validate and deploy

```bash
hyops blueprint validate --ref onprem/gns3@v1

hyops blueprint preflight \
  --env gns3-lab \
  --ref onprem/gns3@v1

hyops blueprint deploy \
  --env gns3-lab \
  --ref onprem/gns3@v1 \
  --execute
```

## Default VM

- name: `gns3-01`
- CPU: 4 cores, type `host`
- memory: 16 GB
- disk: 128 GB
- management network: `vmbr0` with DHCP
- API: authenticated HTTP on VM loopback port 3080

Ordinary blueprint destroy removes the workload VM and retains the reusable
Ubuntu template.
