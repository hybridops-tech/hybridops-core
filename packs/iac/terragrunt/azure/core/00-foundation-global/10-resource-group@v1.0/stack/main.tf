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

variable "resource_group_name" {
  type    = string
  default = ""
}

variable "location" {
  type    = string
  default = ""
}

variable "tags" {
  type    = map(string)
  default = {}
}

locals {
  derived_name = lower(join("-", compact([trimspace(var.name_prefix), trimspace(var.context_id), "rg"])))

  effective_resource_group_name = trimspace(var.resource_group_name) != "" ? trimspace(var.resource_group_name) : local.derived_name
  effective_location            = trimspace(var.location) != "" ? trimspace(var.location) : "uksouth"
}

resource "azurerm_resource_group" "this" {
  name     = local.effective_resource_group_name
  location = local.effective_location
  tags     = var.tags
}

output "resource_group_id" {
  value = azurerm_resource_group.this.id
}

output "resource_group_name" {
  value = azurerm_resource_group.this.name
}

output "location" {
  value = azurerm_resource_group.this.location
}
