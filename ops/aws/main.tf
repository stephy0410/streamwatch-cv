# Portal de evidencias de StreamWatch CV en AWS: imagen en ECR privado, servida por Lightsail Container Service
# con HTTPS administrado. La inferencia no corre aquí: la demo sirve las corridas de evidencias/runs en solo
# lectura. (App Runner no está habilitado en la cuenta: SubscriptionRequiredException.)

resource "aws_ecr_repository" "portal" {
  name                 = var.service_name
  image_tag_mutability = "IMMUTABLE" # un tag = un commit; nunca se reescribe
  force_delete         = true        # permite `terraform destroy` aunque haya imágenes

  image_scanning_configuration {
    scan_on_push = true
  }
}

resource "aws_ecr_lifecycle_policy" "portal" {
  repository = aws_ecr_repository.portal.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Conservar las 5 imágenes más recientes"
      selection    = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = 5 }
      action       = { type = "expire" }
    }]
  })
}

resource "aws_lightsail_container_service" "portal" {
  name  = var.service_name
  power = var.power
  scale = 1

  # Rol administrado por Lightsail para descargar imágenes de ECR privado.
  private_registry_access {
    ecr_image_puller_role {
      is_active = true
    }
  }
}

# Solo el rol de Lightsail de este servicio puede descargar imágenes del repositorio.
data "aws_iam_policy_document" "lightsail_pull" {
  statement {
    sid     = "AllowLightsailPull"
    effect  = "Allow"
    actions = ["ecr:BatchGetImage", "ecr:GetDownloadUrlForLayer"]
    principals {
      type        = "AWS"
      identifiers = [aws_lightsail_container_service.portal.private_registry_access[0].ecr_image_puller_role[0].principal_arn]
    }
  }
}

resource "aws_ecr_repository_policy" "portal" {
  repository = aws_ecr_repository.portal.name
  policy     = data.aws_iam_policy_document.lightsail_pull.json
}

resource "aws_lightsail_container_service_deployment_version" "portal" {
  count        = var.image_tag == "" ? 0 : 1
  service_name = aws_lightsail_container_service.portal.name

  container {
    container_name = "portal"
    image          = "${aws_ecr_repository.portal.repository_url}:${var.image_tag}"
    environment = {
      STREAMWATCH_READONLY = "1"
    }
    ports = {
      "8000" = "HTTP"
    }
  }

  public_endpoint {
    container_name = "portal"
    container_port = 8000
    health_check {
      path                = "/healthz"
      success_codes       = "200"
      interval_seconds    = 10
      timeout_seconds     = 5
      healthy_threshold   = 2
      unhealthy_threshold = 3
    }
  }

  depends_on = [aws_ecr_repository_policy.portal]
}
