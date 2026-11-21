resource "aws_lb" "app_alb" {
  # checkov:skip=CKV2_AWS_76:Managed WAF rules run in count mode to avoid blocking application traffic.
  name               = "${var.PROJECT_NAME}-alb"
  internal           = false
  load_balancer_type = "application"

  security_groups = [
    aws_security_group.alb_sg.id
  ]

  subnets = [
    for subnet in aws_subnet.public_sn : subnet.id
  ]
  drop_invalid_header_fields = true
  enable_deletion_protection = true

  access_logs {
    bucket  = aws_s3_bucket.access_logs.id
    prefix  = "alb"
    enabled = true
  }

  depends_on = [aws_s3_bucket_policy.access_logs, aws_s3_bucket_server_side_encryption_configuration.access_logs]

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name = "${var.PROJECT_NAME}-alb"
  }
}

resource "aws_lb_target_group" "app_tg" {
  name        = "${var.PROJECT_NAME}-tg"
  port        = 80
  protocol    = "HTTP"
  target_type = "instance"
  vpc_id      = aws_vpc.vpc.id

  health_check {
    enabled             = true
    path                = "/api/health"
    protocol            = "HTTP"
    port                = "traffic-port"
    matcher             = "200"
    interval            = 30
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 2
  }

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name = "${var.PROJECT_NAME}-tg"
  }
}

resource "aws_lb_target_group_attachment" "app_attachment" {
  for_each = aws_instance.app

  target_group_arn = aws_lb_target_group.app_tg.arn
  target_id        = each.value.id
  port             = 80
}

moved {
  from = aws_lb_listener.http
  to   = aws_lb_listener.http[0]
}

resource "aws_lb_listener" "http" {
  count = var.ACM_CERTIFICATE_ARN != null ? 1 : 0

  load_balancer_arn = aws_lb.app_alb.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "redirect"

    redirect {
      port        = "443"
      protocol    = "HTTPS"
      status_code = "HTTP_301"
    }
  }
}

resource "aws_lb_listener" "https" {
  count = var.ACM_CERTIFICATE_ARN != null ? 1 : 0

  load_balancer_arn = aws_lb.app_alb.arn
  port              = 443
  protocol          = "HTTPS"

  certificate_arn = var.ACM_CERTIFICATE_ARN
  ssl_policy      = "ELBSecurityPolicy-TLS13-1-2-2021-06"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.app_tg.arn
  }
}
