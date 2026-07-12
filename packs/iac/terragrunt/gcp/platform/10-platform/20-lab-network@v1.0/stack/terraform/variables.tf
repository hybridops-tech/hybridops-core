variable "name_prefix" {
  type    = string
  default = ""
}

variable "context_id" {
  type    = string
  default = ""
}

variable "project_id" {
  type    = string
  default = ""
}

variable "region" {
  type = string
}

variable "network_name" {
  type    = string
  default = "lab-network"
}

variable "routing_mode" {
  type    = string
  default = "REGIONAL"
}

variable "subnetwork_name" {
  type    = string
  default = "lab"
}

variable "subnetwork_cidr" {
  type    = string
  default = "10.80.0.0/24"
}

variable "enable_private_google_access" {
  type    = bool
  default = true
}

variable "enable_iap_ssh" {
  type    = bool
  default = true
}

variable "iap_source_cidrs" {
  type    = list(string)
  default = ["35.235.240.0/20"]
}

variable "iap_target_tags" {
  type    = list(string)
  default = ["allow-iap-ssh"]
}

variable "router_name" {
  type    = string
  default = "lab-router"
}

variable "nat_name" {
  type    = string
  default = "lab-nat"
}

variable "nat_min_ports_per_vm" {
  type    = number
  default = 64
}

variable "nat_enable_endpoint_independent_mapping" {
  type    = bool
  default = true
}

variable "nat_log_filter" {
  type    = string
  default = "ERRORS_ONLY"
}
