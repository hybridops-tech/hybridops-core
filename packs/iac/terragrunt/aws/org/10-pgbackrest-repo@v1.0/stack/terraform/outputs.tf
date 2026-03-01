# Normalized cross-provider outputs
output "repo_backend" {
  value       = "s3"
  description = "Repository backend type for pgBackRest (normalized contract)."
}

output "repo_provider" {
  value       = "aws"
  description = "Cloud provider for this repository module (normalized contract)."
}

output "repo_bucket_name" {
  value       = aws_s3_bucket.repo.bucket
  description = "Repository bucket name (normalized contract)."
}

output "repo_region" {
  value       = var.aws_region
  description = "Repository region (normalized contract)."
}

output "repo_principal_type" {
  value       = "iam_user"
  description = "Principal type used by backup clients (normalized contract)."
}

output "repo_principal_name" {
  value       = aws_iam_user.pgbackrest.name
  description = "Principal identity used by backup clients (normalized contract)."
}

output "repo_credential_create_hint" {
  value       = "aws iam create-access-key --user-name ${aws_iam_user.pgbackrest.name}"
  description = "Operator hint to mint workload credentials out-of-band (normalized contract)."
}

# Legacy aliases retained for compatibility
output "bucket_name" {
  value       = aws_s3_bucket.repo.bucket
  description = "S3 bucket name for pgBackRest repository."
}

output "aws_region" {
  value       = var.aws_region
  description = "AWS region configured for this repository."
}

output "iam_user_name" {
  value       = aws_iam_user.pgbackrest.name
  description = "IAM user with repository read/write permissions."
}

output "access_key_hint" {
  value = "aws iam create-access-key --user-name ${aws_iam_user.pgbackrest.name}"
}
