resource "google_storage_bucket" "repo" {
  project       = var.project_id
  name          = var.bucket_name
  location      = var.location
  storage_class = var.storage_class

  uniform_bucket_level_access = var.uniform_bucket_level_access
  public_access_prevention    = "enforced"

  versioning {
    enabled = var.versioning_enabled
  }

  dynamic "lifecycle_rule" {
    for_each = var.lifecycle_delete_age_days > 0 ? [1] : []
    content {
      condition {
        age = var.lifecycle_delete_age_days
      }
      action {
        type = "Delete"
      }
    }
  }
}

resource "google_service_account" "pgbackrest" {
  project      = var.project_id
  account_id   = var.service_account_id
  display_name = var.service_account_display_name
}

resource "google_storage_bucket_iam_member" "repo_object_admin" {
  bucket = google_storage_bucket.repo.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.pgbackrest.email}"
}
