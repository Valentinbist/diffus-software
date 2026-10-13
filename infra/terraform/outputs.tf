output "vm_ipv4" {
  description = "The VM's address as reported by the guest agent. Open http://<this>:8000 from the LAN right after first boot."
  # Index 0 is the loopback interface.
  value = try(proxmox_virtual_environment_vm.diffus.ipv4_addresses[1][0], null)
}

output "tunnel_id" {
  description = "Id of the Cloudflare tunnel."
  value       = cloudflare_zero_trust_tunnel_cloudflared.diffus.id
}

output "ci_access_client_id" {
  description = "GitHub secret CF_ACCESS_CLIENT_ID."
  value       = cloudflare_zero_trust_access_service_token.ci.client_id
}

output "ci_access_client_secret" {
  description = "GitHub secret CF_ACCESS_CLIENT_SECRET."
  value       = cloudflare_zero_trust_access_service_token.ci.client_secret
  sensitive   = true
}
