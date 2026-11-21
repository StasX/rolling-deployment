resource "aws_wafv2_web_acl" "app" {
  # checkov:skip=CKV_AWS_192:The managed Log4j rules record matches in count mode during rollout.
  name  = "${var.PROJECT_NAME}-app"
  scope = "REGIONAL"

  default_action {
    allow {}
  }

  rule {
    name     = "aws-common-rules"
    priority = 0

    override_action {
      count {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesCommonRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = false
      metric_name                = "aws-common-rules"
      sampled_requests_enabled   = false
    }
  }

  rule {
    name     = "aws-known-bad-inputs"
    priority = 1

    override_action {
      count {}
    }

    statement {
      managed_rule_group_statement {
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
        vendor_name = "AWS"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = false
      metric_name                = "aws-known-bad-inputs"
      sampled_requests_enabled   = false
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = false
    metric_name                = "${var.PROJECT_NAME}-app"
    sampled_requests_enabled   = false
  }
}

resource "aws_wafv2_web_acl_association" "app" {
  resource_arn = aws_lb.app_alb.arn
  web_acl_arn  = aws_wafv2_web_acl.app.arn
}

resource "aws_cloudwatch_log_group" "waf" {
  # checkov:skip=CKV_AWS_158:Use default CloudWatch Logs encryption for operational telemetry.
  # checkov:skip=CKV_AWS_338:Retain operational telemetry for 30 days to limit storage costs.
  name              = "aws-waf-logs-${var.PROJECT_NAME}"
  retention_in_days = 30
}

resource "aws_wafv2_web_acl_logging_configuration" "app" {
  resource_arn            = aws_wafv2_web_acl.app.arn
  log_destination_configs = [aws_cloudwatch_log_group.waf.arn]

  logging_filter {
    default_behavior = "DROP"

    filter {
      behavior    = "KEEP"
      requirement = "MEETS_ANY"

      condition {
        action_condition {
          action = "COUNT"
        }
      }

      condition {
        action_condition {
          action = "EXCLUDED_AS_COUNT"
        }
      }
    }
  }

  redacted_fields {
    query_string {}
  }

  dynamic "redacted_fields" {
    for_each = toset(["authorization", "cookie"])
    content {
      single_header {
        name = redacted_fields.value
      }
    }
  }
}
