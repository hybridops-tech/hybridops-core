# Normalized cross-provider outputs
output "repo_backend" {
  value       = "gcs"
  description = "Repository backend type for pgBackRest (normalized contract)."
}

output "repo_provider" {
  value       = "gcp"
  description = "Cloud provider for this repository module (normalized contract)."
}

output "repo_bucket_name" {
  value       = google_storage_bucket.repo.name
  description = "Repository bucket name (normalized contract)."
}

output "repo_region" {
  value       = google_storage_bucket.repo.location
  description = "Repository location/region (normalized contract)."
}

output "repo_principal_type" {
  value       = "service_account"
  description = "Principal type used by backup clients (normalized contract)."
}

output "repo_principal_name" {
  value       = google_service_account.pgbackrest.email
  description = "Principal identity used by backup clients (normalized contract)."
}

output "repo_credential_create_hint" {
  value       = "gcloud iam service-accounts keys create ./pgbackrest-gcs-sa.json --iam-account ${google_service_account.pgbackrest.email}"
  description = "Operator hint to mint workload credentials out-of-band (normalized contract)."
}

# Legacy aliases retained for compatibility
output "bucket_name" {
  value       = google_storage_bucket.repo.name
  description = "GCS bucket name for the pgBackRest repository."
}

output "service_account_email" {
  value       = google_service_account.pgbackrest.email
  description = "Service account email that has objectAdmin on the repo bucket."
}

output "gcloud_sa_key_hint" {
  value = "gcloud iam service-accounts keys create ./pgbackrest-gcs-sa.json --iam-account ${google_service_account.pgbackrest.email}"
}
