#!/usr/bin/env bash
# Despliega el portal de evidencias en AWS: infraestructura (Terraform) → imagen linux/amd64 en ECR con el tag
# del commit → nueva versión del servicio de Lightsail. Requiere AWS CLI con sesión (p. ej. `aws login --profile
# streamwatch` y `export AWS_PROFILE=streamwatch`), Terraform y Docker.
#   ops/aws/deploy.sh            despliega el commit actual
#   terraform -chdir=ops/aws destroy   elimina todo
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(git rev-parse --show-toplevel)"

# La imagen debe corresponder exactamente a un commit: nada pendiente en lo que entra a la imagen.
if [ -n "$(git -C "$ROOT" status --porcelain -- src config ops/Dockerfile ops/portal-entrypoint.sh evidencias/runs evidencias/revisiones pyproject.toml uv.lock)" ]; then
  echo "Hay cambios sin commit en archivos que entran a la imagen; haz commit primero." >&2
  exit 1
fi
TAG="$(git -C "$ROOT" rev-parse --short=12 HEAD)"

# Terraform aún no lee las sesiones de `aws login`: se exportan sus credenciales temporales al entorno.
if [ -z "${AWS_ACCESS_KEY_ID:-}" ]; then
  eval "$(aws configure export-credentials --format env)"
fi

terraform init -input=false >/dev/null
terraform apply -input=false -auto-approve \
  -target=aws_ecr_repository.portal -target=aws_ecr_repository_policy.portal -target=aws_ecr_lifecycle_policy.portal
REPO="$(terraform output -raw ecr_repository_url)"
REGISTRY="${REPO%%/*}"

if aws ecr describe-images --repository-name "${REPO##*/}" --image-ids imageTag="$TAG" >/dev/null 2>&1; then
  echo "La imagen $REPO:$TAG ya existe; no se reconstruye."
else
  aws ecr get-login-password | docker login --username AWS --password-stdin "$REGISTRY"
  docker buildx build --platform linux/amd64 --target demo -f "$ROOT/ops/Dockerfile" -t "$REPO:$TAG" --push "$ROOT"
fi

terraform apply -input=false -auto-approve -var "image_tag=$TAG"
URL="$(terraform output -raw url)"
echo "Esperando a que $URL responda…"
for _ in $(seq 1 60); do
  if curl -fs "${URL%/}/healthz" >/dev/null; then echo "Desplegado: $URL (imagen $TAG)"; exit 0; fi
  sleep 10
done
echo "El servicio no respondió en 10 min; revisa la consola de Lightsail." >&2
exit 1
