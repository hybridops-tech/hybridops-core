# config.plugins.hcl
# Global Packer plugin configuration
# Shared by all OS families (Ubuntu, Rocky, Windows)
#
# Maintainer: HybridOps.Studio
# Date: 2025-01-06

packer {
  required_version = ">= 1.11.0"

  required_plugins {
    proxmox = {
      version = ">= 1.2.3"
      source  = "github.com/hashicorp/proxmox"
    }
  }
}
