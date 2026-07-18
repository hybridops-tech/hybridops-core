# GCP Linux Desktop

Provision an Ubuntu 22.04 GCP VM with public RDP access and configure XFCE with XRDP.

Outcome: an Ubuntu desktop VM is running in GCP and can be reached with an RDP client on port `3389`.

## Chain

```text
platform/gcp/vm-firewall-rules
  -> platform/gcp/platform-vm
  -> platform/linux/desktop-xrdp
```

See [blueprint.yml](blueprint.yml) for the full contract.

## Usage

```bash
hyops blueprint validate --ref gcp/linux-desktop@v1 --blueprints-root blueprints
hyops blueprint preflight --env <env> --ref gcp/linux-desktop@v1 --blueprints-root blueprints
hyops blueprint deploy --env <env> --ref gcp/linux-desktop@v1 --blueprints-root blueprints --execute
```
