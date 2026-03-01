terraform {
  required_version = ">= 1.6.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = ">= 3.100.0"
    }
  }
}

variable "name_prefix" {
  type    = string
  default = ""
}

variable "context_id" {
  type    = string
  default = ""
}

variable "vnet_name" {
  type    = string
  default = ""
}

variable "resource_group_name" {
  type    = string
  default = ""

  validation {
    condition     = trimspace(var.resource_group_name) != ""
    error_message = "inputs.resource_group_name must be a non-empty string"
  }
}

variable "location" {
  type    = string
  default = ""
}

variable "address_space" {
  type    = list(string)
  default = ["10.60.0.0/16"]

  validation {
    condition     = length(var.address_space) > 0
    error_message = "inputs.address_space must contain at least one CIDR"
  }
}

variable "dns_servers" {
  type    = list(string)
  default = []
}

variable "tags" {
  type    = map(string)
  default = {}
}

locals {
  derived_name = lower(join("-", compact([trimspace(var.name_prefix), trimspace(var.context_id), "vnet"])))

  effective_vnet_name = trimspace(var.vnet_name) != "" ? trimspace(var.vnet_name) : local.derived_name
  effective_location  = trimspace(var.location) != "" ? trimspace(var.location) : "uksouth"
}

resource "azurerm_virtual_network" "this" {
  name                = local.effective_vnet_name
  location            = local.effective_location
  resource_group_name = trimspace(var.resource_group_name)
  address_space       = var.address_space
  dns_servers         = length(var.dns_servers) > 0 ? var.dns_servers : null
  tags                = var.tags
}

output "vnet_id" {
  value = azurerm_virtual_network.this.id
}

output "vnet_name" {
  value = azurerm_virtual_network.this.name
}

output "resource_group_name" {
  value = azurerm_virtual_network.this.resource_group_name
}

output "location" {
  value = azurerm_virtual_network.this.location
}
