#!/usr/bin/env bash
# ==============================================================================
# Imagen DOCKER para subir a ECR (Arquitectura Dual: Learner Lab vs AWS Normal)
# Versión nativa para Linux (Bash)
# ==============================================================================
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

MODE="${1:-${DEPLOY_MODE:-lab}}"
LAMBDA_ROLE_ARN="${2:-}"
AWS_REGION="${3:-${AWS_REGION:-us-east-1}}"
BUCKET_NAME="${4:-${S3_BUCKET:-backup-planta-asfalto-molino-ml}}"
DYNAMO_TABLE="${5:-${DYNAMODB_TABLE:-QLA_Molino_Telemetria}}"
IOT_ENDPOINT="${6:-}"

AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query "Account" --output text | tr -d '[:space:]')

if [[ -z "$LAMBDA_ROLE_ARN" ]]; then
    if [[ "$MODE" == "prod" ]]; then
        LAMBDA_ROLE_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:role/QLA_Lambda_Inference_Role"
    else
        LAMBDA_ROLE_ARN="arn:aws:iam::${AWS_ACCOUNT_ID}:role/LabRole"
    fi
fi

if [[ -z "$IOT_ENDPOINT" ]]; then
    IOT_ENDPOINT=$(aws iot describe-endpoint --endpoint-type iot:Data-ATS --region "$AWS_REGION" --query "endpointAddress" --output text 2>/dev/null | tr -d '[:space:]' || true)
fi

REPO_NAME="qla-molino-inferencia"
IMAGE_TAG="latest"
ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${REPO_NAME}"

echo -e "\033[1;33mCuenta AWS detectada: ${AWS_ACCOUNT_ID} | Modo: ${MODE^^} | Rol Lambda: ${LAMBDA_ROLE_ARN}\033[0m"

echo -e "\033[1;36m1. Creando repositorio ECR si no existe...\033[0m"
if ! aws ecr describe-repositories --repository-names "$REPO_NAME" --region "$AWS_REGION" >/dev/null 2>&1; then
    aws ecr create-repository --repository-name "$REPO_NAME" --region "$AWS_REGION" >/dev/null
fi

echo -e "\033[1;36m2. Autenticando Docker con ECR...\033[0m"
aws ecr get-login-password --region "$AWS_REGION" | \
    docker login --username AWS --password-stdin "${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com"

echo -e "\033[1;36m3. Compilando y subiendo imagen a ECR en formato compatible con Lambda...\033[0m"
if ! docker buildx build \
    --platform linux/amd64 \
    --provenance=false \
    --sbom=false \
    --output type=registry,oci-mediatypes=false \
    -t "${ECR_URI}:${IMAGE_TAG}" \
    -f ../lambda_inferencia/Dockerfile ../lambda_inferencia/; then
    echo -e "\033[1;31mERROR: Falló la compilación/subida de la imagen a ECR.\033[0m"
    exit 1
fi

echo -e "\033[1;32mImagen subida exitosamente: ${ECR_URI}:${IMAGE_TAG}\033[0m"

ENV_VARS="Variables={S3_BUCKET=${BUCKET_NAME},DYNAMODB_TABLE=${DYNAMO_TABLE}"
if [[ -n "$IOT_ENDPOINT" ]]; then
    ENV_VARS="${ENV_VARS},IOT_ENDPOINT=https://${IOT_ENDPOINT}"
fi
ENV_VARS="${ENV_VARS}}"

echo -e "\033[1;36m4. Creando o actualizando función AWS Lambda con Rol (${LAMBDA_ROLE_ARN})...\033[0m"
if ! aws lambda get-function --function-name "$REPO_NAME" --region "$AWS_REGION" >/dev/null 2>&1; then
    aws lambda create-function \
        --function-name "$REPO_NAME" \
        --package-type Image \
        --code ImageUri="${ECR_URI}:${IMAGE_TAG}" \
        --role "$LAMBDA_ROLE_ARN" \
        --timeout 60 \
        --memory-size 2048 \
        --environment "$ENV_VARS" \
        --region "$AWS_REGION" >/dev/null
else
    aws lambda update-function-code \
        --function-name "$REPO_NAME" \
        --image-uri "${ECR_URI}:${IMAGE_TAG}" \
        --region "$AWS_REGION" >/dev/null

    aws lambda wait function-updated --function-name "$REPO_NAME" --region "$AWS_REGION" 2>/dev/null || true
    aws lambda update-function-configuration \
        --function-name "$REPO_NAME" \
        --role "$LAMBDA_ROLE_ARN" \
        --environment "$ENV_VARS" \
        --region "$AWS_REGION" >/dev/null 2>&1 || true
fi

echo -e "\033[1;32mFunción Lambda actualizada exitosamente con Rol (${LAMBDA_ROLE_ARN}).\033[0m"
