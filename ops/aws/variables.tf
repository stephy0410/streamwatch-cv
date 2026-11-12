variable "region" {
  description = "Región de AWS"
  type        = string
  default     = "us-east-1"
}

variable "service_name" {
  description = "Nombre del servicio de Lightsail y del repositorio de ECR"
  type        = string
  default     = "streamwatch-cv"
}

variable "power" {
  description = "Tamaño de nodo de Lightsail (nano = 0.25 vCPU, 512 MB)"
  type        = string
  default     = "nano"
  validation {
    condition     = contains(["nano", "micro", "small", "medium", "large", "xlarge"], var.power)
    error_message = "power debe ser un tamaño válido de Lightsail."
  }
}

variable "image_tag" {
  description = "Tag de la imagen en ECR (commit). Vacío: solo se crea la infraestructura, sin desplegar"
  type        = string
  default     = ""
}
