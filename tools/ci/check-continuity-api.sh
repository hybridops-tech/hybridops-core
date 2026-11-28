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
hyops_ci::require_cmd python3

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

resource_snapshot() {
  kubectl get --request-timeout=30s "$1" --output=json
}

status_snapshot() {
  resource_snapshot "$1" | python3 -c \
    'import json,sys; print(json.dumps(json.load(sys.stdin).get("status"), sort_keys=True, separators=(",", ":")))'
}

assert_equal() {
  local label="$1"
  local expected="$2"
  local actual="$3"
  if [[ "${actual}" != "${expected}" ]]; then
    echo "ERR: ${label}: expected '${expected}', got '${actual}'" >&2
    exit 1
  fi
}

expect_admission_rejection() {
  local label="$1"
  local target="$2"
  local expected_message="$3"
  shift 3

  local before after output rc
  before="$(resource_snapshot "${target}")"
  if output="$("$@" 2>&1)"; then
    rc=0
  else
    rc=$?
  fi
  after="$(resource_snapshot "${target}")"

  if (( rc == 0 )); then
    echo "ERR: ${label}: mutation was accepted" >&2
    exit 1
  fi
  if ! grep -Fq -- "${expected_message}" <<<"${output}"; then
    echo "ERR: ${label}: expected admission message was not returned" >&2
    printf '%s\n' "${output}" >&2
    exit 1
  fi
  if [[ "${after}" != "${before}" ]]; then
    echo "ERR: ${label}: resource changed after rejection" >&2
    exit 1
  fi
}

expect_create_rejection() {
  local label="$1"
  local expected_message="$2"
  shift 2

  local output rc
  if output="$("$@" 2>&1)"; then
    rc=0
  else
    rc=$?
  fi
  if (( rc == 0 )); then
    echo "ERR: ${label}: resource was accepted" >&2
    exit 1
  fi
  if ! grep -Fq -- "${expected_message}" <<<"${output}"; then
    echo "ERR: ${label}: expected admission message was not returned" >&2
    printf '%s\n' "${output}" >&2
    exit 1
  fi
  kubectl get --request-timeout=30s --raw=/readyz >/dev/null
}

create_terminal_contract() {
  local name="$1"
  kubectl apply --server-side --validate=strict --filename - <<EOF
apiVersion: continuity.hybridops.tech/v1alpha1
kind: ContinuityContract
metadata:
  name: ${name}
spec:
  workload:
    name: ${name}
    revision: v1
    digest: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  stages:
    - id: prepare
      adapterRef:
        name: conformance
      operation: prepare
EOF
}

exercise_terminal_phase() {
  local target="$1"
  local phase="$2"
  local recovery_sets="$3"
  local name="${target#*/}"
  local evidence_digest="sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
  local terminal_patch
  local terminal_without_evidence

  terminal_without_evidence="$(printf \
    '{"status":{"observedGeneration":1,"phase":"%s","conditions":[],"recoverySets":%s}}' \
    "${phase}" "${recovery_sets}")"
  terminal_patch="$(printf \
    '{"status":{"observedGeneration":1,"phase":"%s","conditions":[],"recoverySets":%s,"terminalEvidenceRef":{"apiGroup":"","kind":"ConfigMap","name":"%s-terminal","digest":"%s"}}}' \
    "${phase}" "${recovery_sets}" "${name}" "${evidence_digest}")"

  kubectl patch --request-timeout=30s "${target}" \
    --subresource=status \
    --type=merge \
    --patch='{"status":{"observedGeneration":1,"phase":"Running","conditions":[],"recoverySets":[]}}' \
    >/dev/null

  expect_admission_rejection \
    "${phase} without terminal evidence" "${target}" \
    "terminal evidence must match the terminal phase" \
    kubectl patch --request-timeout=30s "${target}" \
      --subresource=status --type=merge --patch="${terminal_without_evidence}"

  kubectl patch --request-timeout=30s "${target}" \
    --subresource=status --type=merge --patch="${terminal_patch}" >/dev/null
  assert_equal \
    "${phase} terminal status" \
    "${phase}/${evidence_digest}" \
    "$(kubectl get "${target}" --output=jsonpath='{.status.phase}/{.status.terminalEvidenceRef.digest}')"

  local before_retry after_retry
  before_retry="$(status_snapshot "${target}")"
  kubectl patch --request-timeout=30s "${target}" \
    --subresource=status --type=merge --patch="${terminal_patch}" >/dev/null
  after_retry="$(status_snapshot "${target}")"
  assert_equal "${phase} retry" "${before_retry}" "${after_retry}"

  expect_admission_rejection \
    "${phase} evidence mutation" "${target}" \
    "terminal status is immutable" \
    kubectl patch --request-timeout=30s "${target}" \
      --subresource=status \
      --type=merge \
      --patch='{"status":{"terminalEvidenceRef":{"digest":"sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd"}}}'

  expect_admission_rejection \
    "${phase} unknown status mutation" "${target}" \
    "terminal status is immutable" \
    kubectl patch --request-timeout=30s "${target}" \
      --subresource=status \
      --type=merge \
      --patch='{"status":{"unexpectedStatus":"blocked"}}'

  expect_admission_rejection \
    "${phase} status deletion" "${target}" \
    "terminal status is immutable" \
    kubectl patch --request-timeout=30s "${target}" \
      --subresource=status --type=merge --patch='{"status":null}'
}

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
  authorities:
    - name: release-authority
      capability: release
      provider: conformance
  stages:
    - id: prepare
      adapterRef:
        name: conformance
      operation: prepare
EOF

defaults="$(
  kubectl get continuitycontract/default-policy \
    --output=jsonpath='{.spec.policy.failureAction}/{.spec.policy.unverifiableAction}/{.spec.policy.terminalEvidence}/{.spec.authorities[0].compatibility}'
)"
assert_equal \
  "ContinuityContract fail-closed defaults" \
  "Recover/Block/Required/false" \
  "${defaults}"

kubectl create --validate=strict --filename - <<'EOF'
apiVersion: continuity.hybridops.tech/v1alpha1
kind: ContinuityContract
metadata:
  name: unknown-field
spec:
  workload:
    name: unknown-field
    revision: v1
    digest: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  policy:
    failureActon: Ignore
  stages:
    - id: prepare
      adapterRef:
        name: conformance
      operation: prepare
      authorityReff: release-authority
EOF
unknown_payload="${runtime_root}/unknown-field.json"
kubectl get continuitycontract/unknown-field --output=json >"${unknown_payload}"
PYTHONPATH="${HYOPS_REPO_ROOT}" python3 - "${unknown_payload}" <<'PY'
import json
from pathlib import Path
import sys

from hyops.continuity.api.v1alpha1 import ApiValidationError, decode

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload["spec"]["policy"].get("failureActon") != "Ignore":
    raise SystemExit("unknown policy field was pruned before validation")
if payload["spec"]["stages"][0].get("authorityReff") != "release-authority":
    raise SystemExit("unknown stage field was pruned before validation")
try:
    decode(payload)
except ApiValidationError as exc:
    if exc.reason_code != "UnknownField" or exc.path != "$.spec.stages[0]":
        raise
else:
    raise SystemExit("strict codec accepted a preserved unknown field")
PY

create_terminal_contract "unknown-status" >/dev/null
kubectl patch --request-timeout=30s continuitycontract/unknown-status \
  --subresource=status \
  --type=merge \
  --patch='{"status":{"observedGeneration":1,"phase":"Running","unexpectedStatus":"retained"}}' \
  >/dev/null
unknown_status_payload="${runtime_root}/unknown-status.json"
kubectl get continuitycontract/unknown-status --output=json >"${unknown_status_payload}"
PYTHONPATH="${HYOPS_REPO_ROOT}" python3 - "${unknown_status_payload}" <<'PY'
import json
from pathlib import Path
import sys

from hyops.continuity.api.v1alpha1 import ApiValidationError, decode

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if payload["status"].get("unexpectedStatus") != "retained":
    raise SystemExit("unknown status field was pruned before validation")
try:
    decode(payload)
except ApiValidationError as exc:
    if exc.reason_code != "UnknownField" or exc.path != "$.status":
        raise
else:
    raise SystemExit("strict codec accepted a preserved unknown status field")
PY

expect_create_rejection \
  "self dependency" "a stage cannot depend on itself" \
  kubectl create --request-timeout=30s --validate=false --filename - <<'EOF'
apiVersion: continuity.hybridops.tech/v1alpha1
kind: ContinuityContract
metadata:
  name: self-dependency
spec:
  workload:
    name: self-dependency
    revision: v1
    digest: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  stages:
    - id: prepare
      adapterRef:
        name: conformance
      operation: prepare
      requires:
        - prepare
EOF

kubectl patch --request-timeout=30s "${resource}" \
  --subresource=status \
  --type=merge \
  --patch='{"status":{"observedGeneration":1,"phase":"Running","conditions":[],"recoverySets":[]}}' \
  >/dev/null
assert_equal \
  "running status" "Running/1" \
  "$(kubectl get "${resource}" --output=jsonpath='{.status.phase}/{.status.observedGeneration}')"

expect_admission_rejection \
  "mismatched recovery identity" "${resource}" \
  "status recovery sets must match their declarations" \
  kubectl patch --request-timeout=30s "${resource}" \
    --subresource=status \
    --type=merge \
    --patch='{"status":{"observedGeneration":1,"phase":"Running","conditions":[],"recoverySets":[{"name":"workload-state","evidence":"prepared-state","role":"invalid","digest":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}]}}'

expect_admission_rejection \
  "nonterminal evidence" "${resource}" \
  "terminal evidence must match the terminal phase" \
  kubectl patch --request-timeout=30s "${resource}" \
    --subresource=status \
    --type=merge \
    --patch='{"status":{"terminalEvidenceRef":{"apiGroup":"","kind":"ConfigMap","name":"invalid-terminal","digest":"sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"}}}'

expect_admission_rejection \
  "condition generation" "${resource}" \
  "condition generations cannot exceed status generation" \
  kubectl patch --request-timeout=30s "${resource}" \
    --subresource=status \
    --type=merge \
    --patch='{"status":{"conditions":[{"type":"Ready","status":"False","observedGeneration":2,"lastTransitionTime":"2026-11-28T10:15:30Z","reason":"Pending","message":"pending"}]}}'

expect_admission_rejection \
  "incomplete successful status" "${resource}" \
  "successful status requires every declared recovery set" \
  kubectl patch --request-timeout=30s "${resource}" \
    --subresource=status \
    --type=merge \
    --patch='{"status":{"observedGeneration":1,"phase":"Succeeded","conditions":[],"recoverySets":[],"terminalEvidenceRef":{"apiGroup":"","kind":"ConfigMap","name":"conformance-workload-terminal","digest":"sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"}}}'

expect_admission_rejection \
  "zero terminal generation" "${resource}" \
  "terminal status requires a positive observed generation" \
  kubectl patch --request-timeout=30s "${resource}" \
    --subresource=status \
    --type=merge \
    --patch='{"status":{"observedGeneration":0,"phase":"Succeeded","conditions":[],"recoverySets":[{"name":"workload-state","evidence":"prepared-state","role":"recovery","digest":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}],"terminalEvidenceRef":{"apiGroup":"","kind":"ConfigMap","name":"conformance-workload-terminal","digest":"sha256:cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"}}}'

succeeded_recovery='[{"name":"workload-state","evidence":"prepared-state","role":"recovery","digest":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}]'
exercise_terminal_phase "${resource}" "Succeeded" "${succeeded_recovery}"
assert_equal \
  "successful recovery identity" \
  "workload-state/prepared-state/recovery" \
  "$(kubectl get "${resource}" --output=jsonpath='{.status.recoverySets[0].name}/{.status.recoverySets[0].evidence}/{.status.recoverySets[0].role}')"

expect_admission_rejection \
  "spec mutation" "${resource}" "spec is immutable" \
  kubectl patch --request-timeout=30s "${resource}" \
    --type=merge --patch='{"spec":{"workload":{"revision":"v2.0.0"}}}'

expect_admission_rejection \
  "unknown spec mutation" "${resource}" "spec is immutable" \
  kubectl patch --request-timeout=30s "${resource}" \
    --type=merge --patch='{"spec":{"unexpectedSpec":"blocked"}}'

for phase in Recovered Failed; do
  name="terminal-${phase,,}"
  create_terminal_contract "${name}" >/dev/null
  exercise_terminal_phase "continuitycontract/${name}" "${phase}" '[]'
done

kubectl get --request-timeout=30s --raw=/readyz >/dev/null
