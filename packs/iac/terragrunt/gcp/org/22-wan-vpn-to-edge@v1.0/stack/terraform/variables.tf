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

variable "ha_vpn_gateway_name" {
  type = string
}

variable "external_vpn_gateway_name" {
  type = string
}

variable "peer_ip_a" {
  type = string
}

variable "peer_ip_b" {
  type = string
}

variable "shared_secret_a" {
  type      = string
  sensitive = true
}

variable "shared_secret_b" {
  type      = string
  sensitive = true
}

variable "peer_asn" {
  type = number
}

variable "tunnel_a_inside_cidr" {
  type = string
}

variable "tunnel_b_inside_cidr" {
  type = string
}

variable "advertised_prefixes" {
  type = list(string)
}

variable "advertised_route_priority" {
  type    = number
  default = 100
}
