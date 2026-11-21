resource "aws_cloudwatch_log_group" "vpc_flow" {
  # checkov:skip=CKV_AWS_158:Use default CloudWatch Logs encryption for operational telemetry.
  # checkov:skip=CKV_AWS_338:Retain operational telemetry for 30 days to limit storage costs.
  name              = "/aws/vpc/${var.PROJECT_NAME}/flow"
  retention_in_days = 30
}

resource "aws_iam_role" "vpc_flow" {
  name = "${var.PROJECT_NAME}-vpc-flow-logs"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "vpc-flow-logs.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
      }
    }]
  })
}

resource "aws_iam_role_policy" "vpc_flow" {
  name = "write-vpc-flow-logs"
  role = aws_iam_role.vpc_flow.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.vpc_flow.arn}:log-stream:*"
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:DescribeLogStreams"]
        Resource = aws_cloudwatch_log_group.vpc_flow.arn
      },
      {
        Effect   = "Allow"
        Action   = "logs:DescribeLogGroups"
        Resource = "*"
      },
    ]
  })
}

resource "aws_flow_log" "vpc" {
  vpc_id               = aws_vpc.vpc.id
  traffic_type         = "ALL"
  log_destination_type = "cloud-watch-logs"
  log_destination      = aws_cloudwatch_log_group.vpc_flow.arn
  iam_role_arn         = aws_iam_role.vpc_flow.arn

  depends_on = [aws_iam_role_policy.vpc_flow]
}
