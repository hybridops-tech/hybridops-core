"""Codec and semantic validation for continuity.hyopsproject.github.io/v1alpha1."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from ..json_values import thaw_json
from ..validation import is_sha256_digest, is_token
from .models import (
    API_GROUP,
    API_KIND,
    ApiCondition,
    ApiPolicy,
    ApiResource,
    ApiSpec,
    ApiStage,
    ApiStatus,
    ApiWorkload,
    AuthoritySpec,
    InputBindingSpec,
    LocalObjectReference,
    ObjectMeta,
    RecoverySetIdentity,
    RecoverySetSpec,
    TerminalEvidenceReference,
)

API_VERSION = "v1alpha1"
API_VERSION_VALUE = f"{API_GROUP}/{API_VERSION}"

_DNS_LABEL_RE = re.compile(r"^[a-z0-9](?:[-a-z0-9]*[a-z0-9])?$")
_DNS_SUBDOMAIN_RE = re.compile(
    r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*$"
)
_KIND_RE = re.compile(r"^[A-Z][A-Za-z0-9]{0,62}$")
_CONDITION_TYPE_RE = re.compile(
    r"^([a-z0-9]([-a-z0-9]*[a-z0-9])?"
    r"(\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*/)?"
    r"(([A-Z]([a-z0-9A-Z]*[a-z0-9])?)|"
    r"([a-z0-9]([a-z0-9A-Z]*[a-z0-9])?))$"
)
_CONDITION_REASON_RE = re.compile(r"^[A-Za-z]([A-Za-z0-9_,:]*[A-Za-z0-9_])?$")
_RFC3339_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d{1,9})?(?:Z|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])$"
)

_TYPED_METADATA_KEYS = frozenset({"name", "namespace", "uid", "generation"})
_MAX_GENERATION = (1 << 63) - 1
_MAX_AUTHORITIES = 64
_MAX_CONDITIONS = 32
_MAX_CONDITION_MESSAGE_LENGTH = 32768
_MAX_CONDITION_REASON_LENGTH = 1024
_MAX_CONDITION_TYPE_LENGTH = 316
_MAX_DNS_SUBDOMAIN_LENGTH = 253
_MAX_INPUT_BINDINGS = 256
_MAX_RECOVERY_SETS = 256
_MAX_STAGE_ITEMS = 256
_MAX_STAGES = 128
_MAX_WORKLOAD_NAME_LENGTH = 253
_MAX_WORKLOAD_REVISION_LENGTH = 256

_POLICY_FAILURE_ACTIONS = frozenset({"Recover"})
_POLICY_UNVERIFIABLE_ACTIONS = frozenset({"Block"})
_POLICY_TERMINAL_EVIDENCE = frozenset({"Required"})
_CONDITION_STATUSES = frozenset({"True", "False", "Unknown"})
_PHASES = frozenset(
    {
        "Pending",
        "Admitted",
        "Running",
        "Recovering",
        "Succeeded",
        "Recovered",
        "Failed",
    }
)
_TERMINAL_PHASES = frozenset({"Succeeded", "Recovered", "Failed"})


class ApiValidationError(ValueError):
    """Stable validation failure for one versioned API field."""

    def __init__(self, reason_code: str, path: str, message: str) -> None:
        super().__init__(f"{path}: {message}")
        self.reason_code = reason_code
        self.path = path


def decode(payload: Mapping[str, Any]) -> ApiResource:
    """Decode and validate one v1alpha1 ContinuityContract resource."""

    root = _mapping(payload, "$")
    _known_keys(root, {"apiVersion", "kind", "metadata", "spec", "status"}, "$")
    api_version = _text(root.get("apiVersion"), "$.apiVersion")
    kind = _text(root.get("kind"), "$.kind")
    if api_version != API_VERSION_VALUE:
        _fail("UnsupportedAPIVersion", "$.apiVersion", "unsupported API version")
    if kind != API_KIND:
        _fail("InvalidKind", "$.kind", "unsupported resource kind")

    resource = ApiResource(
        metadata=_decode_metadata(root.get("metadata")),
        spec=_decode_spec(root.get("spec")),
        status=(
            _decode_status(root["status"]) if root.get("status") is not None else None
        ),
    )
    _validate_semantics(resource)
    return resource


def encode(resource: ApiResource) -> dict[str, Any]:
    """Encode a validated API value without discarding Kubernetes metadata."""

    if not isinstance(resource, ApiResource):
        _fail("InvalidResource", "$", "resource has an invalid type")
    try:
        payload = _encode_resource(resource)
    except ApiValidationError:
        raise
    except (AttributeError, TypeError, ValueError):
        _fail("InvalidResource", "$", "resource contains invalid values")
    decode(payload)
    for key in ("uid", "generation"):
        if not payload["metadata"][key]:
            del payload["metadata"][key]
    return payload


def _encode_resource(resource: ApiResource) -> dict[str, Any]:
    metadata = thaw_json(resource.metadata.extra)
    if not _TYPED_METADATA_KEYS.isdisjoint(metadata):
        _fail("InvalidMetadata", "$.metadata", "extra metadata contains a typed field")
    metadata.update(
        name=resource.metadata.name,
        namespace=resource.metadata.namespace,
        uid=resource.metadata.uid,
        generation=resource.metadata.generation,
    )

    payload: dict[str, Any] = {
        "apiVersion": API_VERSION_VALUE,
        "kind": API_KIND,
        "metadata": metadata,
        "spec": _encode_spec(resource.spec),
    }
    if resource.status is not None:
        payload["status"] = _encode_status(resource.status)
    return payload


def _decode_metadata(value: object) -> ObjectMeta:
    metadata = _mapping(value, "$.metadata")
    name = _dns_subdomain(metadata.get("name"), "$.metadata.name")
    namespace = _dns_label(
        metadata.get("namespace", "default"),
        "$.metadata.namespace",
    )
    uid = metadata.get("uid", "")
    if not isinstance(uid, str):
        _fail("InvalidMetadata", "$.metadata.uid", "must be a string")
    generation = _nonnegative_integer(
        metadata.get("generation", 0),
        "$.metadata.generation",
    )
    extra = {
        key: item for key, item in metadata.items() if key not in _TYPED_METADATA_KEYS
    }
    try:
        return ObjectMeta(
            name=name,
            namespace=namespace,
            uid=uid,
            generation=generation,
            extra=extra,
        )
    except (TypeError, ValueError) as exc:
        _fail("InvalidMetadata", "$.metadata", str(exc))


def _decode_spec(value: object) -> ApiSpec:
    spec = _mapping(value, "$.spec")
    _known_keys(
        spec,
        {"workload", "policy", "authorities", "recoverySets", "stages"},
        "$.spec",
    )
    stages = tuple(
        _decode_stage(item, f"$.spec.stages[{index}]")
        for index, item in enumerate(
            _list(spec.get("stages"), "$.spec.stages", _MAX_STAGES)
        )
    )
    if not stages:
        _fail("EmptyContract", "$.spec.stages", "must contain at least one stage")
    return ApiSpec(
        workload=_decode_workload(spec.get("workload")),
        policy=_decode_policy(spec.get("policy", {})),
        authorities=tuple(
            _decode_authority(item, f"$.spec.authorities[{index}]")
            for index, item in enumerate(
                _list(
                    spec.get("authorities", []),
                    "$.spec.authorities",
                    _MAX_AUTHORITIES,
                )
            )
        ),
        recovery_sets=tuple(
            _decode_recovery_set(item, f"$.spec.recoverySets[{index}]")
            for index, item in enumerate(
                _list(
                    spec.get("recoverySets", []),
                    "$.spec.recoverySets",
                    _MAX_RECOVERY_SETS,
                )
            )
        ),
        stages=stages,
    )


def _decode_workload(value: object) -> ApiWorkload:
    workload = _mapping(value, "$.spec.workload")
    _known_keys(workload, {"name", "revision", "digest", "ref"}, "$.spec.workload")
    digest = _text(workload.get("digest"), "$.spec.workload.digest")
    if not is_sha256_digest(digest):
        _fail("InvalidDigest", "$.spec.workload.digest", "must be a SHA-256 digest")
    return ApiWorkload(
        name=_bounded_nonempty_text(
            workload.get("name"),
            "$.spec.workload.name",
            _MAX_WORKLOAD_NAME_LENGTH,
        ),
        revision=_bounded_nonempty_text(
            workload.get("revision"),
            "$.spec.workload.revision",
            _MAX_WORKLOAD_REVISION_LENGTH,
        ),
        digest=digest,
        ref=(
            _decode_reference(workload["ref"], "$.spec.workload.ref")
            if workload.get("ref") is not None
            else None
        ),
    )


def _decode_policy(value: object) -> ApiPolicy:
    policy = _mapping(value, "$.spec.policy")
    _known_keys(
        policy,
        {"failureAction", "unverifiableAction", "terminalEvidence"},
        "$.spec.policy",
    )
    return ApiPolicy(
        failure_action=_enum(
            policy.get("failureAction", "Recover"),
            _POLICY_FAILURE_ACTIONS,
            "$.spec.policy.failureAction",
        ),
        unverifiable_action=_enum(
            policy.get("unverifiableAction", "Block"),
            _POLICY_UNVERIFIABLE_ACTIONS,
            "$.spec.policy.unverifiableAction",
        ),
        terminal_evidence=_enum(
            policy.get("terminalEvidence", "Required"),
            _POLICY_TERMINAL_EVIDENCE,
            "$.spec.policy.terminalEvidence",
        ),
    )


def _decode_authority(value: object, path: str) -> AuthoritySpec:
    authority = _mapping(value, path)
    _known_keys(
        authority,
        {"name", "capability", "provider", "parametersRef", "compatibility"},
        path,
    )
    compatibility = authority.get("compatibility", False)
    if type(compatibility) is not bool:
        _fail("InvalidAuthority", f"{path}.compatibility", "must be a boolean")
    return AuthoritySpec(
        name=_token(authority.get("name"), f"{path}.name"),
        capability=_token(authority.get("capability"), f"{path}.capability"),
        provider=_token(authority.get("provider"), f"{path}.provider"),
        parameters_ref=(
            _decode_reference(authority["parametersRef"], f"{path}.parametersRef")
            if authority.get("parametersRef") is not None
            else None
        ),
        compatibility=compatibility,
    )


def _decode_recovery_set(value: object, path: str) -> RecoverySetSpec:
    recovery_set = _mapping(value, path)
    _known_keys(recovery_set, {"name", "producer"}, path)
    producer = _mapping(recovery_set.get("producer"), f"{path}.producer")
    _known_keys(producer, {"stage", "evidence", "role"}, f"{path}.producer")
    return RecoverySetSpec(
        name=_token(recovery_set.get("name"), f"{path}.name"),
        stage=_token(producer.get("stage"), f"{path}.producer.stage"),
        evidence=_token(producer.get("evidence"), f"{path}.producer.evidence"),
        role=_token(producer.get("role"), f"{path}.producer.role"),
    )


def _decode_stage(value: object, path: str) -> ApiStage:
    stage = _mapping(value, path)
    _known_keys(
        stage,
        {
            "id",
            "adapterRef",
            "operation",
            "destructive",
            "requires",
            "parametersRef",
            "inputBindings",
            "publish",
            "recoverySets",
            "authorityRef",
            "recoveryOperation",
        },
        path,
    )
    adapter_ref = _mapping(stage.get("adapterRef"), f"{path}.adapterRef")
    _known_keys(adapter_ref, {"name"}, f"{path}.adapterRef")
    destructive = stage.get("destructive", False)
    if type(destructive) is not bool:
        _fail("InvalidType", f"{path}.destructive", "must be a boolean")
    authority_ref = stage.get("authorityRef")
    recovery_operation = stage.get("recoveryOperation")
    return ApiStage(
        id=_token(stage.get("id"), f"{path}.id"),
        adapter=_token(adapter_ref.get("name"), f"{path}.adapterRef.name"),
        operation=_token(stage.get("operation"), f"{path}.operation"),
        destructive=destructive,
        requires=tuple(
            _token(item, f"{path}.requires[{index}]")
            for index, item in enumerate(
                _list(
                    stage.get("requires", []),
                    f"{path}.requires",
                    _MAX_STAGES,
                )
            )
        ),
        parameters_ref=(
            _decode_reference(stage["parametersRef"], f"{path}.parametersRef")
            if stage.get("parametersRef") is not None
            else None
        ),
        input_bindings=tuple(
            _decode_input_binding(item, f"{path}.inputBindings[{index}]")
            for index, item in enumerate(
                _list(
                    stage.get("inputBindings", []),
                    f"{path}.inputBindings",
                    _MAX_INPUT_BINDINGS,
                )
            )
        ),
        publish=_token_set(
            stage.get("publish", []),
            f"{path}.publish",
            _MAX_STAGE_ITEMS,
        ),
        recovery_sets=_token_set(
            stage.get("recoverySets", []),
            f"{path}.recoverySets",
            _MAX_RECOVERY_SETS,
        ),
        authority_ref=(
            _token(authority_ref, f"{path}.authorityRef")
            if authority_ref is not None
            else None
        ),
        recovery_operation=(
            _token(recovery_operation, f"{path}.recoveryOperation")
            if recovery_operation is not None
            else None
        ),
    )


def _decode_input_binding(value: object, path: str) -> InputBindingSpec:
    binding = _mapping(value, path)
    _known_keys(binding, {"name", "stage", "output"}, path)
    return InputBindingSpec(
        name=_token(binding.get("name"), f"{path}.name"),
        stage=_token(binding.get("stage"), f"{path}.stage"),
        output=_token(binding.get("output"), f"{path}.output"),
    )


def _decode_reference(value: object, path: str) -> LocalObjectReference:
    reference = _mapping(value, path)
    _known_keys(reference, {"apiGroup", "kind", "name"}, path)
    api_group = reference.get("apiGroup", "")
    if not isinstance(api_group, str) or (
        api_group and not _valid_api_group(api_group)
    ):
        _fail("InvalidReference", f"{path}.apiGroup", "must be a DNS subdomain")
    kind = _text(reference.get("kind"), f"{path}.kind")
    if _KIND_RE.fullmatch(kind) is None:
        _fail("InvalidReference", f"{path}.kind", "has an invalid kind")
    return LocalObjectReference(
        api_group=api_group,
        kind=kind,
        name=_reference_name(reference.get("name"), f"{path}.name"),
    )


def _decode_status(value: object) -> ApiStatus:
    status = _mapping(value, "$.status")
    _known_keys(
        status,
        {
            "observedGeneration",
            "phase",
            "conditions",
            "recoverySets",
            "terminalEvidenceRef",
        },
        "$.status",
    )
    return ApiStatus(
        observed_generation=_nonnegative_integer(
            status.get("observedGeneration", 0),
            "$.status.observedGeneration",
        ),
        phase=_enum(status.get("phase", "Pending"), _PHASES, "$.status.phase"),
        conditions=tuple(
            _decode_condition(item, f"$.status.conditions[{index}]")
            for index, item in enumerate(
                _list(
                    status.get("conditions", []),
                    "$.status.conditions",
                    _MAX_CONDITIONS,
                )
            )
        ),
        recovery_sets=tuple(
            _decode_recovery_identity(item, f"$.status.recoverySets[{index}]")
            for index, item in enumerate(
                _list(
                    status.get("recoverySets", []),
                    "$.status.recoverySets",
                    _MAX_RECOVERY_SETS,
                )
            )
        ),
        terminal_evidence=(
            _decode_terminal_reference(
                status["terminalEvidenceRef"],
                "$.status.terminalEvidenceRef",
            )
            if status.get("terminalEvidenceRef") is not None
            else None
        ),
    )


def _decode_condition(value: object, path: str) -> ApiCondition:
    condition = _mapping(value, path)
    _known_keys(
        condition,
        {
            "type",
            "status",
            "reason",
            "message",
            "lastTransitionTime",
            "observedGeneration",
        },
        path,
    )
    condition_type = _text(condition.get("type"), f"{path}.type")
    if (
        len(condition_type) > _MAX_CONDITION_TYPE_LENGTH
        or _CONDITION_TYPE_RE.fullmatch(condition_type) is None
    ):
        _fail("InvalidCondition", f"{path}.type", "has an invalid condition type")
    reason = _text(condition.get("reason"), f"{path}.reason")
    if (
        len(reason) > _MAX_CONDITION_REASON_LENGTH
        or _CONDITION_REASON_RE.fullmatch(reason) is None
    ):
        _fail("InvalidCondition", f"{path}.reason", "has an invalid condition reason")
    transition_time = _text(
        condition.get("lastTransitionTime"),
        f"{path}.lastTransitionTime",
    )
    _rfc3339(transition_time, f"{path}.lastTransitionTime")
    return ApiCondition(
        type=condition_type,
        status=_enum(
            condition.get("status"),
            _CONDITION_STATUSES,
            f"{path}.status",
        ),
        observed_generation=_nonnegative_integer(
            condition.get("observedGeneration", 0),
            f"{path}.observedGeneration",
        ),
        reason=reason,
        message=_bounded_text(
            condition.get("message"),
            f"{path}.message",
            _MAX_CONDITION_MESSAGE_LENGTH,
        ),
        last_transition_time=transition_time,
    )


def _decode_recovery_identity(value: object, path: str) -> RecoverySetIdentity:
    identity = _mapping(value, path)
    _known_keys(identity, {"name", "evidence", "role", "digest"}, path)
    digest = _text(identity.get("digest"), f"{path}.digest")
    if not is_sha256_digest(digest):
        _fail("InvalidDigest", f"{path}.digest", "must be a SHA-256 digest")
    return RecoverySetIdentity(
        name=_token(identity.get("name"), f"{path}.name"),
        evidence=_token(identity.get("evidence"), f"{path}.evidence"),
        role=_token(identity.get("role"), f"{path}.role"),
        digest=digest,
    )


def _decode_terminal_reference(
    value: object,
    path: str,
) -> TerminalEvidenceReference:
    reference = _mapping(value, path)
    _known_keys(reference, {"apiGroup", "kind", "name", "digest"}, path)
    api_group = _text(reference.get("apiGroup", ""), f"{path}.apiGroup")
    if api_group and not _valid_api_group(api_group):
        _fail("InvalidReference", f"{path}.apiGroup", "must be a DNS subdomain")
    kind = _text(reference.get("kind"), f"{path}.kind")
    if _KIND_RE.fullmatch(kind) is None:
        _fail("InvalidReference", f"{path}.kind", "has an invalid kind")
    digest = _text(reference.get("digest"), f"{path}.digest")
    if not is_sha256_digest(digest):
        _fail("InvalidDigest", f"{path}.digest", "must be a SHA-256 digest")
    return TerminalEvidenceReference(
        api_group=api_group,
        kind=kind,
        name=_reference_name(reference.get("name"), f"{path}.name"),
        digest=digest,
    )


def _validate_semantics(resource: ApiResource) -> None:
    stages = _unique_by(resource.spec.stages, "id", "$.spec.stages", "DuplicateStage")
    authorities = _unique_by(
        resource.spec.authorities,
        "name",
        "$.spec.authorities",
        "DuplicateAuthority",
    )
    recovery_sets = _unique_by(
        resource.spec.recovery_sets,
        "name",
        "$.spec.recoverySets",
        "DuplicateRecoverySet",
    )

    producers: set[tuple[str, str]] = set()
    for recovery_set in resource.spec.recovery_sets:
        if recovery_set.stage not in stages:
            _fail(
                "UnknownRecoveryProducer",
                f"$.spec.recoverySets[{recovery_set.name}]",
                f"references unknown stage '{recovery_set.stage}'",
            )
        producer = (recovery_set.stage, recovery_set.evidence)
        if producer in producers:
            _fail(
                "DuplicateRecoveryProducer",
                f"$.spec.recoverySets[{recovery_set.name}].producer",
                "a producer stage and evidence name must identify one recovery set",
            )
        producers.add(producer)

    for stage in resource.spec.stages:
        if len(stage.requires) != len(set(stage.requires)):
            _fail(
                "DuplicateDependency",
                f"$.spec.stages[{stage.id}].requires",
                "contains a duplicate stage",
            )
        for dependency in stage.requires:
            if dependency not in stages:
                _fail(
                    "UnknownDependency",
                    f"$.spec.stages[{stage.id}].requires",
                    f"references unknown stage '{dependency}'",
                )
            if dependency == stage.id:
                _fail(
                    "DependencyCycle",
                    f"$.spec.stages[{stage.id}].requires",
                    "cannot reference its own stage",
                )

    for stage in resource.spec.stages:
        if stage.destructive and stage.authority_ref is None:
            _fail(
                "MissingDestructiveAuthority",
                f"$.spec.stages[{stage.id}].authorityRef",
                "a destructive stage requires an authority",
            )
        if stage.destructive and not stage.recovery_sets:
            _fail(
                "MissingRecoveryBarrier",
                f"$.spec.stages[{stage.id}].recoverySets",
                "a destructive stage requires a recovery set from a predecessor",
            )
        reachable = _dependencies(stage.id, stages)
        binding_names: set[str] = set()
        for binding in stage.input_bindings:
            if binding.name in binding_names:
                _fail(
                    "DuplicateInputBinding",
                    f"$.spec.stages[{stage.id}].inputBindings",
                    f"contains duplicate input '{binding.name}'",
                )
            binding_names.add(binding.name)
            if binding.stage not in reachable:
                _fail(
                    "UnorderedInputBinding",
                    f"$.spec.stages[{stage.id}].inputBindings",
                    f"input '{binding.name}' must bind a dependency",
                )
            if binding.output not in stages[binding.stage].publish:
                _fail(
                    "UnpublishedInputBinding",
                    f"$.spec.stages[{stage.id}].inputBindings",
                    f"input '{binding.name}' binds an unpublished output",
                )
        for recovery_name in stage.recovery_sets:
            recovery_set = recovery_sets.get(recovery_name)
            if recovery_set is None:
                _fail(
                    "UnknownRecoverySet",
                    f"$.spec.stages[{stage.id}].recoverySets",
                    f"references unknown recovery set '{recovery_name}'",
                )
            if recovery_set.stage not in reachable:
                _fail(
                    "UnorderedRecoverySet",
                    f"$.spec.stages[{stage.id}].recoverySets",
                    f"recovery set '{recovery_name}' must come from a dependency",
                )
        if stage.authority_ref is not None and stage.authority_ref not in authorities:
            _fail(
                "UnknownAuthority",
                f"$.spec.stages[{stage.id}].authorityRef",
                f"references unknown authority '{stage.authority_ref}'",
            )

    _topological_order(stages)
    if resource.status is not None:
        _validate_status(resource)


def _validate_status(resource: ApiResource) -> None:
    status = resource.status
    if status is None:
        return
    if status.observed_generation > resource.metadata.generation:
        _fail(
            "InvalidStatus",
            "$.status.observedGeneration",
            "cannot exceed metadata.generation",
        )
    condition_types: set[str] = set()
    for condition in status.conditions:
        if condition.type in condition_types:
            _fail(
                "DuplicateCondition",
                "$.status.conditions",
                f"contains duplicate condition '{condition.type}'",
            )
        condition_types.add(condition.type)
        if condition.observed_generation > status.observed_generation:
            _fail(
                "InvalidCondition",
                f"$.status.conditions[{condition.type}].observedGeneration",
                "cannot exceed status.observedGeneration",
            )
    recovery_identities = _unique_by(
        status.recovery_sets,
        "name",
        "$.status.recoverySets",
        "DuplicateRecoverySet",
    )
    declared_recovery_sets = {
        recovery_set.name: recovery_set for recovery_set in resource.spec.recovery_sets
    }
    for name, identity in recovery_identities.items():
        declaration = declared_recovery_sets.get(name)
        if declaration is None:
            _fail(
                "UnknownRecoverySet",
                f"$.status.recoverySets[{name}]",
                "does not match a declared recovery set",
            )
        if (
            identity.evidence != declaration.evidence
            or identity.role != declaration.role
        ):
            _fail(
                "RecoverySetMismatch",
                f"$.status.recoverySets[{name}]",
                "does not match its declared evidence identity",
            )
    is_terminal = status.phase in _TERMINAL_PHASES
    if is_terminal != (status.terminal_evidence is not None):
        _fail(
            "InvalidTerminalStatus",
            "$.status.terminalEvidenceRef",
            "must be present exactly when phase is terminal",
        )
    if is_terminal and (
        not status.observed_generation
        or status.observed_generation != resource.metadata.generation
    ):
        _fail(
            "StaleTerminalStatus",
            "$.status.observedGeneration",
            "must be positive and equal metadata.generation for a terminal phase",
        )
    if status.phase == "Succeeded" and set(recovery_identities) != set(
        declared_recovery_sets
    ):
        _fail(
            "IncompleteRecoverySetStatus",
            "$.status.recoverySets",
            "must contain every declared recovery set after success",
        )


def _topological_order(stages: Mapping[str, ApiStage]) -> tuple[str, ...]:
    indegree = {stage_id: 0 for stage_id in stages}
    dependants = {stage_id: [] for stage_id in stages}
    for stage in stages.values():
        for dependency in stage.requires:
            indegree[stage.id] += 1
            dependants[dependency].append(stage.id)
    ready = sorted(stage_id for stage_id, count in indegree.items() if count == 0)
    order: list[str] = []
    while ready:
        stage_id = ready.pop(0)
        order.append(stage_id)
        for dependant in sorted(dependants[stage_id]):
            indegree[dependant] -= 1
            if indegree[dependant] == 0:
                ready.append(dependant)
                ready.sort()
    if len(order) != len(stages):
        _fail("DependencyCycle", "$.spec.stages", "contains a dependency cycle")
    return tuple(order)


def _dependencies(
    stage_id: str,
    stages: Mapping[str, ApiStage],
) -> frozenset[str]:
    reachable: set[str] = set()
    pending = list(stages[stage_id].requires)
    while pending:
        dependency = pending.pop()
        if dependency in reachable:
            continue
        reachable.add(dependency)
        pending.extend(stages[dependency].requires)
    return frozenset(reachable)


def _encode_spec(spec: ApiSpec) -> dict[str, Any]:
    return {
        "workload": _encode_workload(spec.workload),
        "policy": {
            "failureAction": spec.policy.failure_action,
            "unverifiableAction": spec.policy.unverifiable_action,
            "terminalEvidence": spec.policy.terminal_evidence,
        },
        "authorities": [
            _encode_authority(item)
            for item in sorted(spec.authorities, key=lambda item: item.name)
        ],
        "recoverySets": [
            _encode_recovery_set(item)
            for item in sorted(spec.recovery_sets, key=lambda item: item.name)
        ],
        "stages": [
            _encode_stage(item)
            for item in sorted(spec.stages, key=lambda item: item.id)
        ],
    }


def _encode_workload(workload: ApiWorkload) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": workload.name,
        "revision": workload.revision,
        "digest": workload.digest,
    }
    if workload.ref is not None:
        payload["ref"] = _encode_reference(workload.ref)
    return payload


def _encode_authority(authority: AuthoritySpec) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": authority.name,
        "capability": authority.capability,
        "provider": authority.provider,
        "compatibility": authority.compatibility,
    }
    if authority.parameters_ref is not None:
        payload["parametersRef"] = _encode_reference(authority.parameters_ref)
    return payload


def _encode_recovery_set(recovery_set: RecoverySetSpec) -> dict[str, Any]:
    return {
        "name": recovery_set.name,
        "producer": {
            "stage": recovery_set.stage,
            "evidence": recovery_set.evidence,
            "role": recovery_set.role,
        },
    }


def _encode_stage(stage: ApiStage) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": stage.id,
        "adapterRef": {"name": stage.adapter},
        "operation": stage.operation,
        "requires": sorted(stage.requires),
        "inputBindings": [
            {"name": item.name, "stage": item.stage, "output": item.output}
            for item in sorted(stage.input_bindings, key=lambda item: item.name)
        ],
        "publish": sorted(stage.publish),
        "recoverySets": sorted(stage.recovery_sets),
    }
    if stage.destructive is not False:
        payload["destructive"] = stage.destructive
    if stage.parameters_ref is not None:
        payload["parametersRef"] = _encode_reference(stage.parameters_ref)
    if stage.authority_ref is not None:
        payload["authorityRef"] = stage.authority_ref
    if stage.recovery_operation is not None:
        payload["recoveryOperation"] = stage.recovery_operation
    return payload


def _encode_reference(reference: LocalObjectReference) -> dict[str, str]:
    return {
        "apiGroup": reference.api_group,
        "kind": reference.kind,
        "name": reference.name,
    }


def _encode_status(status: ApiStatus) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "observedGeneration": status.observed_generation,
        "phase": status.phase,
        "conditions": [
            {
                "type": item.type,
                "status": item.status,
                "observedGeneration": item.observed_generation,
                "lastTransitionTime": item.last_transition_time,
                "reason": item.reason,
                "message": item.message,
            }
            for item in sorted(status.conditions, key=lambda item: item.type)
        ],
        "recoverySets": [
            {
                "name": item.name,
                "evidence": item.evidence,
                "role": item.role,
                "digest": item.digest,
            }
            for item in sorted(status.recovery_sets, key=lambda item: item.name)
        ],
    }
    if status.terminal_evidence is not None:
        payload["terminalEvidenceRef"] = {
            "apiGroup": status.terminal_evidence.api_group,
            "kind": status.terminal_evidence.kind,
            "name": status.terminal_evidence.name,
            "digest": status.terminal_evidence.digest,
        }
    return payload


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail("InvalidType", path, "must be an object")
    if not all(isinstance(key, str) for key in value):
        _fail("InvalidType", path, "contains a non-string key")
    return value


def _list(
    value: object,
    path: str,
    maximum_items: int | None = None,
) -> Sequence[Any]:
    if not isinstance(value, list):
        _fail("InvalidType", path, "must be an array")
    if maximum_items is not None and len(value) > maximum_items:
        _fail(
            "InvalidValue",
            path,
            f"must contain no more than {maximum_items} items",
        )
    return value


def _known_keys(value: Mapping[str, Any], allowed: set[str], path: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _fail("UnknownField", path, f"contains unknown field '{unknown[0]}'")


def _text(value: object, path: str) -> str:
    if not isinstance(value, str):
        _fail("InvalidType", path, "must be a string")
    return value


def _nonempty_text(value: object, path: str) -> str:
    text = _text(value, path)
    if not text.strip() or text != text.strip():
        _fail("InvalidValue", path, "must be non-empty without surrounding space")
    return text


def _bounded_nonempty_text(value: object, path: str, maximum: int) -> str:
    text = _nonempty_text(value, path)
    if "\r" in text or "\n" in text:
        _fail("InvalidValue", path, "must be a single line")
    if len(text) > maximum:
        _fail("InvalidValue", path, f"must be no longer than {maximum} characters")
    return text


def _bounded_text(value: object, path: str, maximum: int) -> str:
    text = _text(value, path)
    if len(text) > maximum:
        _fail("InvalidValue", path, f"must be no longer than {maximum} characters")
    return text


def _token_set(value: object, path: str, maximum_items: int) -> frozenset[str]:
    items = _list(value, path, maximum_items)
    tokens = [_token(item, f"{path}[{index}]") for index, item in enumerate(items)]
    if len(tokens) != len(set(tokens)):
        _fail("DuplicateValue", path, "contains a duplicate value")
    return frozenset(tokens)


def _token(value: object, path: str) -> str:
    text = _text(value, path)
    if not is_token(text):
        _fail("InvalidToken", path, "has an invalid token")
    return text


def _dns_label(value: object, path: str) -> str:
    text = _text(value, path)
    if len(text) > 63 or _DNS_LABEL_RE.fullmatch(text) is None:
        _fail("InvalidMetadata", path, "must be a DNS label")
    return text


def _dns_subdomain(value: object, path: str) -> str:
    text = _text(value, path)
    if not _valid_dns_subdomain(text):
        _fail("InvalidMetadata", path, "must be a DNS subdomain")
    return text


def _reference_name(value: object, path: str) -> str:
    text = _text(value, path)
    if not _valid_dns_subdomain(text):
        _fail("InvalidReference", path, "must be a DNS subdomain")
    return text


def _valid_dns_subdomain(value: str) -> bool:
    return (
        len(value) <= _MAX_DNS_SUBDOMAIN_LENGTH
        and _DNS_SUBDOMAIN_RE.fullmatch(value) is not None
    )


def _valid_api_group(value: str) -> bool:
    return _valid_dns_subdomain(value) and all(
        len(label) <= 63 for label in value.split(".")
    )


def _enum(value: object, allowed: frozenset[str], path: str) -> str:
    text = _text(value, path)
    if text not in allowed:
        _fail("InvalidValue", path, f"unsupported value '{text}'")
    return text


def _nonnegative_integer(value: object, path: str) -> int:
    if type(value) is not int or value < 0:
        _fail("InvalidType", path, "must be a non-negative integer")
    if value > _MAX_GENERATION:
        _fail("InvalidValue", path, "must fit a signed 64-bit integer")
    return value


def _rfc3339(value: str, path: str) -> None:
    if _RFC3339_RE.fullmatch(value) is None:
        _fail("InvalidCondition", path, "must be an RFC 3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        _fail("InvalidCondition", path, "must be an RFC 3339 timestamp")
    if parsed.tzinfo is None:
        _fail("InvalidCondition", path, "must include a timezone")


def _unique_by(
    values: Sequence[Any],
    attribute: str,
    path: str,
    reason_code: str,
) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for value in values:
        key = getattr(value, attribute)
        if key in found:
            _fail(reason_code, path, f"contains duplicate '{key}'")
        found[key] = value
    return found


def _fail(reason_code: str, path: str, message: str) -> None:
    raise ApiValidationError(reason_code, path, message)
