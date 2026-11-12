terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.80"
    }
  }
  # Estado local (proyecto individual). Para un equipo: backend "s3" con bloqueo.
}

provider "aws" {
  region = var.region
  default_tags {
    tags = {
      project    = "streamwatch-cv"
      managed-by = "terraform"
      repository = "github.com/stephy0410/streamwatch-cv"
    }
  }
}
