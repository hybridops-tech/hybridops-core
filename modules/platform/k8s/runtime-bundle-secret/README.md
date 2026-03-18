# platform/k8s/runtime-bundle-secret

Publishes a local runtime bundle file into a Kubernetes `Secret`.

This module is intended for private or generated application payloads that should
not be encoded into the public `hybridops-workloads` repository. Typical use
cases include:

- SSR or static-site runtime bundles built from a private source tree
- generated app payloads that need to be mounted into a container at runtime
- private app artifacts that should be delivered through the same HyOps
  execution model as the rest of the platform

What it does:

- resolves the target kubeconfig from `kubeconfig_path` or `kubeconfig_state_ref`
- optionally creates the target namespace
- creates or updates an `Opaque` Kubernetes `Secret`
- stores the source file under `bundle_key`
- publishes the SHA-256 of the current bundle so downstream steps can track what
  was applied
- can optionally restart named rollout targets when the bundle SHA changes

Important:

- this module does not build the application bundle; it only syncs a local file
  into the cluster
- this keeps private build logic out of the public workloads repo
- secrets needed by the workload itself should be managed separately through the
  normal secret-store path
- HyOps applies the Secret with Kubernetes server-side apply so larger bundle
  payloads do not fail on `last-applied-configuration` annotation size limits

Required inputs:

- `namespace`
- `secret_name`
- `bundle_source_path`
- one of:
  - `kubeconfig_path`
  - `kubeconfig_state_ref`

Optional rollout inputs:

- `restart_targets`
  - list of Kubernetes rollout resources in the same namespace, for example
    `deployment/showcase-burst-web`
- `rollout_timeout_s`
  - timeout used for `kubectl rollout status` after a restart

Outputs:

- `namespace`
- `secret_name`
- `bundle_key`
- `bundle_sha256`
- `restarted_targets`
- `cap.k8s.runtime_bundle_secret = ready`
