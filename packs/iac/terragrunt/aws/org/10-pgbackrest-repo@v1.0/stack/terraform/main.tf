locals {
  base_tags = merge(
    {
      managed_by = "hyops"
      module_ref = "org/aws/pgbackrest-repo"
    },
    var.tags,
  )

  use_kms = lower(trimspace(var.sse_algorithm)) == "aws:kms"
}

resource "aws_s3_bucket" "repo" {
  bucket        = var.bucket_name
  force_destroy = var.force_destroy

  tags = local.base_tags
}

resource "aws_s3_bucket_public_access_block" "repo" {
  bucket = aws_s3_bucket.repo.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "repo" {
  bucket = aws_s3_bucket.repo.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "repo" {
  bucket = aws_s3_bucket.repo.id

  versioning_configuration {
    status = var.versioning_enabled ? "Enabled" : "Suspended"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "repo" {
  bucket = aws_s3_bucket.repo.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = var.sse_algorithm
      kms_master_key_id = local.use_kms ? var.kms_key_arn : null
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "repo" {
  count  = var.lifecycle_delete_age_days > 0 ? 1 : 0
  bucket = aws_s3_bucket.repo.id

  rule {
    id     = "delete-old-objects"
    status = "Enabled"

    filter {}

    expiration {
      days = var.lifecycle_delete_age_days
    }
  }
}

data "aws_iam_policy_document" "bucket_tls_only" {
  statement {
    sid    = "DenyInsecureTransport"
    effect = "Deny"

    actions   = ["s3:*"]
    resources = [aws_s3_bucket.repo.arn, "${aws_s3_bucket.repo.arn}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }
}

resource "aws_s3_bucket_policy" "repo" {
  bucket = aws_s3_bucket.repo.id
  policy = data.aws_iam_policy_document.bucket_tls_only.json
}

resource "aws_iam_user" "pgbackrest" {
  name = var.iam_user_name
  tags = local.base_tags
}

data "aws_iam_policy_document" "pgbackrest_user" {
  statement {
    sid    = "ListRepoBucket"
    effect = "Allow"

    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.repo.arn]
  }

  statement {
    sid    = "RepoObjectReadWrite"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
      "s3:ListBucketMultipartUploads",
      "s3:ListMultipartUploadParts"
    ]
    resources = ["${aws_s3_bucket.repo.arn}/*"]
  }
}

resource "aws_iam_user_policy" "pgbackrest_user" {
  name   = "pgbackrest-repo-access"
  user   = aws_iam_user.pgbackrest.name
  policy = data.aws_iam_policy_document.pgbackrest_user.json
}
