output "app_public_ips" {
  description = "Public IP addresses of application instances"

  value = {
    for name, instance in aws_instance.app :
    name => instance.public_ip
  }
}


output "app_private_ips" {
  description = "Private IP addresses of application instances"

  value = {
    for name, instance in aws_instance.app :
    name => instance.private_ip
  }
}

output "app_instance_ids" {
  description = "Application instance IDs used for rolling ALB registration"
  value       = { for name, instance in aws_instance.app : name => instance.id }
}

output "app_target_group_arn" {
  description = "Target group used for rolling deployments"
  value       = aws_lb_target_group.app_tg.arn
}


output "monitoring_public_ip" {
  description = "Public IP address of monitoring instance"
  value       = aws_instance.monitoring.public_ip
}


output "monitoring_private_ip" {
  description = "Private IP address of monitoring instance"
  value       = aws_instance.monitoring.private_ip
}


output "vpc_id" {
  description = "VPC ID"
  value       = aws_vpc.vpc.id
}


output "alb_dns_name" {
  description = "AWS-generated ALB DNS name"
  value       = aws_lb.app_alb.dns_name
}


output "app_url" {
  description = "Application URL"

  value = var.USE_DOMAIN ? (
    "http://${aws_route53_record.app[0].fqdn}"
    ) : (
    "http://${aws_lb.app_alb.dns_name}"
  )
}


output "alb_zone_id" {
  description = "ALB hosted zone ID for Route 53 alias records"
  value       = aws_lb.app_alb.zone_id
}


output "custom_domain" {
  description = "Custom application domain, if enabled"
  value       = var.USE_DOMAIN ? aws_route53_record.app[0].fqdn : null
}


output "database_public_ips" {
  description = "Public IP addresses of database instances"

  value = {
    for name, instance in aws_instance.database :
    name => instance.public_ip
  }
}


output "database_private_ips" {
  description = "Private IP addresses of database instances"

  value = {
    for name, instance in aws_instance.database :
    name => instance.private_ip
  }
}


output "redis_public_ips" {
  description = "Public IP addresses of Redis instances"

  value = {
    for name, instance in aws_instance.redis :
    name => instance.public_ip
  }
}


output "redis_private_ips" {
  description = "Private IP addresses of Redis instances"

  value = {
    for name, instance in aws_instance.redis :
    name => instance.private_ip
  }
}

output "database_volume_ids" {
  description = "EBS volume ID for each database host"
  value       = { for name, volume in aws_ebs_volume.database : name => volume.id }
}

output "uploads_bucket" {
  description = "Uploads bucket used by the application"
  value       = aws_s3_bucket.uploads.bucket
}
