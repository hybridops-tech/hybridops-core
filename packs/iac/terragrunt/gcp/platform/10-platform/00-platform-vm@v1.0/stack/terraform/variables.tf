variable "name_prefix" {
  type    = string
  default = ""
}

variable "context_id" {
  type    = string
  default = ""
}

variable "zone" {
  type = string
}

variable "network" {
  type    = string
  default = "default"
}

variable "subnetwork" {
  type    = string
  default = ""
}

variable "network_project_id" {
  type    = string
  default = ""
}

variable "machine_type" {
  type    = string
  default = "e2-standard-2"
}

variable "boot_disk_size_gb" {
  type    = number
  default = 40
}

variable "boot_disk_type" {
  type    = string
  default = "pd-balanced"
}

variable "source_image_project" {
  type    = string
  default = "rocky-linux-cloud"
}

variable "source_image_family" {
  type    = string
  default = "rocky-linux-9"
}

variable "assign_public_ip" {
  type    = bool
  default = false
}

variable "enable_nested_virtualization" {
  type    = bool
  default = false
}

variable "ssh_username" {
  type    = string
  default = "opsadmin"
}

variable "ssh_keys" {
  type    = list(string)
  default = []
}

variable "tags" {
  type    = list(string)
  default = []
}

variable "labels" {
  type    = map(string)
  default = {}
}

variable "vms" {
  type = map(
    object(
      {
        role                         = optional(string)
        machine_type                 = optional(string)
        zone                         = optional(string)
        boot_disk_size_gb            = optional(number)
        boot_disk_type               = optional(string)
        source_image_project         = optional(string)
        source_image_family          = optional(string)
        assign_public_ip             = optional(bool)
        enable_nested_virtualization = optional(bool)
        tags                         = optional(list(string))
        labels                       = optional(map(string))
      }
    )
  )
}
