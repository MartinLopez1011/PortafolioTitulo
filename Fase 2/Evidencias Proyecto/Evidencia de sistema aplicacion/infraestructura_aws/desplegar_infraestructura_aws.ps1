# ==============================================================================
# Script de Despliegue de Infraestructura AWS (Arquitectura Dual: Lab vs Prod)
# Proyecto: Sistema Predictivo y Telemetría Molino Coloidal QLA
#
# Modos soportados:
#   -Mode lab  (Default): Usa exclusivamente 'arn:aws:iam::<ACC_ID>:role/LabRole'
#                         sin ejecutar iam:CreateRole (100% compatible con AWS Academy Learner Lab).
#   -Mode prod          : Crea y asigna 3 roles IAM de minimo privilegio (Least-Privilege)
#                         para cuentas AWS comerciales/normales.
# ==============================================================================

param(
    [Parameter(Mandatory=$false)]
    [ValidateSet("lab", "prod")]
    [string]$Mode = $(if ($env:DEPLOY_MODE) { $env:DEPLOY_MODE } else { "lab" }),

    [Parameter(Mandatory=$false)]
    [string]$Region = $(if ($env:AWS_REGION) { $env:AWS_REGION } else { "us-east-1" }),

    [Parameter(Mandatory=$false)]
    [string]$BucketName = $(if ($env:S3_BUCKET) { $env:S3_BUCKET } else { "backup-planta-asfalto-molino-ml" })
)

$ErrorActionPreference = "Continue"
$AWS_REGION = $Region
$BUCKET_NAME = $BucketName
$REPO_NAME = "qla-molino-inferencia"
$DYNAMO_TABLE = "QLA_Molino_Telemetria"
$FIREHOSE_STREAM = "stream-backup-planta-asfalto"

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "[DESPLIEGUE COMPLETO DE INFRAESTRUCTURA AWS - 3 RUTAS QLA]" -ForegroundColor Cyan
Write-Host "   Modo de Arquitectura: $($Mode.ToUpper())" -ForegroundColor Yellow
Write-Host "==================================================================" -ForegroundColor Cyan

# 0. Verificar Identidad AWS y Obtener Account ID e IoT Endpoint Dinamico
$ACC_ID = (aws sts get-caller-identity --query "Account" --output text 2>$null)
if (-not $ACC_ID) {
    Write-Host "[ERROR] No se detectaron credenciales validas de AWS." -ForegroundColor Red
    Write-Host "Asegurate de configurar tus credenciales en ~/.aws/credentials" -ForegroundColor Yellow
    exit 1
}
$ACC_ID = $ACC_ID.Trim()

$IOT_ENDPOINT = (aws iot describe-endpoint --endpoint-type iot:Data-ATS --region $AWS_REGION --query "endpointAddress" --output text 2>$null)
if ($IOT_ENDPOINT) { $IOT_ENDPOINT = $IOT_ENDPOINT.Trim() }

# Resolucion de Roles segun el Modo ('lab' vs 'prod')
if ($Mode -eq "prod") {
    Write-Host "`n[0/4] Configurando Roles IAM de Minimo Privilegio (Modo PROD - Cuenta Normal)..." -ForegroundColor Yellow
    $Roles = .\setup_iam_prod.ps1 `
        -AccountId $ACC_ID `
        -Region $AWS_REGION `
        -BucketName $BUCKET_NAME `
        -DynamoTable $DYNAMO_TABLE `
        -FirehoseStream $FIREHOSE_STREAM
    $LAMBDA_ROLE_ARN   = $Roles.LambdaRoleArn
    $FIREHOSE_ROLE_ARN = $Roles.FirehoseRoleArn
    $IOT_RULE_ROLE_ARN = $Roles.IotRuleRoleArn
} else {
    $LAB_ROLE_ARN      = "arn:aws:iam::${ACC_ID}:role/LabRole"
    $LAMBDA_ROLE_ARN   = $LAB_ROLE_ARN
    $FIREHOSE_ROLE_ARN = $LAB_ROLE_ARN
    $IOT_RULE_ROLE_ARN = $LAB_ROLE_ARN
}

Write-Host "[OK] Cuenta AWS     : $ACC_ID | Region: $AWS_REGION" -ForegroundColor Green
Write-Host "[OK] Endpoint IoT   : $IOT_ENDPOINT" -ForegroundColor Green
Write-Host "[OK] Rol Lambda     : $LAMBDA_ROLE_ARN" -ForegroundColor Green
Write-Host "[OK] Rol Firehose   : $FIREHOSE_ROLE_ARN" -ForegroundColor Green
Write-Host "[OK] Rol IoT Rule   : $IOT_RULE_ROLE_ARN" -ForegroundColor Green

# ------------------------------------------------------------------------------
# 1. RUTA 1: COLD PATH (S3, Glue, Firehose, Athena, Regla IoT)
# ------------------------------------------------------------------------------
Write-Host "`n[1/4] Configurando RUTA 1 (Cold Path: S3 + Glue + Firehose + Athena)..." -ForegroundColor Yellow

# S3 Data Lake
Write-Host "  -> Verificando Bucket S3 '$BUCKET_NAME'..."
aws s3api head-bucket --bucket $BUCKET_NAME 2>$null
if ($LASTEXITCODE -ne 0) {
    aws s3 mb "s3://$BUCKET_NAME" --region $AWS_REGION 2>$null
    if ($LASTEXITCODE -ne 0) {
        # Si el nombre global ya está tomado en otra cuenta, usar sufijo con Account ID
        $BUCKET_NAME = "${BUCKET_NAME}-${ACC_ID}"
        Write-Host "     Nombre global en uso. Creando bucket unico por cuenta: s3://$BUCKET_NAME" -ForegroundColor Cyan
        aws s3 mb "s3://$BUCKET_NAME" --region $AWS_REGION | Out-Null
    }
    Write-Host "     Bucket S3 '$BUCKET_NAME' listo." -ForegroundColor Green
}

# Glue Database
Write-Host "  -> Verificando Base de Datos Glue 'qla_planta_asfalto'..."
aws glue create-database --database-input file://glue_database.json --region $AWS_REGION 2>$null

# Glue Table (Parquet con Partition Projection sincronizado con el Bucket activo)
Write-Host "  -> Verificando Tabla Glue 'telemetria_molino'..."
(Get-Content glue_table.json -Raw).Replace('backup-planta-asfalto-molino-ml', $BUCKET_NAME) | Set-Content "$env:TEMP\glue_table_resolved.json"
aws glue create-table --database-name qla_planta_asfalto --table-input "file://$env:TEMP\glue_table_resolved.json" --region $AWS_REGION 2>$null
if ($LASTEXITCODE -ne 0) {
    aws glue update-table --database-name qla_planta_asfalto --table-input "file://$env:TEMP\glue_table_resolved.json" --region $AWS_REGION 2>$null
}

# Amazon Athena WorkGroup
Write-Host "  -> Configurando WorkGroup de Amazon Athena..."
aws athena update-work-group `
  --work-group primary `
  --configuration-updates "ResultConfigurationUpdates={OutputLocation=s3://${BUCKET_NAME}/athena_results/}" `
  --region $AWS_REGION 2>$null

# Amazon Data Firehose (Crear si no existe, o actualizar destino si ya existe)
Write-Host "  -> Configurando flujo de Amazon Data Firehose '$FIREHOSE_STREAM'..."
$FirehoseDestContent = (Get-Content firehose_update.json -Raw) `
    -replace '\$\{AWS_ACCOUNT_ID\}', $ACC_ID `
    -replace '\$\{FIREHOSE_ROLE_ARN\}', $FIREHOSE_ROLE_ARN `
    -replace '\$\{BUCKET_NAME\}', $BUCKET_NAME `
    -replace 'arn:aws:iam::\$\{AWS_ACCOUNT_ID\}:role/LabRole', $FIREHOSE_ROLE_ARN
$FirehoseDestContent | Set-Content "$env:TEMP\firehose_update.json"

$StreamDesc = (aws firehose describe-delivery-stream --delivery-stream-name $FIREHOSE_STREAM --region $AWS_REGION 2>$null | ConvertFrom-Json)
if (-not $StreamDesc) {
    Write-Host "     Creando Delivery Stream '$FIREHOSE_STREAM'..." -ForegroundColor Cyan
    aws firehose create-delivery-stream `
      --delivery-stream-name $FIREHOSE_STREAM `
      --delivery-stream-type DirectPut `
      --extended-s3-destination-configuration "file://$env:TEMP\firehose_update.json" `
      --region $AWS_REGION 2>$null | Out-Null
} else {
    $VersionId = $StreamDesc.DeliveryStreamDescription.VersionId
    $DestId = $StreamDesc.DeliveryStreamDescription.Destinations[0].DestinationId
    aws firehose update-destination `
      --delivery-stream-name $FIREHOSE_STREAM `
      --current-delivery-stream-version-id $VersionId `
      --destination-id $DestId `
      --extended-s3-destination-update "file://$env:TEMP\firehose_update.json" `
      --region $AWS_REGION 2>$null
}

# Regla IoT Core hacia Firehose
Write-Host "  -> Configurando Regla IoT 'Regla_S3_Historico_Molino'..."
$IotFirehoseRule = (Get-Content iot_rule_firehose.json -Raw) `
    -replace '\$\{AWS_ACCOUNT_ID\}', $ACC_ID `
    -replace '\$\{IOT_RULE_ROLE_ARN\}', $IOT_RULE_ROLE_ARN `
    -replace 'arn:aws:iam::\$\{AWS_ACCOUNT_ID\}:role/LabRole', $IOT_RULE_ROLE_ARN
$IotFirehoseRule | Set-Content "$env:TEMP\iot_rule_firehose.json"

aws iot get-topic-rule --rule-name Regla_S3_Historico_Molino --region $AWS_REGION 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    aws iot create-topic-rule `
      --rule-name Regla_S3_Historico_Molino `
      --topic-rule-payload "file://$env:TEMP\iot_rule_firehose.json" `
      --region $AWS_REGION 2>$null
} else {
    aws iot replace-topic-rule `
      --rule-name Regla_S3_Historico_Molino `
      --topic-rule-payload "file://$env:TEMP\iot_rule_firehose.json" `
      --region $AWS_REGION 2>$null
}

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
  --region $AWS_REGION 2>$null | Out-Null

# Compilacion ECR y Lambda
Write-Host "  -> Desplegando Contenedor ECR y actualizando Lambda con build_and_push_ecr.ps1..."
.\build_and_push_ecr.ps1 `
    -Mode $Mode `
    -LambdaRoleArn $LAMBDA_ROLE_ARN `
    -Region $AWS_REGION `
    -BucketName $BUCKET_NAME `
    -DynamoTable $DYNAMO_TABLE `
    -IotEndpoint $IOT_ENDPOINT

# Permiso Lambda e invocacion IoT Core
Write-Host "  -> Asignando permisos a IoT Core para invocar Lambda..."
aws lambda add-permission `
  --function-name $REPO_NAME `
  --statement-id iot-events `
  --action lambda:InvokeFunction `
  --principal iot.amazonaws.com `
  --region $AWS_REGION 2>$null | Out-Null

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

Write-Host "  -> Configurando Regla IoT 'Regla_Inferencia_Molino'..."
aws iot get-topic-rule --rule-name Regla_Inferencia_Molino --region $AWS_REGION 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    aws iot create-topic-rule `
      --rule-name Regla_Inferencia_Molino `
      --topic-rule-payload "file://$env:TEMP\rule_lambda.json" `
      --region $AWS_REGION 2>$null
} else {
    aws iot replace-topic-rule `
      --rule-name Regla_Inferencia_Molino `
      --topic-rule-payload "file://$env:TEMP\rule_lambda.json" `
      --region $AWS_REGION 2>$null
}

# ------------------------------------------------------------------------------
# 3. RUTA 3: HOT PATH (Politica IoT Core para WebSockets / MQTT)
# ------------------------------------------------------------------------------
Write-Host "`n[3/4] Configurando RUTA 3 (Hot Path: Politica IoT Core)..." -ForegroundColor Yellow
aws iot create-policy `
  --policy-name PlantaAsfalto_Molino_Policy `
  --policy-document file://iot_policy_updated.json `
  --region $AWS_REGION 2>$null | Out-Null

# ------------------------------------------------------------------------------
# 4. RESUMEN FINAL
# ------------------------------------------------------------------------------
Write-Host "`n[4/4] Verificacion completada con exito." -ForegroundColor Green
Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "[OK] INFRAESTRUCTURA DESPLEGADA CORRECTAMENTE (MODO: $($Mode.ToUpper()))." -ForegroundColor Green
Write-Host "Puedes probar toda la arquitectura ejecutando:" -ForegroundColor White
Write-Host "   python probar_arquitectura_completa.py" -ForegroundColor Yellow
Write-Host "==================================================================" -ForegroundColor Cyan
