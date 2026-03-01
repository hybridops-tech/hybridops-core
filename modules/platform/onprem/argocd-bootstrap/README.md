# platform/onprem/argocd-bootstrap

Bootstraps Argo CD on an existing on-prem Kubernetes cluster and applies a root workloads Application.

This module remains for backward compatibility with existing onprem blueprints.
For new multi-target designs (onprem + burst + DR), prefer `platform/k8s/argocd-bootstrap`.

## Usage

```bash
hyops apply --env dev \
  --module platform/onprem/argocd-bootstrap \
  --inputs modules/platform/onprem/argocd-bootstrap/examples/inputs.typical.yml
```

## Inputs

- `kubeconfig_path` (required for apply): path to kubeconfig on controller host.
- `install_argocd`: install/upgrade Argo CD manifests before creating root Application.
- `workloads_repo_url`, `workloads_revision`, `workloads_target_path`: root Application source.
- `root_app_*`: root Application metadata/project/namespace contract.

Default workloads repo URL:
- `https://github.com/hybridops-tech/hybridops-workloads.git`

Override `workloads_repo_url` only if you run a fork or private mirror.

`kubeconfig_path` can be imported automatically from `platform/onprem/rke2-cluster` state using `spec.dependencies`.

## Outputs

- `kubeconfig_path`
- `argocd_namespace`
- `root_app_name`
- `workloads_repo_url`
- `workloads_revision`
- `workloads_target_path`
- `cap.gitops.argocd = ready`
