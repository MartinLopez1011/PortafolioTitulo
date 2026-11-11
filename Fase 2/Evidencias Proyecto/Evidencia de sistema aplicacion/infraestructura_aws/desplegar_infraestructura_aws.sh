#!/usr/bin/env bash
# ==============================================================================
# Script de Despliegue de Infraestructura AWS (Arquitectura Dual: Lab vs Prod)
# Proyecto: Sistema Predictivo y Telemetría Molino Coloidal QLA
#
# Uso en Linux:
#   ./desplegar_infraestructura_aws.sh prod   # Cuenta AWS Comercial / Normal (crea roles IAM Least-Privilege)
#   ./desplegar_infraestructura_aws.sh lab    # AWS Academy Learner Lab (usa LabRole)
# ==============================================================================
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

MODE="${1:-${DEPLOY_MODE:-prod}}"
AWS_REGION="${AWS_REGION:-us-east-1}"
BUCKET_NAME="${S3_BUCKET:-backup-planta-asfalto-molino-ml}"
REPO_NAME="qla-molino-inferencia"
DYNAMO_TABLE="QLA_Molino_Telemetria"
FIREHOSE_STREAM="stream-backup-planta-asfalto"
TMP_DIR="/tmp/qla_aws_deploy"
mkdir -p "$TMP_DIR"

echo -e "\033[1;36m==================================================================\033[0m"
echo -e "\033[1;36m🚀 DESPLIEGUE COMPLETO DE INFRAESTRUCTURA AWS (3 RUTAS QLA)\033[0m"
echo -e "\033[1;33m   Modo de Arquitectura: ${MODE^^}\033[0m"
echo -e "\033[1;36m==================================================================\033[0m"

# 0. Verificar Identidad AWS y Obtener Account ID e IoT Endpoint Dinámico
ACC_ID=$(aws sts get-caller-identity --query "Account" --output text 2>/dev/null | tr -d '[:space:]')
if [[ -z "$ACC_ID" ]]; then
    echo -e "\033[1;31m❌ ERROR: No se detectaron credenciales válidas de AWS.\033[0m"
    echo -e "\033[1;33mAsegúrate de configurar tus credenciales en ~/.aws/credentials\033[0m"
    exit 1
fi

IOT_ENDPOINT=$(aws iot describe-endpoint --endpoint-type iot:Data-ATS --region "$AWS_REGION" --query "endpointAddress" --output text 2>/dev/null | tr -d '[:space:]' || true)

# Verificar / Crear Bucket S3 antes de crear políticas IAM para tener el nombre real del bucket
if ! aws s3api head-bucket --bucket "$BUCKET_NAME" 2>/dev/null; then
    if ! aws s3 mb "s3://$BUCKET_NAME" --region "$AWS_REGION" 2>/dev/null; then
        BUCKET_NAME="${BUCKET_NAME}-${ACC_ID}"
        echo -e "  -> \033[1;36mNombre global S3 en uso. Creando bucket único por cuenta: s3://${BUCKET_NAME}\033[0m"
        aws s3 mb "s3://$BUCKET_NAME" --region "$AWS_REGION" >/dev/null
    fi
fi

# Resolución de Roles según el Modo ('lab' vs 'prod')
if [[ "$MODE" == "prod" ]]; then
    echo -e "\n\033[1;33m[0/4] Configurando Roles IAM de Mínimo Privilegio (Modo PROD - Cuenta Comercial)...\033[0m"
    bash "${SCRIPT_DIR}/setup_iam_prod.sh" "$ACC_ID" "$AWS_REGION" "$BUCKET_NAME" "$DYNAMO_TABLE" "$FIREHOSE_STREAM"
    LAMBDA_ROLE_ARN="arn:aws:iam::${ACC_ID}:role/QLA_Lambda_Inference_Role"
    FIREHOSE_ROLE_ARN="arn:aws:iam::${ACC_ID}:role/QLA_Firehose_Delivery_Role"
    IOT_RULE_ROLE_ARN="arn:aws:iam::${ACC_ID}:role/QLA_IoT_Rule_Role"
else
    LAB_ROLE_ARN="arn:aws:iam::${ACC_ID}:role/LabRole"
    LAMBDA_ROLE_ARN="$LAB_ROLE_ARN"
    FIREHOSE_ROLE_ARN="$LAB_ROLE_ARN"
    IOT_RULE_ROLE_ARN="$LAB_ROLE_ARN"
fi

echo -e "\033[1;32m✔ Cuenta AWS     : ${ACC_ID} | Región: ${AWS_REGION}\033[0m"
echo -e "\033[1;32m✔ Bucket S3      : ${BUCKET_NAME}\033[0m"
echo -e "\033[1;32m✔ Endpoint IoT   : ${IOT_ENDPOINT}\033[0m"
echo -e "\033[1;32m✔ Rol Lambda     : ${LAMBDA_ROLE_ARN}\033[0m"
echo -e "\033[1;32m✔ Rol Firehose   : ${FIREHOSE_ROLE_ARN}\033[0m"
echo -e "\033[1;32m✔ Rol IoT Rule   : ${IOT_RULE_ROLE_ARN}\033[0m"

# ------------------------------------------------------------------------------
# 1. RUTA 1: COLD PATH (S3, Glue, Firehose, Athena, Regla IoT)
# ------------------------------------------------------------------------------
echo -e "\n\033[1;33m[1/4] Configurando RUTA 1 (Cold Path: S3 + Glue + Firehose + Athena)...\033[0m"

echo "  -> Verificando Base de Datos Glue 'qla_planta_asfalto'..."
aws glue create-database --database-input file://glue_database.json --region "$AWS_REGION" 2>/dev/null || true

echo "  -> Verificando Tabla Glue 'telemetria_molino'..."
sed "s/backup-planta-asfalto-molino-ml/${BUCKET_NAME}/g" glue_table.json > "${TMP_DIR}/glue_table_resolved.json"
if ! aws glue create-table --database-name qla_planta_asfalto --table-input "file://${TMP_DIR}/glue_table_resolved.json" --region "$AWS_REGION" 2>/dev/null; then
    aws glue update-table --database-name qla_planta_asfalto --table-input "file://${TMP_DIR}/glue_table_resolved.json" --region "$AWS_REGION" 2>/dev/null || true
fi

echo "  -> Configurando WorkGroup de Amazon Athena..."
aws athena update-work-group \
    --work-group primary \
    --configuration-updates "ResultConfigurationUpdates={OutputLocation=s3://${BUCKET_NAME}/athena_results/}" \
    --region "$AWS_REGION" 2>/dev/null || true

echo "  -> Configurando flujo de Amazon Data Firehose '$FIREHOSE_STREAM'..."
sed -e "s|\${AWS_ACCOUNT_ID}|${ACC_ID}|g" \
    -e "s|\${FIREHOSE_ROLE_ARN}|${FIREHOSE_ROLE_ARN}|g" \
    -e "s|\${BUCKET_NAME}|${BUCKET_NAME}|g" \
    -e "s|arn:aws:iam::\${AWS_ACCOUNT_ID}:role/LabRole|${FIREHOSE_ROLE_ARN}|g" \
    firehose_update.json > "${TMP_DIR}/firehose_update.json"

if ! aws firehose describe-delivery-stream --delivery-stream-name "$FIREHOSE_STREAM" --region "$AWS_REGION" >/dev/null 2>&1; then
    echo -e "     \033[1;36mCreando Delivery Stream '${FIREHOSE_STREAM}'...\033[0m"
    aws firehose create-delivery-stream \
        --delivery-stream-name "$FIREHOSE_STREAM" \
        --delivery-stream-type DirectPut \
        --extended-s3-destination-configuration "file://${TMP_DIR}/firehose_update.json" \
        --region "$AWS_REGION" >/dev/null
else
    VERSION_ID=$(aws firehose describe-delivery-stream --delivery-stream-name "$FIREHOSE_STREAM" --region "$AWS_REGION" --query "DeliveryStreamDescription.VersionId" --output text)
    DEST_ID=$(aws firehose describe-delivery-stream --delivery-stream-name "$FIREHOSE_STREAM" --region "$AWS_REGION" --query "DeliveryStreamDescription.Destinations[0].DestinationId" --output text)
    aws firehose update-destination \
        --delivery-stream-name "$FIREHOSE_STREAM" \
        --current-delivery-stream-version-id "$VERSION_ID" \
        --destination-id "$DEST_ID" \
        --extended-s3-destination-update "file://${TMP_DIR}/firehose_update.json" \
        --region "$AWS_REGION" >/dev/null
fi

echo "  -> Configurando Regla IoT 'Regla_S3_Historico_Molino'..."
sed -e "s|\${AWS_ACCOUNT_ID}|${ACC_ID}|g" \
    -e "s|\${IOT_RULE_ROLE_ARN}|${IOT_RULE_ROLE_ARN}|g" \
    -e "s|arn:aws:iam::\${AWS_ACCOUNT_ID}:role/LabRole|${IOT_RULE_ROLE_ARN}|g" \
    iot_rule_firehose.json > "${TMP_DIR}/iot_rule_firehose.json"

if ! aws iot get-topic-rule --rule-name Regla_S3_Historico_Molino --region "$AWS_REGION" >/dev/null 2>&1; then
    aws iot create-topic-rule \
        --rule-name Regla_S3_Historico_Molino \
        --topic-rule-payload "file://${TMP_DIR}/iot_rule_firehose.json" \
        --region "$AWS_REGION"
else
    aws iot replace-topic-rule \
        --rule-name Regla_S3_Historico_Molino \
        --topic-rule-payload "file://${TMP_DIR}/iot_rule_firehose.json" \
        --region "$AWS_REGION"
fi

# ------------------------------------------------------------------------------
# 2. RUTA 2: ML PATH (DynamoDB, ECR, Lambda & Regla IoT)
# ------------------------------------------------------------------------------
echo -e "\n\033[1;33m[2/4] Configurando RUTA 2 (ML Path: DynamoDB + ECR/Lambda + Regla IoT)...\033[0m"

echo "  -> Creando tabla DynamoDB '$DYNAMO_TABLE' si no existe..."
aws dynamodb create-table \
    --table-name "$DYNAMO_TABLE" \
    --attribute-definitions AttributeName=equipo_id,AttributeType=S AttributeName=timestamp,AttributeType=N \
    --key-schema AttributeName=equipo_id,KeyType=HASH AttributeName=timestamp,KeyType=RANGE \
    --billing-mode PAY_PER_REQUEST \
    --region "$AWS_REGION" >/dev/null 2>&1 || true

echo "  -> Desplegando Contenedor ECR y actualizando Lambda con build_and_push_ecr.sh..."
bash "${SCRIPT_DIR}/build_and_push_ecr.sh" "$MODE" "$LAMBDA_ROLE_ARN" "$AWS_REGION" "$BUCKET_NAME" "$DYNAMO_TABLE" "$IOT_ENDPOINT"

echo "  -> Asignando permisos a IoT Core para invocar Lambda..."
aws lambda add-permission \
    --function-name "$REPO_NAME" \
    --statement-id iot-events \
    --action lambda:InvokeFunction \
    --principal iot.amazonaws.com \
    --region "$AWS_REGION" >/dev/null 2>&1 || true

LAMBDA_ARN="arn:aws:lambda:${AWS_REGION}:${ACC_ID}:function:${REPO_NAME}"
cat > "${TMP_DIR}/rule_lambda.json" <<EOF
{
  "sql": "SELECT * FROM 'planta/asfalto/molino/telemetria'",
  "description": "Inferencia ML en tiempo real con cada paquete de telemetria",
  "actions": [
    {
      "lambda": {
        "functionArn": "${LAMBDA_ARN}"
      }
    }
  ],
  "ruleDisabled": false,
  "awsIotSqlVersion": "2016-03-23"
}
EOF

echo "  -> Configurando Regla IoT 'Regla_Inferencia_Molino'..."
if ! aws iot get-topic-rule --rule-name Regla_Inferencia_Molino --region "$AWS_REGION" >/dev/null 2>&1; then
    aws iot create-topic-rule \
        --rule-name Regla_Inferencia_Molino \
        --topic-rule-payload "file://${TMP_DIR}/rule_lambda.json" \
        --region "$AWS_REGION"
else
    aws iot replace-topic-rule \
        --rule-name Regla_Inferencia_Molino \
        --topic-rule-payload "file://${TMP_DIR}/rule_lambda.json" \
        --region "$AWS_REGION"
fi

# ------------------------------------------------------------------------------
# 3. RUTA 3: HOT PATH (Política IoT Core para WebSockets / MQTT)
# ------------------------------------------------------------------------------
echo -e "\n\033[1;33m[3/4] Configurando RUTA 3 (Hot Path: Política IoT Core)...\033[0m"
aws iot create-policy \
    --policy-name PlantaAsfalto_Molino_Policy \
    --policy-document file://iot_policy_updated.json \
    --region "$AWS_REGION" >/dev/null 2>&1 || true

# ------------------------------------------------------------------------------
# 4. RESUMEN FINAL
# ------------------------------------------------------------------------------
echo -e "\n\033[1;32m[4/4] Verificación completada con éxito.\033[0m"
echo -e "\033[1;36m==================================================================\033[0m"
echo -e "\033[1;32m🎉 INFRAESTRUCTURA DESPLEGADA CORRECTAMENTE (MODO: ${MODE^^}).\033[0m"
echo -e "Puedes probar toda la arquitectura ejecutando:"
echo -e "\033[1;33m   S3_BUCKET=${BUCKET_NAME} python probar_arquitectura_completa.py\033[0m"
echo -e "\033[1;36m==================================================================\033[0m"
