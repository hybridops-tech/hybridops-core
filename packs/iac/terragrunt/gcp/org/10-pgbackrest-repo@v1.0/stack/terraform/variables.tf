variable "project_id" {
  type        = string
  description = "GCP project id where the bucket and service account will be created."
}

variable "bucket_name" {
  type        = string
  description = "Globally unique GCS bucket name."
}

variable "location" {
  type        = string
  description = "Bucket location (e.g. EU, US, europe-west2)."
  default     = "EU"
}

variable "storage_class" {
  type        = string
  description = "Bucket storage class (STANDARD, NEARLINE, COLDLINE, ARCHIVE)."
  default     = "STANDARD"
}

variable "uniform_bucket_level_access" {
  type        = bool
  description = "Enforce uniform bucket-level access (recommended)."
  default     = true
}

variable "versioning_enabled" {
  type        = bool
  description = "Enable object versioning."
  default     = false
}

variable "lifecycle_delete_age_days" {
  type        = number
  description = "If > 0, delete objects older than this many days (safety net; pgBackRest retention is still authoritative)."
  default     = 0
}

variable "service_account_id" {
  type        = string
  description = "Service account id (account_id) to create for pgBackRest repo access."
  default     = "pgbackrest"
}

variable "service_account_display_name" {
  type        = string
  description = "Display name for the pgBackRest repo service account."
  default     = "pgBackRest Repo"
}

