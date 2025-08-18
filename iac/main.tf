terraform {
  required_providers { aws = { source = "hashicorp/aws", version = "~> 3.0" } }
}

provider "aws" {
  region = "us-east-1"
}

# Intentionally insecure security group
resource "aws_security_group" "open_ssh" {
  name        = "open-ssh"
  description = "Open SSH to the world (bad)"

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# Public S3 bucket with ACL
resource "aws_s3_bucket" "public_bucket" {
  bucket = "vuln-demo-public-bucket-123456"
  acl    = "public-read"
}
