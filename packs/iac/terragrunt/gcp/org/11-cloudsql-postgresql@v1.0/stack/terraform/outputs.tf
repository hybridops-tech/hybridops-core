output "project_id" {
  value       = var.project_id
  description = "GCP project id."
}

output "region" {
  value       = google_sql_database_instance.instance.region
  description = "Cloud SQL region."
}

output "instance_name" {
  value       = google_sql_database_instance.instance.name
  description = "Cloud SQL instance name."
}

output "connection_name" {
  value       = google_sql_database_instance.instance.connection_name
  description = "Cloud SQL connection name."
}

output "private_ip_address" {
  value       = google_sql_database_instance.instance.private_ip_address
  description = "Private IP address."
}

output "public_ip_address" {
  value       = google_sql_database_instance.instance.public_ip_address
  description = "Public IPv4 address, when enabled."
}

output "availability_type" {
  value       = google_sql_database_instance.instance.settings[0].availability_type
  description = "Cloud SQL availability type."
}

output "database_version" {
  value       = google_sql_database_instance.instance.database_version
  description = "Database version token."
}

output "db_provider" {
  value       = "gcp"
  description = "Managed database provider."
}

output "db_engine" {
  value       = "postgresql"
  description = "Managed database engine."
}

output "db_host" {
  value       = coalesce(google_sql_database_instance.instance.private_ip_address, google_sql_database_instance.instance.public_ip_address)
  description = "Preferred database host address."
}

output "db_port" {
  value       = 5432
  description = "Managed PostgreSQL port."
}

output "cap_db_managed_postgresql" {
  value       = "ready"
  description = "Capability marker for managed PostgreSQL readiness."
}
