# GCP GNS3 Teaching Lab

Deploy a private GNS3 server and a zero-image starter topology on Google Cloud.
The VM has no public IP; SSH and desktop-client access use IAP.

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

## Connect a desktop client

```bash
hyops blueprint access --env gns3-gcp --ref gcp/gns3@v1
```

Keep the command running and configure the GNS3 desktop client to use the
printed loopback endpoint. Retrieve the API password when required:

```bash
hyops secrets show --env gns3-gcp GNS3_SERVER_PASSWORD
```

## Remove the lab

```bash
hyops blueprint destroy --env gns3-gcp --ref gcp/gns3@v1 --execute
```
