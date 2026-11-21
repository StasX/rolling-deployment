# Laravel uploads storage

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "uploads" {
  # checkov:skip=CKV_AWS_144:This deployment has no cross-region recovery requirement for uploads.
  # checkov:skip=CKV_AWS_145:Uploads use SSE-S3 and require no customer-managed key.
  # checkov:skip=CKV2_AWS_62:The application does not consume S3 events.
  bucket = "${lower(var.PROJECT_NAME)}-uploads-${data.aws_caller_identity.current.account_id}"

  force_destroy = false

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name    = "${var.PROJECT_NAME}-uploads"
    Purpose = "${var.PROJECT_NAME}-images-storage"
  }
}

resource "aws_s3_bucket_public_access_block" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "uploads" {
  bucket = aws_s3_bucket.uploads.id

  rule {
    id     = "cleanup-old-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 90
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# Backups storage

resource "aws_s3_bucket" "db_backups" {
  # checkov:skip=CKV_AWS_144:This deployment retains database backups in one region.
  # checkov:skip=CKV_AWS_145:Database backups use SSE-S3 and require no customer-managed key.
  # checkov:skip=CKV2_AWS_62:The backup workflow does not consume S3 events.
  bucket        = "${lower(var.PROJECT_NAME)}-db-backups-${data.aws_caller_identity.current.account_id}"
  force_destroy = false

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name    = "${var.PROJECT_NAME}-db-backups"
    Purpose = "mariadb-galera-backups"
  }


}

resource "aws_s3_bucket_public_access_block" "db_backups" {
  bucket = aws_s3_bucket.db_backups.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "db_backups" {
  bucket = aws_s3_bucket.db_backups.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_versioning" "db_backups" {
  bucket = aws_s3_bucket.db_backups.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "db_backups" {
  bucket = aws_s3_bucket.db_backups.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "db_backups" {
  bucket = aws_s3_bucket.db_backups.id

  rule {
    id     = "delete-old-db-backups"
    status = "Enabled"

    filter {}

    expiration {
      days = 90
    }

    noncurrent_version_expiration {
      noncurrent_days = 90
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}
