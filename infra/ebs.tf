resource "aws_ebs_volume" "database" {
  # checkov:skip=CKV_AWS_189:Volumes are encrypted. Switching existing volumes to a customer-managed key requires a data migration.
  for_each = local.database_instances

  availability_zone = aws_subnet.public_sn[each.value].availability_zone
  size              = 100
  type              = "gp3"
  encrypted         = true

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name = "${var.PROJECT_NAME}-${each.key}-database"
  }
}
