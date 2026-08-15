terraform {
  required_version = ">= 1.0.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

# Fetch default VPC
data "aws_vpc" "default" {
  default = true
}

# Fetch default subnets
data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# Latest Ubuntu 24.04 LTS AMI
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical

  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# Security Group for BuildWise OS
resource "aws_security_group" "buildwise_sg" {
  name        = "buildwise-t3-small-sg"
  description = "Security Group for BuildWise Capstone OS on t3.small"
  vpc_id      = data.aws_vpc.default.id

  # HTTP Port 80 (Nginx Security Gateway)
  ingress {
    description = "Public HTTP Access (Protected by Basic Auth)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # SSH Port 22
  ingress {
    description = "SSH Access"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  # Outbound Rules (Allow all egress)
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "buildwise-sg"
    Project = "BuildWise-Capstone"
  }
}

# User Data Cloud Init Script Template
data "template_file" "user_data" {
  template = file("${path.module}/user_data.sh")

  vars = {
    security_user     = var.security_user
    security_password = var.security_password
    openai_api_key    = var.openai_api_key
    llm_provider      = var.openai_api_key != "" ? "openai" : "mock"
    github_repo       = var.github_repo
  }
}

# EC2 Instance (t3.small)
resource "aws_instance" "buildwise" {
  ami                         = data.aws_ami.ubuntu.id
  instance_type               = var.instance_type
  key_name                    = var.key_name != "" ? var.key_name : null
  subnet_id                   = data.aws_subnets.default.ids[0]
  vpc_security_group_ids      = [aws_security_group.buildwise_sg.id]
  associate_public_ip_address = true

  user_data                   = data.template_file.user_data.rendered

  root_block_device {
    volume_type           = "gp3"
    volume_size           = 20
    delete_on_termination = true
  }

  tags = {
    Name    = "BuildWise-Capstone-t3-small"
    Project = "BuildWise-Capstone"
  }
}
