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

cluster_name="hyops-api-$(python3 -c 'from uuid import uuid4; print(uuid4().hex[:24])')"
runtime_root="$(mktemp -d)"
export KUBECONFIG="${runtime_root}/kubeconfig"
cluster_state=unstarted
original_ca=""
proxy_pid=""

cluster_ca() {
  kubectl config view --kubeconfig="$1" --raw --minify \
    --output=jsonpath='{.clusters[0].cluster.certificate-authority-data}'
}

cleanup() {
  local rc=$? clusters current
  trap - EXIT
  if [[ -n "${proxy_pid}" ]]; then
    kill "${proxy_pid}" 2>/dev/null || :
    wait "${proxy_pid}" 2>/dev/null || :
  fi
  if [[ "${cluster_state}" == created ]]; then
    if [[ -z "${original_ca}" ]] ||
      ! current="$(kind get kubeconfig --name "${cluster_name}" | cluster_ca /dev/stdin)" ||
      [[ "${current}" != "${original_ca}" ]]; then
      echo "ERR: cannot confirm ownership of kind cluster: ${cluster_name}; not deleting" >&2
      rc=1
    elif ! kind delete cluster --name "${cluster_name}"; then
      echo "ERR: failed to remove kind cluster: ${cluster_name}" >&2
      rc=1
    fi
  elif [[ "${cluster_state}" == creating ]]; then
    # kind rolls back failed creates; a remaining name does not establish ownership.
    if ! clusters="$(kind get clusters)" || grep -Fxq -- "${cluster_name}" <<<"${clusters}"; then
      echo "ERR: check kind cluster after failed create: ${cluster_name}; not deleting" >&2
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
apiVersion: continuity.hyopsproject.github.io/v1alpha1
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

exercise_spec_order_and_aliases() {
  local name target path patch good
  # A single 64-character component is a valid Kubernetes resource name.
  name="$(printf 'a%.0s' {1..64})"
  target="continuitycontract/${name}"
  kubectl create --validate=strict --filename - <<EOF
apiVersion: continuity.hyopsproject.github.io/v1alpha1
kind: ContinuityContract
metadata:
  name: ${name}
spec:
  workload:
    name: test
    revision: v1
    digest: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    ref: {kind: ConfigMap, name: ${name}}
  authorities:
    - {name: first, capability: release, provider: test}
    - {name: second, capability: release, provider: test}
  recoverySets:
    - {name: first, producer: {stage: prepare, evidence: state, role: recovery}}
    - {name: archive, producer: {stage: prepare, evidence: archived, role: recovery}}
    - {name: independent, producer: {stage: copy, evidence: state, role: archive}}
  stages:
    - id: prepare
      adapterRef: {name: test}
      operation: prepare
      publish: [one, two]
    - id: copy
      adapterRef: {name: test}
      operation: copy
      requires: [prepare]
      recoverySets: [first]
    - id: finish
      adapterRef: {name: test}
      operation: finish
      requires: [prepare, copy]
      inputBindings:
        - {name: a, stage: prepare, output: one}
        - {name: b, stage: prepare, output: two}
      recoverySets: [first, archive]
EOF

  resource_snapshot "${target}" | python3 -c '
import json, sys
p = json.load(sys.stdin)
p["metadata"] = {"name": "alias-conflict"}
p["spec"]["recoverySets"][1]["producer"]["evidence"] = "state"
p["spec"]["recoverySets"][1]["producer"]["role"] = "another"
json.dump(p, sys.stdout)' | expect_create_rejection \
    "aliases with conflicting roles" "a producer stage and evidence name must identify one recovery set" \
    kubectl create --request-timeout=30s --validate=false --filename -

  # Exercise the advertised collection and token bounds against the CEL runtime budget.
  resource_snapshot "${target}" | python3 -c '
import json, sys
p = json.load(sys.stdin)
p["metadata"] = {"name": "bounded-producers"}
producer = "p" * 64
p["spec"]["recoverySets"] = [
    {"name": f"{i:r>64}", "producer": {"stage": producer, "evidence": f"{i:e>64}", "role": "r"*64}}
    for i in range(256)]
stage = {"adapterRef": {"name": "test"}, "operation": "test"}
p["spec"]["stages"] = [
    {**stage, "id": producer}, {**stage, "id": "observe", "requires": [producer]},
    {**stage, "id": "release", "destructive": True, "requires": ["observe"],
     "authorityRef": "first", "recoverySets": [r["name"] for r in p["spec"]["recoverySets"]]}]
json.dump(p, sys.stdout)' | kubectl create --validate=strict --filename - >/dev/null
  resource_snapshot continuitycontract/bounded-producers | python3 -c '
import json, sys
p = json.load(sys.stdin)
digest = "sha256:" + "a" * 64
status = {"observedGeneration": p["metadata"]["generation"], "phase": "Succeeded",
          "terminalEvidenceRef": {"kind": "ConfigMap", "name": "bounded-evidence", "digest": digest},
          "recoverySets": [
              {"name": r["name"], "evidence": r["producer"]["evidence"],
               "role": r["producer"]["role"], "digest": digest}
              for r in reversed(p["spec"]["recoverySets"])]}
json.dump({"status": status}, sys.stdout)' | kubectl patch continuitycontract/bounded-producers \
    --subresource=status --type=merge --patch-file=/dev/stdin >/dev/null
  resource_snapshot continuitycontract/bounded-producers | PYTHONPATH="${HYOPS_REPO_ROOT}" python3 -c '
import json, sys
from hyops.continuity.api.v1alpha1 import decode
status = decode(json.load(sys.stdin)).status
if status.phase != "Succeeded" or len(status.recovery_sets) != 256:
    raise SystemExit("complete maximum-size terminal status did not persist")'

  good='[{"name":"first","evidence":"state","role":"recovery","digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},{"name":"archive","evidence":"archived","role":"recovery","digest":"sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},{"name":"independent","evidence":"state","role":"archive","digest":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}]'
  exercise_terminal_phase "${target}" "Succeeded" "${good}"
  resource_snapshot "${target}" | python3 -c '
import json, sys
p = json.load(sys.stdin)
p["spec"]["stages"].reverse()
json.dump(p, sys.stdout)' | expect_admission_rejection \
    "replace terminal object with reordered stages" "${target}" "spec list order is immutable" \
    kubectl replace --request-timeout=30s --filename -
  for path in /spec/authorities /spec/recoverySets \
    /spec/stages/0/publish /spec/stages/2/requires \
    /spec/stages/2/inputBindings /spec/stages/2/recoverySets; do
    patch="$(printf '[{"op":"move","from":"%s/0","path":"%s/1"}]' "${path}" "${path}")"
    expect_admission_rejection \
      "reorder ${path}" "${target}" "spec list order is immutable" \
      kubectl patch --request-timeout=30s "${target}" --type=json --patch="${patch}"
  done
  kubectl patch "${target}" --type=merge --patch='{"unknownRoot":"ignored"}' >/dev/null
  kubectl annotate "${target}" verified=yes >/dev/null
  resource_snapshot "${target}" | PYTHONPATH="${HYOPS_REPO_ROOT}" python3 -c '
import json, sys
from hyops.continuity.api.v1alpha1 import decode
p = json.load(sys.stdin)
r = decode(p)
if ("unknownRoot" in p or p["metadata"]["annotations"].get("verified") != "yes" or
    r.status.phase != "Succeeded" or r.status.observed_generation != r.metadata.generation or
    r.metadata.generation != 1):
    raise SystemExit("persisted terminal contract became stale or invalid")'
}

clusters="$(kind get clusters)"
if grep -Fxq -- "${cluster_name}" <<<"${clusters}"; then
  echo "ERR: kind cluster already exists: ${cluster_name}" >&2
  exit 1
fi
cluster_state=creating
kind create cluster \
  --name "${cluster_name}" \
  --image "${KIND_NODE_IMAGE}" \
  --kubeconfig "${KUBECONFIG}" \
  --wait 180s
cluster_state=created
original_ca="$(cluster_ca "${KUBECONFIG}")"
[[ -n "${original_ca}" ]] || exit 1

crd="${HYOPS_REPO_ROOT}/config/crd/bases/continuity.hyopsproject.github.io_continuitycontracts.yaml"
sample="${HYOPS_REPO_ROOT}/config/samples/continuity_v1alpha1_contract.yaml"
resource="continuitycontract/conformance-workload"

kubectl apply --server-side --validate=strict --filename "${crd}"
kubectl wait \
  --for=condition=Established \
  --timeout=90s \
  customresourcedefinition/continuitycontracts.continuity.hyopsproject.github.io

reject_sample_patch() {
  local change="$1" diagnostic="$2"
  kubectl patch --local --filename "${sample}" --type=json --patch="${change}" --output=json |
    expect_create_rejection "${change}" "${diagnostic}" \
      kubectl create --request-timeout=30s --dry-run=server --validate=false --filename -
}

reject_sample_patch '[{"op":"remove","path":"/spec/stages/1/authorityRef"}]' \
  "a destructive stage requires a declared authority"
reject_sample_patch '[{"op":"remove","path":"/spec/stages/1/recoverySets"}]' \
  "a destructive stage requires a recovery set"
reject_sample_patch '[{"op":"replace","path":"/spec/stages/1/authorityRef","value":"unknown"}]' \
  "a destructive stage requires a declared authority"
reject_sample_patch '[{"op":"replace","path":"/spec/recoverySets/0/producer/stage","value":"release"}]' \
  "destructive recovery sets must be declared and produced by another stage"
reject_sample_patch '[{"op":"replace","path":"/spec/stages/1/destructive","value":null}]' \
  "destructive must be a boolean"

kubectl apply --server-side --validate=strict --filename "${sample}"
assert_equal "release declares destructive intent" "true" \
  "$(kubectl get "${resource}" --output=jsonpath='{.spec.stages[?(@.id=="release")].destructive}')"

kubectl apply --server-side --validate=strict --filename - <<'EOF'
apiVersion: continuity.hyopsproject.github.io/v1alpha1
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
    --output=jsonpath='{.spec.policy.failureAction}/{.spec.policy.unverifiableAction}/{.spec.policy.terminalEvidence}/{.spec.authorities[0].compatibility}/{.spec.stages[0].destructive}'
)"
assert_equal \
  "ContinuityContract fail-closed defaults" \
  "Recover/Block/Required/false/false" \
  "${defaults}"

kubectl create --validate=strict --filename - <<'EOF'
apiVersion: continuity.hyopsproject.github.io/v1alpha1
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
  recoverySets:
    - name: retained
      producer: {stage: archive, evidence: snapshot, role: recovery}
    - name: unclaimed
      producer: {stage: prepare, evidence: report, role: inspection}
  stages:
    - id: prepare
      adapterRef:
        name: conformance
      operation: prepare
      authorityReff: release-authority
    - id: archive
      adapterRef: {name: conformance}
      operation: archive
EOF
kubectl patch --request-timeout=30s continuitycontract/unknown-field \
  --subresource=status --type=merge \
  --patch='{"status":{"observedGeneration":1,"recoverySets":[{"name":"retained","evidence":"snapshot","role":"recovery","digest":"sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}]}}' \
  >/dev/null
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
apiVersion: continuity.hyopsproject.github.io/v1alpha1
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

exercise_spec_order_and_aliases

kubectl get --request-timeout=30s --raw=/readyz >/dev/null

run_proxy_test() {
  local script="$1" paths="$2" reject_methods="$3" proxy_address
  coproc TEST_PROXY {
    exec kubectl proxy --address=127.0.0.1 --port=0 --accept-paths="${paths}" --reject-methods="${reject_methods}"
  }
  proxy_pid=${TEST_PROXY_PID}
  if ! IFS= read -r -t 10 proxy_address <&"${TEST_PROXY[0]}" ||
    [[ ! "${proxy_address}" =~ ^Starting\ to\ serve\ on\ 127\.0\.0\.1:([0-9]+)$ ]]; then
    echo "ERR: ${script} proxy did not announce a loopback port" >&2
    exit 1
  fi
  HYOPS_TEST_PROXY_PORT="${BASH_REMATCH[1]}" PYTHONPATH="${HYOPS_REPO_ROOT}" \
    python3 "${SCRIPT_DIR}/tests/${script}"
  kill "${proxy_pid}"
  wait "${proxy_pid}" || :
  proxy_pid=""
}

contracts='/apis/continuity\.hyopsproject\.github\.io/v1alpha1/namespaces/default/continuitycontracts'
run_proxy_test check-continuity-reconciliation.py \
  "^${contracts}/(default-policy|unknown-field)(/status)?$" 'POST,PATCH,DELETE'

kubectl create namespace reference-records
kubectl patch --local --filename "${sample}" --type=merge \
  --patch='{"metadata":{"name":"reference-operation"}}' --output=json |
  kubectl create --namespace=default --validate=strict --filename -
sources='/api/v1/namespaces/default/(configmaps/(conformance-workload|prepare-parameters)|secrets/release-authority)'
records='/api/v1/namespaces/reference-records/configmaps(/binding-[a-f0-9]{32}\.[a-f0-9]{32})?'
run_proxy_test check-continuity-references.py \
  "^(${contracts}/reference-operation|${sources}|${records})$" 'PUT,PATCH,DELETE,CONNECT,HEAD,OPTIONS,TRACE'

kubectl create namespace dispatch-records
records='/api/v1/namespaces/dispatch-records/configmaps(/(binding-[a-f0-9]{32}\.[a-f0-9]{32}|dispatch-[a-f0-9]{54}))?'
run_proxy_test check-continuity-dispatch.py \
  "^(${contracts}/dispatch-(complete|competing|corrupt|replaced|interrupted)|${records})$" 'PUT,DELETE,CONNECT,HEAD,OPTIONS,TRACE'

kubectl create namespace terminal-labs
kubectl create namespace terminal-records
contracts='/apis/continuity\.hyopsproject\.github\.io/v1alpha1/namespaces/terminal-labs/continuitycontracts'
records='/api/v1/namespaces/terminal-records/configmaps(/(binding-[a-f0-9]{32}\.[a-f0-9]{32}|(terminal|dispatch)-[a-f0-9]{54}))?'
evidence='/api/v1/namespaces/terminal-labs/configmaps(/terminal-[a-f0-9]{54})?'
run_proxy_test check-continuity-terminal.py \
  "^(${contracts}/terminal-(complete|uncertain|evidence|witness|claims|recovered|restart|unpinned)(/status)?|${records}|${evidence})$" 'DELETE,CONNECT,HEAD,OPTIONS,TRACE'
