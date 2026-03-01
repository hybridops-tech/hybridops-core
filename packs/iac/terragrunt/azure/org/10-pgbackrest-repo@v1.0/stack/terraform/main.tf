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
  default = "uksouth"
}

variable "storage_account_name" {
  type    = string
  default = ""
}

variable "container_name" {
  type    = string
  default = "pgbackrest"
}

variable "account_tier" {
  type    = string
  default = "Standard"
}

variable "account_replication_type" {
  type    = string
  default = "LRS"
}

variable "access_tier" {
  type    = string
  default = "Hot"
}

variable "versioning_enabled" {
  type    = bool
  default = true
}

variable "lifecycle_delete_age_days" {
  type    = number
  default = 0
}

variable "shared_access_key_enabled" {
  type    = bool
  default = true
}

variable "public_network_access_enabled" {
  type    = bool
  default = true
}

variable "min_tls_version" {
  type    = string
  default = "TLS1_2"
}

variable "tags" {
  type    = map(string)
  default = {}
}

locals {
  derived_rg_name = lower(join("-", compact([trimspace(var.name_prefix), trimspace(var.context_id), "pgbackrest-rg"])))
  effective_resource_group_name = trimspace(var.resource_group_name) != "" ? trimspace(var.resource_group_name) : local.derived_rg_name

  sa_seed_raw = lower(join("", compact([trimspace(var.name_prefix), trimspace(var.context_id), "pgbackrest"])))
  sa_seed     = replace(local.sa_seed_raw, "/[^a-z0-9]/", "")
  derived_sa  = substr(local.sa_seed != "" ? local.sa_seed : "hyopspgbackrest", 0, 24)
  effective_storage_account_name = trimspace(var.storage_account_name) != "" ? lower(trimspace(var.storage_account_name)) : local.derived_sa

  effective_container_name = lower(trimspace(var.container_name))
}

resource "azurerm_resource_group" "this" {
  name     = local.effective_resource_group_name
  location = var.location
  tags     = var.tags
}

resource "azurerm_storage_account" "this" {
  name                     = local.effective_storage_account_name
  resource_group_name      = azurerm_resource_group.this.name
  location                 = azurerm_resource_group.this.location
  account_tier             = var.account_tier
  account_replication_type = var.account_replication_type
  access_tier              = var.access_tier

  min_tls_version                 = var.min_tls_version
  shared_access_key_enabled       = var.shared_access_key_enabled
  public_network_access_enabled   = var.public_network_access_enabled
  allow_nested_items_to_be_public = false

  blob_properties {
    versioning_enabled = var.versioning_enabled
  }

  tags = var.tags
}

resource "azurerm_storage_container" "repo" {
  name                  = local.effective_container_name
  storage_account_name  = azurerm_storage_account.this.name
  container_access_type = "private"
}

resource "azurerm_storage_management_policy" "repo" {
  count = var.lifecycle_delete_age_days > 0 ? 1 : 0

  storage_account_id = azurerm_storage_account.this.id

  rule {
    name    = "delete-old-blobs"
    enabled = true

    filters {
      blob_types = ["blockBlob"]
    }

    actions {
      base_blob {
        delete_after_days_since_modification_greater_than = var.lifecycle_delete_age_days
      }
    }
  }
}

# Normalized cross-provider outputs
output "repo_backend" {
  value       = "azure"
  description = "Repository backend type for pgBackRest (normalized contract)."
}

output "repo_provider" {
  value       = "azure"
  description = "Cloud provider for this repository module (normalized contract)."
}

output "repo_bucket_name" {
  value       = azurerm_storage_container.repo.name
  description = "Repository bucket/container name (normalized contract)."
}

output "repo_region" {
  value       = azurerm_storage_account.this.location
  description = "Repository region/location (normalized contract)."
}

output "repo_principal_type" {
  value       = var.shared_access_key_enabled ? "storage_account_key" : "azure_ad"
  description = "Principal type used by backup clients (normalized contract)."
}

output "repo_principal_name" {
  value       = azurerm_storage_account.this.name
  description = "Principal identity used by backup clients (normalized contract)."
}

output "repo_credential_create_hint" {
  value       = "az storage account keys list --resource-group ${azurerm_resource_group.this.name} --account-name ${azurerm_storage_account.this.name} --query '[0].value' -o tsv"
  description = "Operator hint to mint workload credentials out-of-band (normalized contract)."
}

# Azure aliases
output "resource_group_name" {
  value = azurerm_resource_group.this.name
}

output "storage_account_name" {
  value = azurerm_storage_account.this.name
}

output "container_name" {
  value = azurerm_storage_container.repo.name
}

output "account_key_hint" {
  value = "az storage account keys list --resource-group ${azurerm_resource_group.this.name} --account-name ${azurerm_storage_account.this.name} --query '[0].value' -o tsv"
}
