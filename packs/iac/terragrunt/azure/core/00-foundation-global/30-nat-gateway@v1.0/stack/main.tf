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

variable "nat_gateway_name" {
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

variable "sku_name" {
  type    = string
  default = "Standard"
}

variable "idle_timeout_in_minutes" {
  type    = number
  default = 4

  validation {
    condition     = var.idle_timeout_in_minutes >= 4 && var.idle_timeout_in_minutes <= 120
    error_message = "inputs.idle_timeout_in_minutes must be between 4 and 120"
  }
}

variable "zones" {
  type    = list(string)
  default = []
}

variable "tags" {
  type    = map(string)
  default = {}
}

locals {
  derived_name = lower(join("-", compact([trimspace(var.name_prefix), trimspace(var.context_id), "natgw"])))

  effective_nat_gateway_name = trimspace(var.nat_gateway_name) != "" ? trimspace(var.nat_gateway_name) : local.derived_name
  effective_location         = trimspace(var.location) != "" ? trimspace(var.location) : "uksouth"
}

resource "azurerm_public_ip" "this" {
  name                = "${local.effective_nat_gateway_name}-pip"
  resource_group_name = trimspace(var.resource_group_name)
  location            = local.effective_location
  allocation_method   = "Static"
  sku                 = "Standard"
  zones               = length(var.zones) > 0 ? var.zones : null
  tags                = var.tags
}

resource "azurerm_nat_gateway" "this" {
  name                    = local.effective_nat_gateway_name
  resource_group_name     = trimspace(var.resource_group_name)
  location                = local.effective_location
  sku_name                = var.sku_name
  idle_timeout_in_minutes = var.idle_timeout_in_minutes
  zones                   = length(var.zones) > 0 ? var.zones : null
  tags                    = var.tags
}

resource "azurerm_nat_gateway_public_ip_association" "this" {
  nat_gateway_id       = azurerm_nat_gateway.this.id
  public_ip_address_id = azurerm_public_ip.this.id
}

output "nat_gateway_id" {
  value = azurerm_nat_gateway.this.id
}

output "nat_gateway_name" {
  value = azurerm_nat_gateway.this.name
}

output "public_ip_id" {
  value = azurerm_public_ip.this.id
}

output "public_ip_address" {
  value = azurerm_public_ip.this.ip_address
}
