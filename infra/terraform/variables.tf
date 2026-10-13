variable "cloudflare_account_id" {
  description = "Cloudflare account id (dashboard sidebar, or the URL after dash.cloudflare.com/)."
  type        = string
}

variable "cloudflare_zone_id" {
  description = "Zone id of the domain that hosts app_hostname and coolify_hostname (zone Overview page)."
  type        = string
}

variable "app_hostname" {
  description = "Public hostname of the app, e.g. connector.diffus.space."
  type        = string
}

variable "coolify_hostname" {
  description = "Hostname of the Coolify dashboard, e.g. coolify.diffus.space. Sits behind Cloudflare Access."
  type        = string
}

variable "admin_emails" {
  description = "Email addresses that may open the Coolify dashboard through Cloudflare Access."
  type        = list(string)
}

variable "proxmox_node" {
  description = "Name of the Proxmox node the VM is created on (as shown in the web UI tree)."
  type        = string
}

variable "vm_name" {
  description = "VM name in Proxmox; also the guest's hostname."
  type        = string
  default     = "diffus"
}

variable "vm_id" {
  description = "Proxmox VM id. Null lets Proxmox pick the next free one."
  type        = number
  default     = null
}

variable "vm_cores" {
  description = "Number of vCPU cores."
  type        = number
  default     = 2
}

variable "vm_memory_mb" {
  description = "RAM in MiB. Coolify, its proxy, the app and Postgres need about 4 GiB."
  type        = number
  default     = 4096
}

variable "vm_disk_gb" {
  description = "Size of the system disk in GiB. Docker images and the database live here."
  type        = number
  default     = 40
}

variable "vm_datastore" {
  description = "Datastore for the VM disk."
  type        = string
  default     = "local-lvm"
}

variable "image_datastore" {
  description = "File-based datastore for the downloaded Debian cloud image. Needs content type \"Import\" enabled (Datacenter > Storage)."
  type        = string
  default     = "local"
}

variable "snippets_datastore" {
  description = "Datastore for the cloud-init user-data file. Needs content type \"Snippets\" enabled (Datacenter > Storage)."
  type        = string
  default     = "local"
}

variable "vm_bridge" {
  description = "Proxmox bridge the VM's network card attaches to."
  type        = string
  default     = "vmbr0"
}

variable "vm_ipv4" {
  description = "\"dhcp\", or a static address in CIDR notation, e.g. 192.168.1.50/24."
  type        = string
  default     = "dhcp"
}

variable "vm_gateway" {
  description = "IPv4 gateway for a static vm_ipv4. Leave null for dhcp."
  type        = string
  default     = null
}

variable "vm_ssh_keys" {
  description = "Public SSH keys that may log in as admin_user."
  type        = list(string)
}

variable "admin_user" {
  description = "Name of the sudo user created on the VM."
  type        = string
  default     = "diffus"
}
