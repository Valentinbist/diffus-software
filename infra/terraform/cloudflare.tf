# --- tunnel ----------------------------------------------------------------
# Remote-managed: the ingress rules live here, and cloudflared on the VM only
# needs the run token. Nothing is open at home; cloudflared dials out.

resource "random_bytes" "tunnel_secret" {
  length = 32
}

resource "cloudflare_zero_trust_tunnel_cloudflared" "diffus" {
  account_id    = var.cloudflare_account_id
  name          = var.vm_name
  config_src    = "cloudflare"
  tunnel_secret = random_bytes.tunnel_secret.base64
}

resource "cloudflare_zero_trust_tunnel_cloudflared_config" "diffus" {
  account_id = var.cloudflare_account_id
  tunnel_id  = cloudflare_zero_trust_tunnel_cloudflared.diffus.id

  config = {
    # cloudflared runs on the VM itself, so localhost:80 is Coolify's Traefik
    # proxy, which routes by hostname to the app or the dashboard.
    ingress = [
      {
        hostname = var.app_hostname
        service  = "http://localhost:80"
      },
      {
        hostname = var.coolify_hostname
        service  = "http://localhost:80"
      },
      {
        service = "http_status:404"
      },
    ]
  }
}

data "cloudflare_zero_trust_tunnel_cloudflared_token" "diffus" {
  account_id = var.cloudflare_account_id
  tunnel_id  = cloudflare_zero_trust_tunnel_cloudflared.diffus.id
}

# --- DNS -------------------------------------------------------------------

resource "cloudflare_dns_record" "app" {
  zone_id = var.cloudflare_zone_id
  name    = var.app_hostname
  type    = "CNAME"
  content = "${cloudflare_zero_trust_tunnel_cloudflared.diffus.id}.cfargotunnel.com"
  proxied = true
  ttl     = 1 # 1 = automatic, the only value a proxied record accepts
}

resource "cloudflare_dns_record" "coolify" {
  zone_id = var.cloudflare_zone_id
  name    = var.coolify_hostname
  type    = "CNAME"
  content = "${cloudflare_zero_trust_tunnel_cloudflared.diffus.id}.cfargotunnel.com"
  proxied = true
  ttl     = 1
}

# --- Access: only the Coolify dashboard ------------------------------------
# The app is not behind Access: it has its own Basic auth and must stay
# reachable for Instagram (OAuth callback, image fetch).

# Used by GitHub Actions (scripts/coolify-deploy.sh) to reach the Coolify API.
resource "cloudflare_zero_trust_access_service_token" "ci" {
  account_id = var.cloudflare_account_id
  name       = "${var.vm_name}-ci"
}

resource "cloudflare_zero_trust_access_policy" "admins" {
  account_id = var.cloudflare_account_id
  name       = "${var.vm_name} admins"
  decision   = "allow"

  include = [for email in var.admin_emails : { email = { email = email } }]
}

# "non_identity" is what lets a service token (no login) through.
resource "cloudflare_zero_trust_access_policy" "ci" {
  account_id = var.cloudflare_account_id
  name       = "${var.vm_name} CI"
  decision   = "non_identity"

  include = [{ service_token = { token_id = cloudflare_zero_trust_access_service_token.ci.id } }]
}

resource "cloudflare_zero_trust_access_application" "coolify" {
  account_id = var.cloudflare_account_id
  name       = "${var.vm_name} Coolify"
  type       = "self_hosted"
  domain     = var.coolify_hostname

  policies = [
    { id = cloudflare_zero_trust_access_policy.admins.id, precedence = 1 },
    { id = cloudflare_zero_trust_access_policy.ci.id, precedence = 2 },
  ]
}

# --- zone rulesets ---------------------------------------------------------
# A zone has exactly one entrypoint ruleset per phase. If one exists already
# (made in the dashboard, for this zone's other sites), `terraform import` it
# instead of creating a second: terraform import cloudflare_ruleset.<name>
# zones/<zone id>/<ruleset id>.

# Coolify domains are entered as http:// (Cloudflare terminates TLS; with
# https:// Traefik would try Let's Encrypt and loop behind the tunnel), so
# nothing else upgrades a plain-http visitor. Doing it per hostname keeps
# Basic auth off cleartext without touching zone-wide settings, because the
# zone also hosts other sites.
resource "cloudflare_ruleset" "https_redirect" {
  zone_id = var.cloudflare_zone_id
  name    = "diffus https redirect"
  kind    = "zone"
  phase   = "http_request_dynamic_redirect"

  rules = [{
    action      = "redirect"
    description = "Send plain http for the app and Coolify to https"
    enabled     = true
    expression  = "(http.host in {\"${var.app_hostname}\" \"${var.coolify_hostname}\"}) and not ssl"
    action_parameters = {
      from_value = {
        status_code           = 301
        preserve_query_string = true
        target_url = {
          expression = "concat(\"https://\", http.host, http.request.uri.path)"
        }
      }
    }
  }]
}

# Meta's image fetcher has no browser and trips the bot checks, so skip them
# for the two paths it (and the uptime check) needs. Bot Fight Mode cannot be
# skipped on the free plan: keep it off for this zone, and verify with the
# "prove a tunnel is good enough for Meta" check in docs/development.md.
resource "cloudflare_ruleset" "meta_fetch" {
  zone_id = var.cloudflare_zone_id
  name    = "diffus skip bot checks for Meta"
  kind    = "zone"
  phase   = "http_request_firewall_custom"

  rules = [{
    action      = "skip"
    description = "Let Meta fetch /media and /healthz"
    enabled     = true
    expression  = "(http.host eq \"${var.app_hostname}\" and (starts_with(http.request.uri.path, \"/media/\") or http.request.uri.path eq \"/healthz\"))"
    action_parameters = {
      products = ["bic", "securityLevel"]
    }
  }]
}

