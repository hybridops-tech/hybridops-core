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

variable "network_self_link" {
  type    = string
  default = ""
}

variable "router_name" {
  type = string
}

variable "nat_name" {
  type = string
}

variable "subnetwork_self_links" {
  type = list(string)
}

variable "subnetwork_source_ip_ranges_to_nat" {
  type = string
}

variable "auto_allocate_external_ips" {
  type = bool
}

variable "nat_ip_self_links" {
  type    = list(string)
  default = []
}

variable "min_ports_per_vm" {
  type = number
}

variable "enable_endpoint_independent_mapping" {
  type = bool
}

variable "log_filter" {
  type = string
}
