terraform {
  required_version = ">= 1.6.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0, < 7.0"
    }
  }
}

# ── Inputs ────────────────────────────────────────────────────────────────────

variable "project_id" {
  type        = string
  description = "GCP project ID in which the ESO service account will be created."
}

variable "eso_sa_name" {
  type        = string
  default     = "eso-gsm-reader"
  description = "Service account ID (short name, not email) for the ESO Secret Manager reader."
}

variable "eso_sa_display_name" {
  type        = string
  default     = "External Secrets Operator — GCP Secret Manager Reader"
  description = "Human-readable display name for the ESO service account."
}

# ── ESO service account ───────────────────────────────────────────────────────
#
# The org-level iam.disableServiceAccountKeyCreation policy override is handled
# by `hyops init gcp --with-cli-login` using operator ADC before this module
# runs. The key is generated once by `hyops init gcp --with-eso-sa`, stored in
# the operator bootstrap vault, and consumed by platform/k8s/gsm-bootstrap to
# create the gsm-sa-credentials Kubernetes secret. When Workload Identity
# Federation is adopted for on-prem OIDC, the key lifecycle should be retired.

resource "google_service_account" "eso" {
  account_id   = var.eso_sa_name
  display_name = var.eso_sa_display_name
  project      = var.project_id
}

resource "google_project_iam_member" "eso_secretmanager_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.eso.email}"

  depends_on = [google_service_account.eso]
}

# ── Outputs ───────────────────────────────────────────────────────────────────

output "eso_sa_email" {
  description = "Email of the ESO GCP service account."
  value       = google_service_account.eso.email
}
