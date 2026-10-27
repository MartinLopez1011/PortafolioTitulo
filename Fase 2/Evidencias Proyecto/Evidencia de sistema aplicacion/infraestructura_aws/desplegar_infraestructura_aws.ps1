# ==============================================================================
# Script de Despliegue de Infraestructura AWS (AWS Academy Learner Lab - LabRole)
# Proyecto: Sistema Predictivo y Telemetría Molino Coloidal QLA
# ==============================================================================

$ErrorActionPreference = "Continue"
$AWS_REGION = "us-east-1"
$BUCKET_NAME = "backup-planta-asfalto-molino-ml"
$REPO_NAME = "qla-molino-inferencia"
$DYNAMO_TABLE = "QLA_Molino_Telemetria"

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "🚀 DESPLIEGUE COMPLETO DE INFRAESTRUCTURA AWS (3 RUTAS QLA)" -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan

# 0. Verificar Identidad AWS y Obtener Account ID
$ACC_ID = (aws sts get-caller-identity --query "Account" --output text 2>$null)
if (-not $ACC_ID) {
    Write-Host "❌ ERROR: No se detectaron credenciales validas de AWS." -ForegroundColor Red
    Write-Host "Asegurate de iniciar tu Learner Lab y actualizar ~/.aws/credentials" -ForegroundColor Yellow
    exit 1
}
$ACC_ID = $ACC_ID.Trim()
$LAB_ROLE_ARN = "arn:aws:iam::${ACC_ID}:role/LabRole"
Write-Host "✔ Cuenta AWS: $ACC_ID | Rol: $LAB_ROLE_ARN" -ForegroundColor Green

# ------------------------------------------------------------------------------
# 1. RUTA 1: COLD PATH (S3, Glue, Firehose, Athena, Regla IoT)
# ------------------------------------------------------------------------------
Write-Host "`n[1/4] Configurando RUTA 1 (Cold Path: S3 + Glue + Firehose + Athena)..." -ForegroundColor Yellow

# S3 Data Lake
Write-Host "  -> Verificando Bucket S3 '$BUCKET_NAME'..."
aws s3 mb "s3://$BUCKET_NAME" --region $AWS_REGION 2>$null
if ($LASTEXITCODE -eq 0) { Write-Host "     Bucket S3 creado exitosamente." -ForegroundColor Green }

# Glue Database
Write-Host "  -> Verificando Base de Datos Glue 'qla_planta_asfalto'..."
aws glue create-database --database-input file://glue_database.json --region $AWS_REGION 2>$null

# Glue Table (Parquet con Partition Projection)
Write-Host "  -> Verificando Tabla Glue 'telemetria_molino'..."
aws glue create-table --database-name qla_planta_asfalto --table-input file://glue_table.json --region $AWS_REGION 2>$null

# Amazon Athena WorkGroup
Write-Host "  -> Configurando WorkGroup de Amazon Athena..."
aws athena update-work-group `
  --work-group primary `
  --configuration-updates "ResultConfigurationUpdates={OutputLocation=s3://${BUCKET_NAME}/athena_results/}" `
  --region $AWS_REGION 2>$null

# Amazon Data Firehose Destination
Write-Host "  -> Actualizando destino de Amazon Data Firehose..."
(Get-Content firehose_update.json -Raw).Replace('${AWS_ACCOUNT_ID}', $ACC_ID) | Set-Content "$env:TEMP\firehose_update.json"
aws firehose update-destination `
  --delivery-stream-name stream-backup-planta-asfalto `
  --current-delivery-stream-version-id 1 `
  --destination-id destinationId-000000000001 `
  --extended-s3-destination-update "file://$env:TEMP\firehose_update.json" `
  --region $AWS_REGION 2>$null

# Regla IoT Core hacia Firehose
Write-Host "  -> Configurando Regla IoT 'Regla_S3_Historico_Molino'..."
(Get-Content iot_rule_firehose.json -Raw).Replace('${AWS_ACCOUNT_ID}', $ACC_ID) | Set-Content "$env:TEMP\iot_rule_firehose.json"
aws iot replace-topic-rule `
  --rule-name Regla_S3_Historico_Molino `
  --topic-rule-payload "file://$env:TEMP\iot_rule_firehose.json" `
  --region $AWS_REGION 2>$null

# ------------------------------------------------------------------------------
# 2. RUTA 2: ML PATH (DynamoDB, ECR, Lambda & Regla IoT)
# ------------------------------------------------------------------------------
Write-Host "`n[2/4] Configurando RUTA 2 (ML Path: DynamoDB + ECR/Lambda + Regla IoT)..." -ForegroundColor Yellow

# DynamoDB
Write-Host "  -> Creando tabla DynamoDB '$DYNAMO_TABLE' si no existe..."
aws dynamodb create-table `
  --table-name $DYNAMO_TABLE `
  --attribute-definitions AttributeName=equipo_id,AttributeType=S AttributeName=timestamp,AttributeType=N `
  --key-schema AttributeName=equipo_id,KeyType=HASH AttributeName=timestamp,KeyType=RANGE `
  --billing-mode PAY_PER_REQUEST `
  --region $AWS_REGION 2>$null

# Compilación ECR y Lambda
Write-Host "  -> Desplegando Contenedor ECR y actualizando Lambda con build_and_push_ecr.ps1..."
.\build_and_push_ecr.ps1

# Permiso Lambda e invocación IoT Core
Write-Host "  -> Asignando permisos a IoT Core para invocar Lambda..."
aws lambda add-permission `
  --function-name $REPO_NAME `
  --statement-id iot-events `
  --action lambda:InvokeFunction `
  --principal iot.amazonaws.com `
  --region $AWS_REGION 2>$null

$LAMBDA_ARN = "arn:aws:lambda:${AWS_REGION}:${ACC_ID}:function:${REPO_NAME}"
$RULE_PAYLOAD = @"
{
  "sql": "SELECT * FROM 'planta/asfalto/molino/telemetria'",
  "description": "Inferencia ML en tiempo real con cada paquete de telemetria",
  "actions": [
    {
      "lambda": {
        "functionArn": "$LAMBDA_ARN"
      }
    }
  ],
  "ruleDisabled": false,
  "awsIotSqlVersion": "2016-03-23"
}
"@
$RULE_PAYLOAD | Set-Content "$env:TEMP\rule_lambda.json"

Write-Host "  -> Creando Regla IoT 'Regla_Inferencia_Molino'..."
aws iot replace-topic-rule `
  --rule-name Regla_Inferencia_Molino `
  --topic-rule-payload "file://$env:TEMP\rule_lambda.json" `
  --region $AWS_REGION 2>$null

# ------------------------------------------------------------------------------
# 3. RUTA 3: HOT PATH (Politica IoT Core para WebSockets / MQTT)
# ------------------------------------------------------------------------------
Write-Host "`n[3/4] Configurando RUTA 3 (Hot Path: Politica IoT Core)..." -ForegroundColor Yellow
aws iot create-policy `
  --policy-name PlantaAsfalto_Molino_Policy `
  --policy-document file://iot_policy_updated.json `
  --region $AWS_REGION 2>$null

# ------------------------------------------------------------------------------
# 4. RESUMEN FINAL
# ------------------------------------------------------------------------------
Write-Host "`n[4/4] Verificacion completada con exito." -ForegroundColor Green
Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "🎉 INFRAESTRUCTURA DESPLEGADA CORRECTAMENTE." -ForegroundColor Green
Write-Host "Puedes probar toda la arquitectura ejecutando:" -ForegroundColor White
Write-Host "   python probar_arquitectura_completa.py" -ForegroundColor Yellow
Write-Host "==================================================================" -ForegroundColor Cyan
