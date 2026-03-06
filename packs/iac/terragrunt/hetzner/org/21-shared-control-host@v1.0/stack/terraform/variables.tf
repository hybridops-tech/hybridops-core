variable "name_prefix" {
  type    = string
  default = ""
}

variable "context_id" {
  type    = string
  default = ""
}

variable "private_network_id" {
  type = string
}

variable "private_network_cidr" {
  type    = string
  default = ""
}

variable "location" {
  type = string
}

variable "server_type" {
  type = string
}

variable "image" {
  type = string
}

variable "host_name" {
  type = string
}

variable "private_ip" {
  type = string
}

variable "ssh_username" {
  type = string
}

variable "ssh_keys" {
  type = list(string)
}

variable "public_ipv4_enabled" {
  type    = bool
  default = true
}

variable "public_ipv6_enabled" {
  type    = bool
  default = false
}

variable "firewall_enabled" {
  type    = bool
  default = true
}

variable "firewall_name" {
  type = string
}

variable "ssh_source_cidrs" {
  type    = list(string)
  default = ["0.0.0.0/0"]
}

variable "labels" {
  type    = map(string)
  default = {}
}
