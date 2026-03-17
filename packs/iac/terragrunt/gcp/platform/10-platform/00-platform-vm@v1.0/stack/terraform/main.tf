locals {
  prefix_raw = join("-", compact([trimspace(var.name_prefix), trimspace(var.context_id)]))
  prefix_1   = lower(replace(local.prefix_raw, "/[^0-9a-z-]/", "-"))
  prefix_2   = replace(local.prefix_1, "/-+/", "-")
  prefix     = trim(local.prefix_2, "-")

  ssh_key_lines = [
    for k in var.ssh_keys :
    "${var.ssh_username}:${trimspace(k)}"
    if trimspace(k) != ""
  ]
  ssh_keys_metadata = length(local.ssh_key_lines) > 0 ? join("\n", local.ssh_key_lines) : ""

  vm_name_raw = {
    for k, _ in var.vms :
    k => (local.prefix != "" ? "${local.prefix}-${k}" : k)
  }

  vm_name_norm_1 = {
    for k, name in local.vm_name_raw :
    k => lower(replace(name, "/[^0-9a-z-]/", "-"))
  }
  vm_name_norm_2 = {
    for k, name in local.vm_name_norm_1 :
    k => trim(replace(name, "/-+/", "-"), "-")
  }
  vm_name_norm_3 = {
    for k, name in local.vm_name_norm_2 :
    k => (can(regex("^[a-z]", name)) ? name : "v-${name}")
  }
  vm_name_norm_4 = {
    for k, name in local.vm_name_norm_3 :
    k => trim(substr(name, 0, 63), "-")
  }
}

data "google_compute_image" "img" {
  for_each = var.vms

  family  = coalesce(try(each.value.source_image_family, null), var.source_image_family)
  project = coalesce(try(each.value.source_image_project, null), var.source_image_project)
}

resource "google_compute_instance" "vm" {
  for_each = var.vms

  name                      = local.vm_name_norm_4[each.key]
  zone                      = coalesce(try(each.value.zone, null), var.zone)
  machine_type              = coalesce(try(each.value.machine_type, null), var.machine_type)
  allow_stopping_for_update = true

  tags = distinct(compact(concat(
    var.tags,
    coalesce(try(each.value.tags, null), []),
    try(each.value.role, null) != null ? [lower(trimspace(each.value.role))] : []
  )))

  labels = merge(
    var.labels,
    coalesce(try(each.value.labels, null), {}),
    try(each.value.role, null) != null ? { role = lower(trimspace(each.value.role)) } : {}
  )

  boot_disk {
    initialize_params {
      image = data.google_compute_image.img[each.key].self_link
      size  = coalesce(try(each.value.boot_disk_size_gb, null), var.boot_disk_size_gb)
      type  = coalesce(try(each.value.boot_disk_type, null), var.boot_disk_type)
    }
  }

  advanced_machine_features {
    enable_nested_virtualization = coalesce(
      try(each.value.enable_nested_virtualization, null),
      var.enable_nested_virtualization,
    )
  }

  network_interface {
    network = (
      trimspace(var.network_project_id) != "" && trimspace(var.subnetwork) != ""
      ? null
      : var.network
    )
    subnetwork = trimspace(var.subnetwork) != "" ? var.subnetwork : null
    subnetwork_project = (
      trimspace(var.network_project_id) != "" && trimspace(var.subnetwork) != ""
      ? var.network_project_id
      : null
    )

    dynamic "access_config" {
      for_each = (coalesce(try(each.value.assign_public_ip, null), var.assign_public_ip) ? [1] : [])
      content {}
    }
  }

  metadata = merge(
    local.ssh_keys_metadata != "" ? { "ssh-keys" = local.ssh_keys_metadata } : {},
    { "block-project-ssh-keys" = "true" }
  )
}
