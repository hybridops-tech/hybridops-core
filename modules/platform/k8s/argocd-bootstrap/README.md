# platform/k8s/argocd-bootstrap

Bootstraps Argo CD on an existing Kubernetes cluster and applies a root workloads Application.

This module can be used for on prem, burst, and DR Kubernetes clusters.

## Usage

```bash
hyops apply --env dev \
  --module platform/k8s/argocd-bootstrap \
  --inputs modules/platform/k8s/argocd-bootstrap/examples/inputs.typical.yml
```

## Inputs

- `kubeconfig_path` (required for apply unless imported from state): path to kubeconfig on the controller host.
- `kubeconfig_state_ref`: optional state ref when a cluster module already publishes the kubeconfig.
- `install_argocd`: install/upgrade Argo CD manifests before creating root Application.
  - HyOps applies the upstream install manifest using Kubernetes server-side apply
    to avoid large CRD `metadata.annotations` limits on newer Argo CD manifests.
- `argocd_install_force_conflicts`: force server-side apply conflicts during Argo CD
  install/upgrade (default `true`) so reruns can converge after partial client-side applies.
- `workloads_repo_url`, `workloads_revision`, `workloads_target_path`: root Application source.
- `repo_access_mode`: `public` or `ssh`.
- `workloads_repo_url` should match the selected mode:
  - `public` uses an HTTPS repository URL
  - `ssh` uses `git@...` or `ssh://...`
- `repo_secret_name`: Argo CD repository secret name when `repo_access_mode=ssh`.
- `repo_ssh_private_key_env`: env key used to read the SSH deploy key from the controller.
- `repo_ssh_known_hosts`: optional SSH known-hosts block for strict host verification.
- `root_app_*`: root Application metadata/project/namespace contract.
- `load_vault_env`: defaults to `true` so vault-backed env keys can be resolved safely.

Default workloads repo URL:
- `https://github.com/hybridops-tech/hybridops-workloads.git`

Use the public workloads repo for customer and baseline deployments.

There is no hidden kubeconfig fallback in this module. For a clean run, provide
`kubeconfig_path` directly or let HyOps import it from cluster state through
`kubeconfig_state_ref` or a module dependency.

Override `workloads_repo_url` when you intentionally consume a private workloads
repository or a managed authoring repository. The Argo CD contract stays the same:
- public/exported workloads repo: `workloads_target_path = clusters/<target>`
- private/managed workloads repo: `workloads_target_path = <repo-defined managed target path>`

Promotion boundary:
- keep this module generic
- let the selected workloads repository define application composition
- do not encode business-specific target names or app lanes into public Core contracts

Private repo mode should use SSH deploy keys rather than embedding repo
credentials in module inputs. Set:
- `repo_access_mode = ssh`
- `workloads_repo_url = git@github.com:<org>/<repo>.git`
- `repo_ssh_private_key_env = <vault-backed env key>`

The private key is read from the controller environment using `lookup('env', ...)`.
Because `load_vault_env` defaults to `true`, the common path is:
1. store the deploy key in the runtime vault
2. persist it to GSM if needed
3. let the module resolve it from vault-backed env during apply

If an instance is moved back to `repo_access_mode = public`, HyOps removes the
managed Argo CD repository secret referenced by the current `repo_secret_name`
when that secret was previously created by the same module instance. That keeps
the instance from leaving a stale private-repo registration behind without
blindly deleting unrelated repository secrets.

`workloads_target_path` should map to your cluster target in `hybridops-workloads`, e.g.:
- `clusters/onprem`
- `clusters/onprem-stage1`
- `clusters/onprem-smoke`
- `clusters/burst`
- `clusters/<published-target>`

The shipped public examples use the published workloads repo and a public
`clusters/<target>` path.

The bundled DR example currently points at `clusters/burst` because the public
workloads repo does not yet publish a dedicated `clusters/dr` target.

If you consume a private or managed workloads repository, point `workloads_target_path`
at the managed target defined by that repository.

## Outputs

- `kubeconfig_path`
- `argocd_namespace`
- `root_app_name`
- `workloads_repo_url`
- `workloads_revision`
- `workloads_target_path`
- `repo_access_mode`
- `repo_secret_name`
- `cap.gitops.argocd = ready`
