# GCP Windows Desktop

Provision a Windows Server GCP VM with a public IP and RDP access scoped by firewall source ranges.

Outcome: a Windows Server VM is running in GCP with RDP open only to the configured source ranges.

## Chain

```text
platform/gcp/platform-vm
  -> platform/gcp/vm-firewall-rules
```

See [blueprint.yml](blueprint.yml) for the full contract.

## Usage

```bash
hyops blueprint validate --ref gcp/windows-desktop@v1 --blueprints-root blueprints
hyops blueprint preflight --env dev --ref gcp/windows-desktop@v1 --blueprints-root blueprints
hyops blueprint deploy --env dev --ref gcp/windows-desktop@v1 --blueprints-root blueprints --execute
```
