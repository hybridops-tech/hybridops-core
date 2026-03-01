variable "name_prefix" {
  type    = string
  default = ""
}

variable "context_id" {
  type    = string
  default = ""
}

variable "location" {
  type = string
}

variable "home_location" {
  type = string
}

variable "network_zone" {
  type = string
}

variable "server_type" {
  type = string
}

variable "image" {
  type = string
}

variable "edge01_name" {
  type = string
}

variable "edge02_name" {
  type = string
}

variable "ssh_key_name" {
  type = string
}

variable "ssh_public_key" {
  type      = string
  sensitive = true
}

variable "firewall_name" {
  type = string
}

variable "floating_ip_name" {
  type = string
}

variable "floating_ip_type" {
  type    = string
  default = "ipv4"
}

variable "private_network_name" {
  type = string
}

variable "private_network_cidr" {
  type = string
}

variable "edge01_private_ip" {
  type = string
}

variable "edge02_private_ip" {
  type = string
}

variable "assign_floating_to" {
  type    = string
  default = "edge01"
}

variable "ssh_source_cidrs" {
  type    = list(string)
  default = ["0.0.0.0/0"]
}

variable "ipsec_source_cidrs" {
  type    = list(string)
  default = ["0.0.0.0/0"]
}

variable "labels" {
  type    = map(string)
  default = {}
}
