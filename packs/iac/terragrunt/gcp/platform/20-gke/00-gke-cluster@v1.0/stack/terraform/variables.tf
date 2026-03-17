variable "name_prefix" {
  type    = string
  default = ""
}

variable "context_id" {
  type    = string
  default = ""
}

variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "cluster_name" {
  type = string
}

variable "location" {
  type = string
}

variable "network" {
  type = string
}

variable "subnetwork" {
  type = string
}

variable "pods_secondary_range_name" {
  type = string
}

variable "services_secondary_range_name" {
  type = string
}

variable "release_channel" {
  type    = string
  default = "REGULAR"
}

variable "enable_private_nodes" {
  type    = bool
  default = true
}

variable "enable_private_endpoint" {
  type    = bool
  default = false
}

variable "master_ipv4_cidr_block" {
  type    = string
  default = "172.31.255.240/28"
}
variable "master_authorized_networks" {
  type = list(object({
    cidr         = string
    display_name = optional(string)
  }))
  default = []
}
variable "deletion_protection" {
  type    = bool
  default = false
}

variable "node_pool_name" {
  type    = string
  default = "default-pool"
}

variable "node_count" {
  type    = number
  default = 2
}

variable "machine_type" {
  type    = string
  default = "e2-standard-4"
}

variable "disk_size_gb" {
  type    = number
  default = 50
}

variable "node_locations" {
  type    = list(string)
  default = []
}

variable "node_service_account" {
  type    = string
  default = ""
}

variable "node_service_account_id" {
  type    = string
  default = ""
}

variable "tags" {
  type    = list(string)
  default = []
}

variable "labels" {
  type    = map(string)
  default = {}
}
