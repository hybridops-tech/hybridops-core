variable "name_prefix" {
  type    = string
  default = ""
}

variable "context_id" {
  type    = string
  default = ""
}

variable "network_zone" {
  type = string
}

variable "private_network_name" {
  type = string
}

variable "private_network_cidr" {
  type = string
}

variable "labels" {
  type    = map(string)
  default = {}
}
