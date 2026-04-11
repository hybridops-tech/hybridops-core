output "rule_names" {
  value = { for k, r in google_compute_firewall.rule : k => r.name }
}

output "rule_ids" {
  value = { for k, r in google_compute_firewall.rule : k => r.id }
}
