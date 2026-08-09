"""
purpose: Evaluate whether a declared environment has reached a verified stop state.
maintainer: HybridOps.Tech
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

import yaml


TERMINAL = "terminal"
TERMINAL_WITH_RETENTION = "terminal_with_retention"
NON_TERMINAL = "non_terminal"

_RETENTION_CLASSES = {"reproducible", "preserve", "retained"}
_REMOVED_STATES = {"absent", "destroyed"}
_ARCHIVE_RESULTS = {"pending", "passed", "failed"}
_TEARDOWN_RESULTS = {"absent", "destroyed", "failed", "retained"}


class StopStateManifestError(ValueError):
    """Raised when a stop-state manifest does not satisfy the input contract."""


def load_stop_state_manifest(path: Path) -> dict[str, Any]:
    """Load a YAML or JSON stop-state manifest."""

    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise StopStateManifestError(f"manifest not found: {source}")
    try:
        payload = yaml.safe_load(source.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise StopStateManifestError(f"cannot read manifest: {exc}") from exc
    if not isinstance(payload, dict):
        raise StopStateManifestError("manifest root must be a mapping")
    return payload


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise StopStateManifestError(f"{label} must be a mapping")
    return dict(value)


def _mapping_list(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise StopStateManifestError(f"{label} must be a list")
    result: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        result.append(_mapping(item, f"{label}[{index}]"))
    return result


def _text(value: Any, label: str, *, required: bool = True) -> str:
    token = str(value or "").strip()
    if required and not token:
        raise StopStateManifestError(f"{label} is required")
    return token


def _text_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise StopStateManifestError(f"{label} must be a list")
    result: list[str] = []
    for index, item in enumerate(value):
        result.append(_text(item, f"{label}[{index}]"))
    if len(set(result)) != len(result):
        raise StopStateManifestError(f"{label} contains duplicate resource identifiers")
    return result


def _boolean(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise StopStateManifestError(f"{label} must be a boolean")
    return value


def _decimal(value: Any, label: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise StopStateManifestError(f"{label} must be a non-negative number")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise StopStateManifestError(f"{label} must be a non-negative number") from exc
    if not amount.is_finite() or amount < 0:
        raise StopStateManifestError(f"{label} must be a non-negative number")
    return amount


def _decimal_text(value: Decimal) -> str:
    token = format(value, "f")
    if "." in token:
        token = token.rstrip("0").rstrip(".")
    return token or "0"


def _valid_review_date(value: str) -> bool:
    if not value:
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _timestamp(value: Any, label: str) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        token = _text(value, label)
        try:
            parsed = datetime.fromisoformat(token.replace("Z", "+00:00"))
        except ValueError as exc:
            raise StopStateManifestError(
                f"{label} must be an ISO 8601 timestamp"
            ) from exc
    if parsed.tzinfo is None:
        raise StopStateManifestError(f"{label} must include a timezone")
    return parsed.isoformat().replace("+00:00", "Z")


def _verified_at(value: str | None) -> str:
    candidate: Any = value
    if not candidate:
        candidate = datetime.now(timezone.utc).replace(microsecond=0)
    return _timestamp(candidate, "verified_at")


def _index_resources(environment: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    resources = _mapping_list(environment.get("resources"), "environment.resources")
    if not resources:
        raise StopStateManifestError("environment.resources must contain at least one resource")

    indexed: dict[str, dict[str, Any]] = {}
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(resources):
        label = f"environment.resources[{index}]"
        logical_id = _text(raw.get("logical_id"), f"{label}.logical_id")
        if logical_id in indexed:
            raise StopStateManifestError(
                f"environment.resources contains duplicate logical_id: {logical_id}"
            )
        provider_id = _text(raw.get("provider_id"), f"{label}.provider_id")
        state = _text(raw.get("state"), f"{label}.state").lower()
        retention_class = _text(
            raw.get("retention_class"),
            f"{label}.retention_class",
        ).lower()
        if retention_class not in _RETENTION_CLASSES:
            choices = ", ".join(sorted(_RETENTION_CLASSES))
            raise StopStateManifestError(
                f"{label}.retention_class must be one of: {choices}"
            )

        cost_basis = _text(raw.get("cost_basis"), f"{label}.cost_basis")
        cost_bearing = (
            _boolean(raw.get("cost_bearing"), f"{label}.cost_bearing")
            if "cost_bearing" in raw
            else True
        )
        archive_scopes = raw.get("archive_scopes")
        if archive_scopes is None:
            normalized_scopes = [logical_id] if retention_class == "preserve" else []
        else:
            normalized_scopes = _text_list(archive_scopes, f"{label}.archive_scopes")
            if retention_class == "preserve" and not normalized_scopes:
                raise StopStateManifestError(
                    f"{label}.archive_scopes must not be empty for preserved resources"
                )

        item = {
            "logical_id": logical_id,
            "provider_id": provider_id,
            "state": state,
            "retention_class": retention_class,
            "cost_basis": cost_basis,
            "cost_bearing": cost_bearing,
            "owner": _text(raw.get("owner"), f"{label}.owner", required=False),
            "review_date": _text(
                raw.get("review_date"),
                f"{label}.review_date",
                required=False,
            ),
            "next_action": _text(
                raw.get("next_action"),
                f"{label}.next_action",
                required=False,
            ),
            "archive_scopes": normalized_scopes,
        }
        indexed[logical_id] = item
        normalized.append(item)
    return normalized, indexed


def _index_archives(manifest: dict[str, Any]) -> dict[str, dict[str, str]]:
    raw_archives = manifest.get("archives", [])
    archives = _mapping_list(raw_archives, "archives")
    indexed: dict[str, dict[str, str]] = {}
    for index, raw in enumerate(archives):
        label = f"archives[{index}]"
        scope = _text(raw.get("scope"), f"{label}.scope")
        if scope in indexed:
            raise StopStateManifestError(f"archives contains duplicate scope: {scope}")
        verification = _text(raw.get("verification"), f"{label}.verification").lower()
        if verification not in _ARCHIVE_RESULTS:
            choices = ", ".join(sorted(_ARCHIVE_RESULTS))
            raise StopStateManifestError(
                f"{label}.verification must be one of: {choices}"
            )
        indexed[scope] = {
            "scope": scope,
            "location": _text(
                raw.get("location"),
                f"{label}.location",
                required=False,
            ),
            "integrity_value": _text(
                raw.get("integrity_value"),
                f"{label}.integrity_value",
                required=False,
            ),
            "verification": verification,
        }
    return indexed


def _index_teardown(
    manifest: dict[str, Any],
    resources: dict[str, dict[str, Any]],
) -> dict[str, dict[str, str]]:
    teardown = _mapping(manifest.get("teardown", {}), "teardown")
    steps = _mapping_list(teardown.get("steps", []), "teardown.steps")
    indexed: dict[str, dict[str, str]] = {}
    for index, raw in enumerate(steps):
        label = f"teardown.steps[{index}]"
        resource = _text(raw.get("resource"), f"{label}.resource")
        if resource not in resources:
            raise StopStateManifestError(
                f"{label}.resource is not declared in environment.resources: {resource}"
            )
        if resource in indexed:
            raise StopStateManifestError(
                f"teardown.steps contains duplicate resource: {resource}"
            )
        result = _text(raw.get("result"), f"{label}.result").lower()
        if result not in _TEARDOWN_RESULTS:
            choices = ", ".join(sorted(_TEARDOWN_RESULTS))
            raise StopStateManifestError(f"{label}.result must be one of: {choices}")
        indexed[resource] = {
            "result": result,
            "next_action": _text(
                raw.get("next_action"),
                f"{label}.next_action",
                required=False,
            ),
        }
    return indexed


def _evaluate_estimate(
    manifest: dict[str, Any],
    resources: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    estimate = _mapping(manifest.get("estimate"), "estimate")
    currency = _text(estimate.get("currency"), "estimate.currency").upper()
    fixed_hourly = _decimal(estimate.get("fixed_hourly"), "estimate.fixed_hourly")
    pricing_timestamp = _timestamp(
        estimate.get("pricing_timestamp"),
        "estimate.pricing_timestamp",
    )
    included = _text_list(estimate.get("included"), "estimate.included")
    excluded = _text_list(estimate.get("excluded"), "estimate.excluded")

    overlap = sorted(set(included) & set(excluded))
    if overlap:
        raise StopStateManifestError(
            "estimate.included and estimate.excluded overlap: " + ", ".join(overlap)
        )

    declared = set(resources)
    referenced = set(included) | set(excluded)
    unknown = sorted(referenced - declared)
    if unknown:
        raise StopStateManifestError(
            "estimate references undeclared resources: " + ", ".join(unknown)
        )

    cost_bearing = {
        logical_id
        for logical_id, resource in resources.items()
        if bool(resource["cost_bearing"])
    }
    non_cost = sorted(referenced - cost_bearing)
    if non_cost:
        raise StopStateManifestError(
            "estimate classifies resources declared as non-cost-bearing: "
            + ", ".join(non_cost)
        )

    unclassified = sorted(cost_bearing - referenced)
    coverage = (
        Decimal("100")
        if not cost_bearing
        else (Decimal(len(set(included))) * Decimal("100") / Decimal(len(cost_bearing)))
    )
    coverage = coverage.quantize(Decimal("0.01"))

    unresolved: list[dict[str, str]] = []
    if unclassified:
        unresolved.append(
            {
                "check": "estimate_scope",
                "reason": "cost-bearing resources are not classified by the estimate",
                "next_action": "add each resource to estimate.included or estimate.excluded",
                "resources": ", ".join(unclassified),
            }
        )

    return (
        {
            "currency": currency,
            "fixed_hourly": _decimal_text(fixed_hourly),
            "pricing_timestamp": pricing_timestamp,
            "cost_bearing_resources": sorted(cost_bearing),
            "included_resources": sorted(included),
            "excluded_resources": sorted(excluded),
            "unclassified_resources": unclassified,
            "coverage_percent": float(coverage),
            "scope_complete": not unclassified,
        },
        unresolved,
    )


def _archive_failure(
    resource: dict[str, Any],
    scope: str,
    archive: dict[str, str] | None,
) -> dict[str, str] | None:
    if archive is None:
        return {
            "logical_id": resource["logical_id"],
            "scope": scope,
            "verification": "missing",
            "reason": "required archive is not recorded",
            "next_action": "export and verify the required archive",
        }
    if archive["verification"] != "passed":
        return {
            "logical_id": resource["logical_id"],
            "scope": scope,
            "verification": archive["verification"],
            "reason": f"required archive verification is {archive['verification']}",
            "next_action": "complete archive verification before teardown",
        }
    missing = [
        field
        for field in ("location", "integrity_value")
        if not archive[field]
    ]
    if missing:
        return {
            "logical_id": resource["logical_id"],
            "scope": scope,
            "verification": archive["verification"],
            "reason": "verified archive is missing " + " and ".join(missing),
            "next_action": "record the archive location and integrity value",
        }
    return None


def _resource_issue(
    resource: dict[str, Any],
    teardown: dict[str, str] | None,
    reasons: list[str],
    default_action: str,
) -> dict[str, str]:
    action = resource["next_action"]
    if not action and teardown:
        action = teardown["next_action"]
    return {
        "logical_id": resource["logical_id"],
        "provider_id": resource["provider_id"],
        "state": resource["state"],
        "reason": "; ".join(reasons),
        "next_action": action or default_action,
    }


def evaluate_stop_state(
    manifest: Mapping[str, Any],
    *,
    verified_at: str | None = None,
) -> dict[str, Any]:
    """Evaluate a lifecycle manifest and return a normalized stop-state result."""

    payload = _mapping(manifest, "manifest")
    schema_version = _text(
        payload.get("schema_version"),
        "schema_version",
        required=False,
    ) or "1.0"
    if schema_version != "1.0":
        raise StopStateManifestError(
            f"unsupported schema_version: {schema_version}"
        )
    environment = _mapping(payload.get("environment"), "environment")
    environment_id = _text(environment.get("id"), "environment.id")
    state_timestamp = _timestamp(
        environment.get("state_timestamp"),
        "environment.state_timestamp",
    )
    resources, resources_by_id = _index_resources(environment)
    archives = _index_archives(payload)
    teardown = _index_teardown(payload, resources_by_id)
    estimate, unresolved_checks = _evaluate_estimate(payload, resources_by_id)

    retained_resources: list[dict[str, str]] = []
    unresolved_resources: list[dict[str, str]] = []
    archive_failures: list[dict[str, str]] = []
    archive_results: list[dict[str, str]] = []
    resource_results: list[dict[str, Any]] = []
    removed = 0
    retained = 0
    resource_states_terminal = True
    retention_accountable = True

    for resource in resources:
        logical_id = resource["logical_id"]
        state = resource["state"]
        retention_class = resource["retention_class"]
        step = teardown.get(logical_id)
        reasons: list[str] = []
        default_action = "refresh the resource state and resume teardown"

        if retention_class == "retained":
            if state != "retained":
                resource_states_terminal = False
                reasons.append("resource is not recorded as retained")
                default_action = "record approved retention or remove the resource"
            if not resource["owner"]:
                retention_accountable = False
                reasons.append("retained resource has no owner")
                default_action = "assign an owner and review date"
            if not _valid_review_date(resource["review_date"]):
                retention_accountable = False
                reasons.append("retained resource has no valid review date")
                default_action = "assign an owner and review date"
            if not reasons:
                retained += 1
                retained_resources.append(
                    {
                        "logical_id": logical_id,
                        "provider_id": resource["provider_id"],
                        "owner": resource["owner"],
                        "review_date": resource["review_date"],
                        "cost_basis": resource["cost_basis"],
                    }
                )
        else:
            if state not in _REMOVED_STATES:
                resource_states_terminal = False
                reasons.append(f"resource state is {state}, not destroyed or absent")
                default_action = (
                    "resolve the failed teardown step and retry"
                    if state == "failed" or (step and step["result"] == "failed")
                    else "destroy the resource or approve retention"
                )
                if step and step["result"] in _REMOVED_STATES:
                    reasons.append("declared state does not reflect the teardown result")
                    default_action = "refresh provider state before continuing"
            else:
                removed += 1

        if retention_class == "preserve":
            for scope in resource["archive_scopes"]:
                archive = archives.get(scope)
                archive_results.append(
                    {
                        "logical_id": logical_id,
                        "scope": scope,
                        "location": archive["location"] if archive else "",
                        "integrity_value": archive["integrity_value"] if archive else "",
                        "verification": archive["verification"] if archive else "missing",
                    }
                )
                failure = _archive_failure(resource, scope, archive)
                if failure:
                    archive_failures.append(failure)
                    reasons.append(failure["reason"])
                    default_action = failure["next_action"]

        if reasons:
            outcome = "unresolved"
        elif retention_class == "retained":
            outcome = "retained"
        else:
            outcome = "removed"
        if reasons:
            unresolved_resources.append(
                _resource_issue(resource, step, reasons, default_action)
            )
        resource_results.append(
            {
                "logical_id": logical_id,
                "provider_id": resource["provider_id"],
                "state": state,
                "retention_class": retention_class,
                "cost_basis": resource["cost_basis"],
                "cost_bearing": resource["cost_bearing"],
                "archive_scopes": list(resource["archive_scopes"]),
                "teardown_result": step["result"] if step else None,
                "outcome": outcome,
            }
        )

    estimate_complete = bool(estimate["scope_complete"])
    archives_verified = not archive_failures

    if (
        resource_states_terminal
        and retention_accountable
        and estimate_complete
        and archives_verified
    ):
        result = TERMINAL_WITH_RETENTION if retained_resources else TERMINAL
    else:
        result = NON_TERMINAL

    terminal_count = len(resources) - len(unresolved_resources)
    return {
        "schema_version": schema_version,
        "environment_id": environment_id,
        "state_timestamp": state_timestamp,
        "verified_at": _verified_at(verified_at),
        "result": result,
        "checks": {
            "resources_terminal": resource_states_terminal,
            "retention_accountable": retention_accountable,
            "archives_verified": archives_verified,
            "estimate_scope_complete": estimate_complete,
        },
        "resources": {
            "declared": len(resources),
            "terminal": terminal_count,
            "removed": removed,
            "retained": retained,
            "unresolved": len(unresolved_resources),
        },
        "estimate": estimate,
        "resource_results": resource_results,
        "archive_results": archive_results,
        "retained_resources": retained_resources,
        "unresolved_resources": unresolved_resources,
        "unresolved_checks": unresolved_checks,
        "archive_failures": archive_failures,
    }


def format_stop_state_result(result: Mapping[str, Any]) -> str:
    """Render a concise operator summary."""

    def format_identifiers(value: Any, *, limit: int = 5) -> str:
        if not isinstance(value, list) or not value:
            return "none"
        identifiers = [str(item) for item in value]
        visible = ", ".join(identifiers[:limit])
        remaining = len(identifiers) - limit
        return f"{visible}, +{remaining} more" if remaining > 0 else visible

    resources = _mapping(result.get("resources"), "result.resources")
    estimate = _mapping(result.get("estimate"), "result.estimate")
    lines = [
        (
            f"environment={result.get('environment_id')} "
            f"stop_state={result.get('result')}"
        ),
        (
            "resources: "
            f"{resources.get('declared')} declared, "
            f"{resources.get('removed')} removed, "
            f"{resources.get('retained')} retained, "
            f"{resources.get('unresolved')} unresolved"
        ),
        (
            "bounded estimate: "
            f"{estimate.get('currency')} {estimate.get('fixed_hourly')}/hour, "
            f"{estimate.get('coverage_percent'):.2f}% coverage"
        ),
        (
            "estimate scope: "
            f"included={format_identifiers(estimate.get('included_resources'))}; "
            f"excluded={format_identifiers(estimate.get('excluded_resources'))}"
        ),
    ]

    retained_resources = result.get("retained_resources")
    if isinstance(retained_resources, list) and retained_resources:
        lines.append("retained:")
        for item in retained_resources:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                f"- {item.get('logical_id')}: owner={item.get('owner')}, "
                f"review_date={item.get('review_date')}"
            )

    unresolved_resources = result.get("unresolved_resources")
    unresolved_checks = result.get("unresolved_checks")
    if (
        (isinstance(unresolved_resources, list) and unresolved_resources)
        or (isinstance(unresolved_checks, list) and unresolved_checks)
    ):
        lines.append("unresolved:")
    if isinstance(unresolved_resources, list):
        for item in unresolved_resources:
            if not isinstance(item, Mapping):
                continue
            lines.append(
                f"- {item.get('logical_id')}: {item.get('reason')}; "
                f"next: {item.get('next_action')}"
            )
    if isinstance(unresolved_checks, list):
        for item in unresolved_checks:
            if not isinstance(item, Mapping):
                continue
            resources_text = str(item.get("resources") or "").strip()
            scope = f" ({resources_text})" if resources_text else ""
            lines.append(
                f"- {item.get('check')}{scope}: {item.get('reason')}; "
                f"next: {item.get('next_action')}"
            )
    return "\n".join(lines)
