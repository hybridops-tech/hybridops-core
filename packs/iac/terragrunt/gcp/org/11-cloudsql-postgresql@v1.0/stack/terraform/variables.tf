variable "project_id" {
  type        = string
  description = "GCP project id where the Cloud SQL instance will be created."
}

variable "region" {
  type        = string
  description = "GCP region for the Cloud SQL instance."
}

variable "instance_name" {
  type        = string
  description = "Cloud SQL instance name."
}

variable "database_version" {
  type        = string
  description = "Cloud SQL database version token, e.g. POSTGRES_16."
}

variable "edition" {
  type        = string
  description = "Cloud SQL edition (ENTERPRISE or ENTERPRISE_PLUS)."
}

variable "availability_type" {
  type        = string
  description = "Cloud SQL availability type (ZONAL or REGIONAL)."
}

variable "tier" {
  type        = string
  description = "Cloud SQL machine tier."
}

variable "disk_size_gb" {
  type        = number
  description = "Storage size in GiB."
}

variable "disk_type" {
  type        = string
  description = "Disk type (PD_SSD or PD_HDD)."
}

variable "backup_enabled" {
  type        = bool
  description = "Enable Cloud SQL automated backups."
  default     = true
}

variable "point_in_time_recovery_enabled" {
  type        = bool
  description = "Enable point-in-time recovery."
  default     = true
}

variable "deletion_protection" {
  type        = bool
  description = "Protect the instance from accidental deletion."
  default     = true
}

variable "private_network" {
  type        = string
  description = "VPC self link for private IP connectivity."
}

variable "network_project_id" {
  type        = string
  description = "Host project id that owns the VPC and private service access range."
  default     = ""
}

variable "manage_shared_vpc_attachment" {
  type        = bool
  description = "When true, attach the service project to the Shared VPC host project."
  default     = false
}

variable "ipv4_enabled" {
  type        = bool
  description = "Enable public IPv4 for the instance."
  default     = false
}

variable "create_private_service_connection" {
  type        = bool
  description = "Create private service access range and service networking connection."
  default     = true
}

variable "allocated_ip_range_name" {
  type        = string
  description = "Existing or managed private service access range name."
  default     = ""
}

variable "labels" {
  type        = map(string)
  description = "User labels for the instance."
  default     = {}
}

variable "database_flags" {
  type        = map(string)
  description = "Optional database flags."
  default     = {}
}
