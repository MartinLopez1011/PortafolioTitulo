#!/bin/bash
# Ejecutado en la EC2 qla-servidor vía SSM (AWS-RunShellScript) desde .github/workflows/cd.yml
# Uso: deploy_backend_ec2.sh <imagen:tag> <registry> <region>
# - Instala Docker si falta (Amazon Linux 2023)
# - Migra una sola vez desde el servicio systemd "qla" (venv) al contenedor
# - Despliega la nueva imagen y hace rollback automático si no pasa el healthcheck
# No usar "set -x": /opt/qla/Backend/.env contiene secretos.
set -euo pipefail

IMAGEN="$1"; REGISTRY="$2"; REGION="$3"
NOMBRE=qla
ENV_FILE=/opt/qla/Backend/.env
ESTADO=/opt/qla/imagen_actual

log() { echo "[$(date -u +%H:%M:%S)] $*"; }

if ! command -v docker >/dev/null 2>&1; then
  log "Instalando Docker"
  dnf install -y docker >/dev/null
fi
systemctl enable --now docker >/dev/null

if systemctl list-unit-files qla.service >/dev/null 2>&1 && systemctl is-enabled qla >/dev/null 2>&1; then
  log "Migrando: deteniendo servicio systemd 'qla' (venv) a favor del contenedor"
  systemctl disable --now qla || true
fi

[ -f "$ENV_FILE" ] || { echo "Falta $ENV_FILE con DATABASE_URL/JWT_SECRET/CLAVE_INGESTA" >&2; exit 1; }

log "Login en ECR ($REGISTRY)"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRY" >/dev/null

log "Descargando $IMAGEN"
docker pull -q "$IMAGEN"

ANTERIOR=$(cat "$ESTADO" 2>/dev/null || true)

arrancar() {
  docker rm -f "$NOMBRE" >/dev/null 2>&1 || true
  docker run -d --name "$NOMBRE" --restart always \
    -p 80:8000 --env-file "$ENV_FILE" \
    -e AWS_DEFAULT_REGION="$REGION" -e AWS_REGION="$REGION" \
    --log-driver json-file --log-opt max-size=20m --log-opt max-file=3 \
    "$1" >/dev/null
}

sano() {
  for _ in $(seq 1 30); do
    CODIGO=$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1/api/salud || true)
    case "$CODIGO" in
      200) log "Healthcheck OK"; return 0 ;;
      503) log "API arriba pero la base de datos no responde (503). Se acepta el despliegue."; return 0 ;;
    esac
    sleep 3
  done
  return 1
}

log "Arrancando contenedor"
arrancar "$IMAGEN"
if sano; then
  echo "$IMAGEN" > "$ESTADO"
  docker image prune -af --filter "until=168h" >/dev/null || true
  log "Desplegado $IMAGEN"
  exit 0
fi

log "ERROR: la nueva imagen no responde. Logs:"
docker logs --tail 80 "$NOMBRE" || true
if [ -n "$ANTERIOR" ]; then
  log "Rollback a $ANTERIOR"
  arrancar "$ANTERIOR"
  sano || log "El rollback tampoco responde"
fi
exit 1
