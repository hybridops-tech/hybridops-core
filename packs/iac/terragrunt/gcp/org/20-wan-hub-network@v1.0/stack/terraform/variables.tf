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

variable "network_name" {
  type = string
}

variable "routing_mode" {
  type    = string
  default = "GLOBAL"
}

variable "subnet_core_name" {
  type = string
}

variable "subnet_core_cidr" {
  type = string
}

variable "subnet_workloads_name" {
  type = string
}

variable "subnet_workloads_cidr" {
  type = string
}

variable "enable_iap_ssh" {
  type    = bool
  default = true
}

variable "internal_allow_cidrs" {
  type    = list(string)
  default = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"]
}

variable "labels" {
  type    = map(string)
  default = {}
}
