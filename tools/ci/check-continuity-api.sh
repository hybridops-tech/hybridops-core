#!/usr/bin/env bash
# purpose: Validate the ContinuityContract API against a Kubernetes API server.
# adr: ADR-N/A
# maintainer: HybridOps.Tech

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "${SCRIPT_DIR}/lib/common.sh"

hyops_ci::require_cmd docker
hyops_ci::require_cmd kind
hyops_ci::require_cmd kubectl

kind version | grep -Fq "kind v${KIND_VERSION} " || {
  echo "ERR: kind v${KIND_VERSION} is required" >&2
  exit 2
}
[[ "${KIND_NODE_IMAGE}" =~ ^[^[:space:]]+@sha256:[0-9a-f]{64}$ ]] || {
  echo "ERR: KIND_NODE_IMAGE must be digest-pinned" >&2
  exit 2
}

cluster_name="hyops-continuity-api-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-0}-$$"
runtime_root="$(mktemp -d)"
export KUBECONFIG="${runtime_root}/kubeconfig"

cleanup() {
  local rc=$?
  trap - EXIT
  if ! kind delete cluster --name "${cluster_name}" >/dev/null 2>&1; then
    echo "ERR: failed to remove kind cluster: ${cluster_name}" >&2
    if (( rc == 0 )); then
      rc=1
    fi
  fi
  rm -rf "${runtime_root}"
  exit "${rc}"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

kind create cluster \
  --name "${cluster_name}" \
  --image "${KIND_NODE_IMAGE}" \
  --kubeconfig "${KUBECONFIG}" \
  --wait 180s

crd="${HYOPS_REPO_ROOT}/config/crd/bases/continuity.hybridops.tech_continuitycontracts.yaml"
sample="${HYOPS_REPO_ROOT}/config/samples/continuity_v1alpha1_contract.yaml"
resource="continuitycontract/conformance-workload"

kubectl apply --server-side --validate=strict --filename "${crd}"
kubectl wait \
  --for=condition=Established \
  --timeout=90s \
  customresourcedefinition/continuitycontracts.continuity.hybridops.tech
kubectl apply --server-side --validate=strict --filename "${sample}"

kubectl apply --server-side --validate=strict --filename - <<'EOF'
apiVersion: continuity.hybridops.tech/v1alpha1
kind: ContinuityContract
metadata:
  name: default-policy
spec:
  workload:
    name: default-policy
    revision: v1
    digest: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  stages:
    - id: prepare
      adapterRef:
        name: conformance
      operation: prepare
EOF

policy="$(
  kubectl get continuitycontract/default-policy \
    --output=jsonpath='{.spec.policy.failureAction}/{.spec.policy.unverifiableAction}/{.spec.policy.terminalEvidence}'
)"
[[ "${policy}" == "Recover/Block/Required" ]] || {
  echo "ERR: ContinuityContract policy defaults are not fail-closed" >&2
  exit 1
}

kubectl patch "${resource}" \
  --subresource=status \
  --type=merge \
  --patch='{"status":{"observedGeneration":1,"phase":"Running","conditions":[],"recoverySets":[]}}'

if kubectl patch "${resource}" \
  --subresource=status \
  --type=merge \
  --patch='{"status":{"observedGeneration":1,"phase":"Running","conditions":[],"recoverySets":[{"name":"workload-state","evidence":"prepared-state","role":"invalid","digest":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}]}}' >/dev/null 2>&1; then
  echo "ERR: status accepted a recovery identity that does not match spec" >&2
  exit 1
fi

terminal_status='{"status":{"observedGeneration":1,"phase":"Succeeded","conditions":[],"recoverySets":[{"name":"workload-state","evidence":"prepared-state","role":"recovery","digest":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}]}}'
if kubectl patch "${resource}" \
  --subresource=status \
  --type=merge \
  --patch="${terminal_status}" >/dev/null 2>&1; then
  echo "ERR: terminal status without evidence was accepted" >&2
  exit 1
fi

if kubectl patch "${resource}" \
  --subresource=status \
  --type=merge \
  --patch='{"status":{"observedGeneration":1,"phase":"Succeeded","conditions":[],"recoverySets":[],"terminalEvidenceRef":{"apiGroup":"","kind":"ConfigMap","name":"conformance-workload-terminal","digest":"sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"}}}' >/dev/null 2>&1; then
  echo "ERR: successful status omitted a declared recovery identity" >&2
  exit 1
fi

kubectl patch "${resource}" \
  --subresource=status \
  --type=merge \
  --patch='{"status":{"observedGeneration":1,"phase":"Succeeded","conditions":[],"recoverySets":[{"name":"workload-state","evidence":"prepared-state","role":"recovery","digest":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}],"terminalEvidenceRef":{"apiGroup":"","kind":"ConfigMap","name":"conformance-workload-terminal","digest":"sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"}}}'

if kubectl patch "${resource}" \
  --subresource=status \
  --type=merge \
  --patch='{"status":{"terminalEvidenceRef":{"digest":"sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"}}}' >/dev/null 2>&1; then
  echo "ERR: terminal evidence was changed after completion" >&2
  exit 1
fi

if kubectl patch "${resource}" \
  --type=merge \
  --patch='{"spec":{"workload":{"revision":"v2.0.0"}}}' >/dev/null 2>&1; then
  echo "ERR: immutable ContinuityContract spec was changed" >&2
  exit 1
fi
