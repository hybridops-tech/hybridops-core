variable "name_prefix" {
  type    = string
  default = ""
}

variable "context_id" {
  type    = string
  default = ""
}

variable "project_id" {
  type    = string
  default = ""
}

variable "network" {
  type    = string
  default = "default"
}

variable "rules" {
  type = list(
    object({
      name_suffix   = string
      description   = optional(string, "")
      direction     = optional(string, "INGRESS")
      priority      = optional(number, 1000)
      source_ranges = optional(list(string), [])
      destination_ranges = optional(list(string), [])
      target_tags   = optional(list(string), [])
      allow = list(
        object({
          protocol = string
          ports    = optional(list(string), [])
        })
      )
    })
  )
  default = []
}
