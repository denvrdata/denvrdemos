terraform {
  required_providers {
    denvr = {
      source  = "denvrdata/denvr"
      version = "0.2.0"
    }
  }
}
provider "denvr" {}

variable "nodes" {
  type        = number
  description = "Number of nodes"
  default     = 4
}

variable "username" {
  type        = string
  description = "Username for the denvrpy SDK config"
  default     = ""
}

variable "password" {
  type        = string
  description = "Password for the denvrpy SDK config"
  default     = ""
}

resource "tls_private_key" "ssh_key" {
  algorithm = "RSA"
  rsa_bits  = 4096
}
resource "local_file" "private_key" {
  content         = tls_private_key.ssh_key.private_key_openssh
  filename        = "${path.cwd}/.secrets/id_rsa"
  file_permission = "0600"
}

resource "local_file" "public_key" {
  content         = tls_private_key.ssh_key.public_key_openssh
  filename        = "${path.cwd}/.secrets/id_rsa.pub"
  file_permission = "0644"
}

resource "denvr_vm" "terraform_vm" {
  count                       = var.nodes
  name                        = "terraform-vm-${count.index + 1}"
  rpool                       = "on-demand"
  vpc                         = "denvr"
  configuration               = "A100_80GB_SXM_1x"
  cluster                     = "Hou1"
  ssh_keys                    = [tls_private_key.ssh_key.public_key_openssh]
  operating_system_image      = "nvidia-550-sxm"
  personal_storage_mount_path = "/home/ubuntu/personal"
  # tenant_shared_additional_storage = "/home/ubuntu/tenant-shared"
  persist_storage           = false
  direct_storage_mount_path = "/home/ubuntu/direct-attached"
  root_disk_size            = 250
  wait                      = true
  timeout                   = 1200 # Covers requesting resources and waiting on boot (Denvr's API has a limit of 15 min anyway)

  connection {
    type        = "ssh"
    host        = self.ip
    user        = "ubuntu"
    private_key = tls_private_key.ssh_key.private_key_openssh
  }

  provisioner "file" {
    content     = templatefile("templates/denvr.toml.tpl", { username = var.username, password = var.password })
    destination = "/home/ubuntu/denvr.toml"
  }

  provisioner "file" {
    content = templatefile("templates/shutdown.py.tpl", {
      id        = self.name,
      namespace = self.namespace,
      cluster   = self.cluster,
    })
    destination = "/home/ubuntu/shutdown.py"
  }

  provisioner "file" {
    content     = file("scripts/training.py")
    destination = "/home/ubuntu/training.py"
  }
}

resource "null_resource" "setup" {
  count = var.nodes

  # This depends on both VMs being ready
  depends_on = [denvr_vm.terraform_vm]

  connection {
    type        = "ssh"
    host        = denvr_vm.terraform_vm[count.index].ip
    user        = "ubuntu"
    private_key = tls_private_key.ssh_key.private_key_openssh
  }

  provisioner "remote-exec" {
    inline = [
      "time sudo apt-get update -qq -y",
      "time sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_SUSPEND=1 apt-get install -qq -y at python3-pip python3-dev --no-install-recommends",
      "time pip3 install --quiet --index-url https://download.pytorch.org/whl/cu128 torch numpy",
      "time pip3 install --quiet denvr",
      "mkdir -p /home/ubuntu/.config/denvr",
      "mv /home/ubuntu/denvr.toml /home/ubuntu/.config/denvr.toml",
      "chmod 600 /home/ubuntu/.config/denvr.toml",
    ]
  }
}
# - Start the torch run commands
# - On the manager node save the snapshot file to the personal storage share
resource "null_resource" "training" {
  count = var.nodes

  # This depends on both VMs being ready
  depends_on = [null_resource.setup]

  connection {
    type        = "ssh"
    host        = denvr_vm.terraform_vm[count.index].ip
    user        = "ubuntu"
    private_key = tls_private_key.ssh_key.private_key_openssh
  }

  provisioner "remote-exec" {
    inline = [
      "echo \"${denvr_vm.terraform_vm[0].private_ip} ${denvr_vm.terraform_vm[0].name}\" | sudo tee -a /etc/hosts",
      <<EOT
      TORCH_LOGS="-torch.distributed.elastic" TORCH_CPP_LOG_LEVEL=ERROR ~/.local/bin/torchrun \
      --nproc_per_node=1 \
      --nnodes=${var.nodes} \
      --node_rank=${count.index} \
      --rdzv_id=451 \
      --rdzv_backend=c10d \
      --rdzv_endpoint=${denvr_vm.terraform_vm[0].name}:29500 \
      /home/ubuntu/training.py 50 10
      EOT
    ]
  }
}

resource "null_resource" "shutdown" {
  count = var.nodes

  # This depends on both VMs being ready
  depends_on = [null_resource.training]

  connection {
    type        = "ssh"
    host        = denvr_vm.terraform_vm[count.index].ip
    user        = "ubuntu"
    private_key = tls_private_key.ssh_key.private_key_openssh
  }

  provisioner "remote-exec" {
    inline = [
      "echo 'python3 /home/ubuntu/shutdown.py > /home/ubuntu/shutdown.log  2>&1' | at now + 1 minute",
    ]
  }
}
