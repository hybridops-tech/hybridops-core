# GCP GNS3 Teaching Lab

Deploy a private GNS3 server and a zero-image starter topology on Google Cloud.
The VM has no public IP; SSH, Web UI and desktop-client access use IAP.

## Execution chain

```text
platform/gcp/lab-network
  -> platform/gcp/platform-vm
  -> platform/linux/gns3-server
  -> platform/linux/gns3-images
  -> platform/linux/gns3-starter-lab
  -> platform/linux/gns3-healthcheck
```

## Prerequisites

Initialise the GCP environment and seed the GNS3 API password:

```bash
hyops init gcp --env gns3-gcp
hyops secrets ensure --env gns3-gcp GNS3_SERVER_PASSWORD
```

GCP initialisation and module preflight confirm project, authentication and
billing readiness before resources are created.

## Deploy

```bash
hyops blueprint preflight --env gns3-gcp --ref gcp/gns3@v1
hyops blueprint deploy --env gns3-gcp --ref gcp/gns3@v1 --execute
```

## Connect to GNS3

```bash
hyops blueprint access --env gns3-gcp --ref gcp/gns3@v1
```

Keep the command running. Open the printed HTTP endpoint in a browser or
configure the GNS3 desktop client to use it. The default username is `gns3`.
Retrieve the password from the environment vault:

```bash
hyops secrets show --env gns3-gcp --raw GNS3_SERVER_PASSWORD
```

## Remove the lab

```bash
hyops blueprint destroy --env gns3-gcp --ref gcp/gns3@v1 --execute
```

The interactive destroy flow can export and verify GNS3 projects before
teardown. Project topology, controller metadata and writable node disks are
preserved; downloadable base images are rebuilt from their declarations.

Restore the latest verified archive during redeployment:

```bash
hyops blueprint deploy \
  --env gns3-gcp \
  --ref gcp/gns3@v1 \
  --execute \
  --restore-labs
```
