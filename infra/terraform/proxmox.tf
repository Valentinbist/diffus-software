# Debian 13 (trixie) cloud image. content_type "import" needs the datastore to
# allow the content type "Import" and a .qcow2 file name.
resource "proxmox_download_file" "debian" {
  node_name    = var.proxmox_node
  datastore_id = var.image_datastore
  content_type = "import"
  file_name    = "debian-13-genericcloud-amd64.qcow2"
  url          = "https://cloud.debian.org/images/cloud/trixie/latest/debian-13-genericcloud-amd64.qcow2"
  # The URL is "latest": without this, a new upstream image would re-download
  # and make the VM's disk (import_from) want a replacement. The image only
  # matters for the first boot; the VM updates itself after that.
  overwrite = false
}

# cloud-init user-data. Runs on first boot only.
resource "proxmox_virtual_environment_file" "user_data" {
  node_name    = var.proxmox_node
  datastore_id = var.snippets_datastore
  content_type = "snippets"

  source_raw {
    file_name = "${var.vm_name}-user-data.yaml"
    data = templatefile("${path.module}/../cloud-init/user-data.yaml.tftpl", {
      hostname     = var.vm_name
      admin_user   = var.admin_user
      ssh_keys     = var.vm_ssh_keys
      tunnel_token = data.cloudflare_zero_trust_tunnel_cloudflared_token.diffus.token
    })
  }
}

resource "proxmox_virtual_environment_vm" "diffus" {
  name      = var.vm_name
  node_name = var.proxmox_node
  vm_id     = var.vm_id

  machine       = "q35"
  scsi_hardware = "virtio-scsi-single"
  on_boot       = true

  operating_system {
    type = "l26"
  }

  cpu {
    cores = var.vm_cores
    type  = "host"
  }

  memory {
    dedicated = var.vm_memory_mb
  }

  # Lets Proxmox shut the guest down cleanly and report its IP.
  agent {
    enabled = true
  }

  disk {
    datastore_id = var.vm_datastore
    import_from  = proxmox_download_file.debian.id
    interface    = "scsi0"
    file_format  = "raw"
    size         = var.vm_disk_gb
    discard      = "on"
    iothread     = true
  }

  network_device {
    bridge = var.vm_bridge
    model  = "virtio"
  }

  initialization {
    ip_config {
      ipv4 {
        address = var.vm_ipv4
        gateway = var.vm_gateway
      }
    }
    user_data_file_id = proxmox_virtual_environment_file.user_data.id
  }

  lifecycle {
    # The VM holds the production database. Destroying it takes a deliberate
    # edit of this line.
    prevent_destroy = true
    # cloud-init only runs on first boot, so editing the template later must
    # not make Terraform replace a running machine.
    ignore_changes = [initialization]
  }
}
