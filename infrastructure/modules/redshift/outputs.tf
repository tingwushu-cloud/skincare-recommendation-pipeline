###############################################################
# modules/redshift/outputs.tf
###############################################################

output "workgroup_name" {
  description = "Redshift Serverless workgroup name"
  value       = aws_redshiftserverless_workgroup.main.workgroup_name
}

output "namespace_name" {
  description = "Redshift Serverless namespace name"
  value       = aws_redshiftserverless_namespace.main.namespace_name
}

output "endpoint" {
  description = "Redshift Serverless endpoint address"
  value       = aws_redshiftserverless_workgroup.main.endpoint
}
