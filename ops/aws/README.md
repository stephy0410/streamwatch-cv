# Despliegue en AWS (Terraform)

Publica el **portal de evidencias** en una URL HTTPS: las corridas de `evidencias/runs` y las revisiones de
`evidencias/revisiones`, en **solo lectura**. La inferencia no corre en la nube: el monitor necesita la GPU local
y las cámaras se procesan en la máquina de la autora.

```
git commit ─► ops/aws/deploy.sh ─► ECR privado (imagen linux/amd64, tag = commit, inmutable, escaneada)
                                        │  (rol de Lightsail con permiso solo de lectura sobre el repositorio)
                                        ▼
                              Lightsail Container Service (nano: 0.25 vCPU / 512 MB, 1 nodo)
                              HTTPS administrado · health check /healthz · STREAMWATCH_READONLY=1
```

| Recurso | Para qué |
|---|---|
| `aws_ecr_repository` | Imágenes con tags inmutables (un tag = un commit), escaneo al subir y retención de las 5 últimas |
| `aws_ecr_repository_policy` | Solo el rol de Lightsail de este servicio puede descargar |
| `aws_lightsail_container_service` | Nodo nano con HTTPS y acceso a ECR privado |
| `aws_lightsail_container_service_deployment_version` | Contenedor `portal`, puerto 8000 y health check |

## Uso

```bash
aws login --profile streamwatch && export AWS_PROFILE=streamwatch   # credenciales temporales, sin claves fijas
ops/aws/deploy.sh                                                    # infraestructura + imagen + despliegue
terraform -chdir=ops/aws output url
terraform -chdir=ops/aws destroy                                     # elimina todo (incluido ECR)
```

`deploy.sh` se niega a desplegar si hay cambios sin commit en lo que entra a la imagen: así la URL siempre
corresponde a una revisión de Git. Si la imagen de ese commit ya existe en ECR, no se reconstruye.

## Decisiones

- **Lightsail en lugar de App Runner:** App Runner no está habilitado en la cuenta
  (`SubscriptionRequiredException`). Lightsail ofrece lo mismo para este caso (contenedor, HTTPS y health check)
  con precio fijo.
- **Imagen `demo`:** la evidencia y el SQLite van dentro de la imagen (`ops/Dockerfile`, etapa `demo`), así que el
  servicio no necesita almacenamiento ni base de datos administrada, y cada imagen es inmutable y reproducible.
  Con OpenCV *headless* y un builder aparte pesa ~170 MB.
- **Solo lectura:** el portal público rechaza revisiones (403) y oculta el formulario. Sin autenticación, aceptar
  escrituras de internet sería un riesgo.
- **Estado de Terraform local** (proyecto individual). En un equipo se usaría un backend `s3` con bloqueo.
- **Credenciales:** `aws login` da credenciales temporales. El script las exporta al entorno porque el proveedor
  de Terraform aún no lee ese tipo de sesión. No hay claves de acceso permanentes en el repositorio ni en la
  máquina.

## Costo

Nodo nano de Lightsail: ~7 US$ al mes con precio fijo, más centavos de ECR. Se elimina con `terraform destroy`.
