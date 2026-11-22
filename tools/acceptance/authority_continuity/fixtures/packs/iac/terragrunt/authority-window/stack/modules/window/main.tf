terraform {
  required_version = ">= 1.5.0"
}

variable "barrier_dir" {
  description = "Existing absolute directory used for the operation barrier."
  type        = string

  validation {
    condition     = startswith(var.barrier_dir, "/") && length(var.barrier_dir) <= 4096
    error_message = "barrier_dir must be an absolute path no longer than 4096 characters."
  }
}

variable "run_nonce" {
  description = "Unique identifier that forces a fresh operation window."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$", var.run_nonce))
    error_message = "run_nonce must contain 1-64 letters, numbers, dots, underscores or hyphens."
  }
}

variable "timeout_s" {
  description = "Maximum time to wait for the benchmark runner to release the operation."
  type        = number

  validation {
    condition     = var.timeout_s >= 5 && var.timeout_s <= 300 && floor(var.timeout_s) == var.timeout_s
    error_message = "timeout_s must be a whole number from 5 to 300."
  }
}

resource "terraform_data" "authority_window" {
  input = {
    run_nonce = var.run_nonce
  }

  triggers_replace = [var.run_nonce]

  provisioner "local-exec" {
    interpreter = ["python3", "${path.module}/window.py"]
    command = jsonencode({
      barrier_dir = var.barrier_dir
      run_nonce   = var.run_nonce
      timeout_s   = var.timeout_s
    })
  }
}

output "run_nonce" {
  value = terraform_data.authority_window.output.run_nonce
}
