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
  type = string
}

variable "router_name" {
  type = string
}

variable "bgp_asn" {
  type = number
}
