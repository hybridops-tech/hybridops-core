variable "aws_region" {
  type        = string
  description = "AWS region for S3/IAM resources."
}

variable "bucket_name" {
  type        = string
  description = "Globally-unique S3 bucket name for pgBackRest repository data."
}

variable "force_destroy" {
  type        = bool
  description = "If true, allows terraform destroy to remove non-empty bucket."
  default     = false
}

variable "versioning_enabled" {
  type        = bool
  description = "Enable bucket versioning."
  default     = true
}

variable "lifecycle_delete_age_days" {
  type        = number
  description = "If >0, delete objects older than this many days."
  default     = 0
}

variable "sse_algorithm" {
  type        = string
  description = "SSE algorithm: AES256 or aws:kms"
  default     = "AES256"
}

variable "kms_key_arn" {
  type        = string
  description = "KMS key ARN when sse_algorithm=aws:kms"
  default     = ""
}

variable "iam_user_name" {
  type        = string
  description = "IAM user name used by pgBackRest clients."
  default     = "pgbackrest"
}

variable "tags" {
  type        = map(string)
  description = "Optional tags to apply to managed resources."
  default     = {}
}
