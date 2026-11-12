output "url" {
  description = "URL HTTPS pública del portal"
  value       = aws_lightsail_container_service.portal.url
}

output "ecr_repository_url" {
  description = "Repositorio de ECR de la imagen"
  value       = aws_ecr_repository.portal.repository_url
}

output "image" {
  description = "Imagen desplegada"
  value       = var.image_tag == "" ? null : "${aws_ecr_repository.portal.repository_url}:${var.image_tag}"
}
