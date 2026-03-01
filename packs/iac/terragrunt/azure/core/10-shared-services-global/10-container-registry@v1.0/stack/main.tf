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

variable "registry_name" {
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

variable "sku" {
  type    = string
  default = "Standard"

  validation {
    condition     = contains(["Basic", "Standard", "Premium"], var.sku)
    error_message = "inputs.sku must be one of: Basic, Standard, Premium"
  }
}

variable "admin_enabled" {
  type    = bool
  default = false
}

variable "public_network_access_enabled" {
  type    = bool
  default = true
}

variable "zone_redundancy_enabled" {
  type    = bool
  default = false
}

variable "tags" {
  type    = map(string)
  default = {}
}

locals {
  # Azure Container Registry name must be 5-50 chars, lowercase alphanumeric only.
  derived_registry_name_raw = lower(replace(join("", compact([trimspace(var.name_prefix), trimspace(var.context_id), "acr"])), "/[^a-z0-9]/", ""))
  derived_registry_name     = length(local.derived_registry_name_raw) >= 5 ? substr(local.derived_registry_name_raw, 0, 50) : "hyopsacr01"

  effective_registry_name = trimspace(var.registry_name) != "" ? lower(trimspace(var.registry_name)) : local.derived_registry_name
  effective_location      = trimspace(var.location) != "" ? trimspace(var.location) : "uksouth"
}

resource "azurerm_container_registry" "this" {
  name                          = local.effective_registry_name
  resource_group_name           = trimspace(var.resource_group_name)
  location                      = local.effective_location
  sku                           = var.sku
  admin_enabled                 = var.admin_enabled
  public_network_access_enabled = var.public_network_access_enabled
  zone_redundancy_enabled       = var.zone_redundancy_enabled
  tags                          = var.tags
}

output "registry_id" {
  value = azurerm_container_registry.this.id
}

output "registry_name" {
  value = azurerm_container_registry.this.name
}

output "login_server" {
  value = azurerm_container_registry.this.login_server
}

output "admin_username" {
  value = azurerm_container_registry.this.admin_username
}

output "admin_password" {
  value     = azurerm_container_registry.this.admin_password
  sensitive = true
}
