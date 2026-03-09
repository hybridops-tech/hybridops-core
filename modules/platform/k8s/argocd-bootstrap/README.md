# platform/k8s/argocd-bootstrap

Bootstraps Argo CD on an existing Kubernetes cluster and applies a root workloads Application.

This module is platform-neutral and can be used for onprem, burst, and DR Kubernetes clusters.

## Usage

```bash
hyops apply --env dev \
  --module platform/k8s/argocd-bootstrap \
  --inputs modules/platform/k8s/argocd-bootstrap/examples/inputs.typical.yml
```

## Inputs

- `kubeconfig_path` (required for apply): path to kubeconfig on controller host.
- `install_argocd`: install/upgrade Argo CD manifests before creating root Application.
  - HyOps applies the upstream install manifest using Kubernetes server-side apply
    to avoid large CRD `metadata.annotations` limits on newer Argo CD manifests.
- `argocd_install_force_conflicts`: force server-side apply conflicts during Argo CD
  install/upgrade (default `true`) so reruns can converge after partial client-side applies.
- `workloads_repo_url`, `workloads_revision`, `workloads_target_path`: root Application source.
- `root_app_*`: root Application metadata/project/namespace contract.

Default workloads repo URL:
- `https://github.com/hybridops-tech/hybridops-workloads.git`

Use the public workloads repo for customer-facing and baseline deployments.

Override `workloads_repo_url` when you intentionally consume a private canonical
workloads repo. The Argo CD contract stays the same:
- public/exported workloads repo: `workloads_target_path = clusters/<target>`
- private/canonical workloads repo: `workloads_target_path = .internal/clusters/<target>`

`workloads_target_path` should map to your cluster target in `hybridops-workloads`, e.g.:
- `clusters/onprem-stage1`
- `clusters/burst`
- `clusters/dr`

If you consume a private canonical workloads repo, point `workloads_target_path`
at the internal target instead, e.g.:
- `.internal/clusters/onprem-learn-stage1`
- `.internal/clusters/onprem-ci-stage1`

## Outputs

- `kubeconfig_path`
- `argocd_namespace`
- `root_app_name`
- `workloads_repo_url`
- `workloads_revision`
- `workloads_target_path`
- `cap.gitops.argocd = ready`
