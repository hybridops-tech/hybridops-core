terraform {
  required_version = ">= 1.5.0"
}

variable "message" {
  type = string
}

output "echo" {
  value = var.message
}
