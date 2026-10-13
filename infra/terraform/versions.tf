terraform {
  required_version = ">= 1.10"

  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
    proxmox = {
      source  = "bpg/proxmox"
      version = "~> 0.116"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }

  # No backend: state is the local terraform.tfstate on the laptop that applies
  # (gitignored — it holds the tunnel secret). Lost state is not fatal: import
  # the resources again, or delete and re-create the Cloudflare ones.
}

# Auth comes from the environment, never from files:
#   CLOUDFLARE_API_TOKEN   a token with these permissions
#     Account: Cloudflare Tunnel Edit, Access: Apps and Policies Edit,
#              Access: Service Tokens Edit
#     Zone:    DNS Edit, Zone WAF Edit, Single Redirect Edit
#   PROXMOX_VE_ENDPOINT    e.g. https://pve.lan:8006/
#   PROXMOX_VE_API_TOKEN   user@realm!tokenid=secret
provider "cloudflare" {}

provider "proxmox" {
  # The API cannot upload snippet files, so the provider also uses SSH to the node.
  ssh {
    agent    = true
    username = "root"
  }
}
