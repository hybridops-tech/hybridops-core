"""Shared GCP runtime helpers."""

from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request


def normalize_billing_account_id(value: str | None) -> str:
    """Return the bare GCP billing account id.

    Google APIs and CLI surfaces sometimes return the billing account in
    resource-name form (`billingAccounts/XXXX-XXXXXX-XXXXXX`) while module
    contracts typically expect the bare id. Accept both, store one canonical
    representation, and keep downstream providers deterministic.
    """

    raw = str(value or "").strip()
    prefix = "billingAccounts/"
    if raw.startswith(prefix):
        return raw[len(prefix) :].strip()
    return raw


def _gcloud_capture(argv: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(argv, text=True, capture_output=True, check=False)
    return int(proc.returncode), str(proc.stdout or "").strip(), str(proc.stderr or "").strip()


def _test_billing_permission_with_token(token: str, billing_account_id: str, permission: str) -> tuple[bool, str]:
    body = json.dumps({"permissions": [permission]}).encode("utf-8")
    req = urllib.request.Request(
        f"https://cloudbilling.googleapis.com/v1/billingAccounts/{billing_account_id}:testIamPermissions",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        return False, f"Cloud Billing API HTTP {exc.code}: {detail or exc.reason}"
    except Exception as exc:
        return False, str(exc)
    perms = payload.get("permissions")
    if isinstance(perms, list) and permission in perms:
        return True, ""
    return False, ""


def _test_project_permissions_with_token(
    token: str,
    project_id: str,
    permissions: list[str],
) -> tuple[set[str], str]:
    body = json.dumps({"permissions": list(permissions)}).encode("utf-8")
    req = urllib.request.Request(
        f"https://cloudresourcemanager.googleapis.com/v1/projects/{project_id}:testIamPermissions",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        return set(), f"Cloud Resource Manager API HTTP {exc.code}: {detail or exc.reason}"
    except Exception as exc:
        return set(), str(exc)

    perms = payload.get("permissions")
    if not isinstance(perms, list):
        return set(), ""
    return {str(item).strip() for item in perms if str(item).strip()}, ""


def _is_billing_quota_noise(detail: str) -> bool:
    text = str(detail or "")
    return (
        "RATE_LIMIT_EXCEEDED" in text
        or "Quota exceeded" in text
        or "RESOURCE_EXHAUSTED" in text
    )


def diagnose_billing_association_permission(
    billing_account_id: str | None,
) -> tuple[bool, str, bool]:
    """Validate that ADC can associate a new project with a billing account.

    Returns:
      (ok, detail, adc_refresh_recommended)
    """

    bare_id = normalize_billing_account_id(billing_account_id)
    if not bare_id:
        return False, "billing account id is missing", False
    permission = "billing.resourceAssociations.create"
    adc_rc, adc_token, adc_err = _gcloud_capture(["gcloud", "auth", "application-default", "print-access-token"])
    if adc_rc != 0 or not adc_token:
        detail = adc_err or "ADC not available"
        return False, f"ADC not available: {detail}. Run: gcloud auth application-default login", True
    adc_ok, adc_detail = _test_billing_permission_with_token(adc_token, bare_id, permission)
    if adc_ok:
        return True, "", False

    cli_rc, cli_token, cli_err = _gcloud_capture(["gcloud", "auth", "print-access-token"])
    if cli_rc == 0 and cli_token:
        cli_ok, cli_detail = _test_billing_permission_with_token(cli_token, bare_id, permission)
        if cli_ok:
            return (
                False,
                (
                    f"ADC lacks {permission} on billingAccounts/{bare_id}, while the active gcloud identity can access it. "
                    "Refresh ADC with: gcloud auth application-default login"
                ),
                True,
            )
        if _is_billing_quota_noise(cli_detail):
            return (
                False,
                (
                    f"ADC lacks {permission} on billingAccounts/{bare_id}. "
                    "Verification of the active gcloud identity was rate-limited by Cloud Billing API quota, "
                    "so HyOps will still recommend refreshing ADC once before failing hard."
                ),
                True,
            )

    detail = adc_detail or adc_err or cli_err or f"current ADC lacks {permission} on billingAccounts/{bare_id}"
    return False, detail, False


def diagnose_project_access(
    project_id: str | None,
    *,
    impersonate_service_account: str | None = None,
) -> tuple[bool, str]:
    """Check whether the effective identity can read a GCP project."""

    target_project_id = str(project_id or "").strip()
    if not target_project_id:
        return False, "project id is missing"

    impersonate = str(impersonate_service_account or "").strip()
    if impersonate:
        rc, token, err = _gcloud_capture(
            [
                "gcloud",
                "auth",
                "print-access-token",
                f"--impersonate-service-account={impersonate}",
                "--project",
                target_project_id,
            ]
        )
        identity = f"service account {impersonate}"
        if rc != 0 or not token:
            detail = err or "failed to mint impersonated access token"
            return False, f"{identity} could not be validated: {detail}"
    else:
        rc, token, err = _gcloud_capture(["gcloud", "auth", "application-default", "print-access-token"])
        identity = "current ADC principal"
        if rc != 0 or not token:
            detail = err or "ADC not available"
            return False, f"ADC not available: {detail}. Run: gcloud auth application-default login"

    req = urllib.request.Request(
        f"https://cloudresourcemanager.googleapis.com/v1/projects/{target_project_id}",
        headers={
            "Authorization": f"Bearer {token}",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace").strip()
        reason = detail or exc.reason
        return False, f"{identity} cannot access project {target_project_id}: HTTP {exc.code}: {reason}"
    except Exception as exc:
        return False, f"{identity} cannot access project {target_project_id}: {exc}"

    return True, ""


def diagnose_private_service_access_permissions(
    *,
    project_id: str | None,
    network_project_id: str | None = None,
    impersonate_service_account: str | None = None,
) -> tuple[bool, str]:
    """Validate the effective Terraform identity for Cloud SQL PSA creation.

    This checks the permission pair needed when Cloud SQL creates a private
    service connection:
      - compute.globalAddresses.createInternal
      - servicenetworking.services.addPeering
    """

    target_project_id = str(network_project_id or project_id or "").strip()
    if not target_project_id:
        return False, "network project id is missing"

    permissions = [
        "compute.globalAddresses.createInternal",
        "servicenetworking.services.addPeering",
    ]
    impersonate = str(impersonate_service_account or "").strip()

    if impersonate:
        rc, token, err = _gcloud_capture(
            [
                "gcloud",
                "auth",
                "print-access-token",
                f"--impersonate-service-account={impersonate}",
                "--project",
                target_project_id,
            ]
        )
        identity = f"service account {impersonate}"
        if rc != 0 or not token:
            detail = err or "failed to mint impersonated access token"
            return False, f"{identity} could not be validated: {detail}"
    else:
        rc, token, err = _gcloud_capture(["gcloud", "auth", "application-default", "print-access-token"])
        identity = "current ADC principal"
        if rc != 0 or not token:
            detail = err or "ADC not available"
            return False, f"ADC not available: {detail}. Run: gcloud auth application-default login"

    granted, detail = _test_project_permissions_with_token(token, target_project_id, permissions)
    if detail:
        return False, detail

    missing = [perm for perm in permissions if perm not in granted]
    if not missing:
        return True, ""

    recommended_roles: list[str] = []
    if "compute.globalAddresses.createInternal" in missing:
        recommended_roles.append("roles/compute.networkAdmin")
    if "servicenetworking.services.addPeering" in missing:
        recommended_roles.append("roles/servicenetworking.networksAdmin")
    role_hint = ", ".join(recommended_roles)
    role_text = f" Grant {role_hint} on project {target_project_id}." if role_hint else ""

    project_hint = ""
    source_project_id = str(project_id or "").strip()
    if source_project_id and source_project_id != target_project_id:
        project_hint = (
            f" Cloud SQL runs in project {source_project_id}, but the private network lives in host project "
            f"{target_project_id}; the host project must carry the network roles."
        )

    return False, (
        f"{identity} lacks {', '.join(missing)} on project {target_project_id}."
        f"{role_text}"
        f"{project_hint}"
    ).strip()
