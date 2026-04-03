# platform/k8s/gsm-bootstrap

Provisions the `gsm-sa-credentials` Kubernetes secret required by External Secrets Operator to authenticate against GCP Secret Manager.

The GCP Service Account key JSON is read from the HybridOps bootstrap vault (`HYOPS_GSM_SA_KEY_JSON`) and applied to the cluster via controller-local `kubectl` operations — the same execution pattern used by `platform/k8s/argocd-bootstrap`. The secret value never touches the workloads repository.

## Usage

```bash
hyops apply --env dev \
  --module platform/k8s/gsm-bootstrap \
  --inputs modules/platform/k8s/gsm-bootstrap/examples/inputs.typical.yml
```

In the `onprem/rke2-workloads@v1` blueprint, this module runs as the final step after `platform/k8s/argocd-bootstrap`. The `kubeconfig_path` is imported automatically from that step's outputs.

## Pre-requisites

`HYOPS_GSM_SA_KEY_JSON` must be present in the bootstrap vault before running this module:

```bash
hyops secrets set --env dev HYOPS_GSM_SA_KEY_JSON "$(cat /path/to/gcp-sa-key.json)"
```

The GCP Service Account requires the `roles/secretmanager.secretAccessor` role on the target project. The secret itself is not stored in GCP Secret Manager — it is the root credential that enables ESO to read from it.

## Inputs

- `kubeconfig_path`: path to kubeconfig on the controller host. Automatically imported from `platform/k8s/argocd-bootstrap` state when used within the blueprint.
- `eso_namespace`: namespace where External Secrets Operator runs (default: `external-secrets`).
- `secret_name`: name of the Kubernetes secret to create (default: `gsm-sa-credentials`).
- `secret_key`: key within the secret (default: `credentials.json`).
- `gsm_sa_key_json_env`: name of the bootstrap vault env key holding the GCP SA JSON (default: `HYOPS_GSM_SA_KEY_JSON`).

## Behaviour

The module is fully idempotent. It:

1. Resolves the kubeconfig path (falls back to `<runtime>/state/kubeconfigs/rke2.yaml`).
2. Reads the SA key JSON from the bootstrap vault via `lookup('env', ...)`.
3. Writes the JSON to a `0600` temp file in the runtime state directory to avoid shell quoting issues with arbitrary JSON content.
4. Creates the `external-secrets` namespace if absent (using `--dry-run=client | apply`).
5. Applies the secret idempotently (using `create --dry-run=client -o yaml | apply`).
6. Removes the temp file unconditionally on completion.

## Outputs

- `secret_name`
- `eso_namespace`
- `cap.k8s.gsm-bootstrap = ready`

## References

- [ADR-0504 – ESO with GCP Secret Manager for On-Prem Platform Workloads](https://docs.hybridops.tech/adr/ADR-0504-eso-gcp-secret-manager-on-prem/)
- [Runbook – Deploy RKE2 + Workloads (HybridOps Blueprint)](https://docs.hybridops.tech/ops/runbooks/platform/blueprints/hyops-blueprint-rke2-workloads/)
