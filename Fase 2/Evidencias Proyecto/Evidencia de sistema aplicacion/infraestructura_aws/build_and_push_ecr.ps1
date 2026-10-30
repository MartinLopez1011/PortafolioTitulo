# ==============================================================================
# Imagen DOCKER para subir a ECR (Arquitectura Dual: Learner Lab vs AWS Normal)
# ==============================================================================

param(
    [Parameter(Mandatory=$false)]
    [ValidateSet("lab", "prod")]
    [string]$Mode = $(if ($env:DEPLOY_MODE) { $env:DEPLOY_MODE } else { "lab" }),

    [Parameter(Mandatory=$false)]
    [string]$LambdaRoleArn = "",

    [Parameter(Mandatory=$false)]
    [string]$Region = $(if ($env:AWS_REGION) { $env:AWS_REGION } else { "us-east-1" }),

    [Parameter(Mandatory=$false)]
    [string]$BucketName = $(if ($env:S3_BUCKET) { $env:S3_BUCKET } else { "backup-planta-asfalto-molino-ml" }),

    [Parameter(Mandatory=$false)]
    [string]$DynamoTable = $(if ($env:DYNAMODB_TABLE) { $env:DYNAMODB_TABLE } else { "QLA_Molino_Telemetria" }),

    [Parameter(Mandatory=$false)]
    [string]$IotEndpoint = ""
)

$AWS_REGION = $Region
$AWS_ACCOUNT_ID = (aws sts get-caller-identity --query "Account" --output text).Trim()

if (-not $LambdaRoleArn) {
    if ($Mode -eq "prod") {
        $LambdaRoleArn = "arn:aws:iam::${AWS_ACCOUNT_ID}:role/QLA_Lambda_Inference_Role"
    } else {
        $LambdaRoleArn = "arn:aws:iam::${AWS_ACCOUNT_ID}:role/LabRole"
    }
}

if (-not $IotEndpoint) {
    $IotEndpoint = (aws iot describe-endpoint --endpoint-type iot:Data-ATS --region $AWS_REGION --query "endpointAddress" --output text 2>$null)
    if ($IotEndpoint) { $IotEndpoint = $IotEndpoint.Trim() }
}

$REPO_NAME = "qla-molino-inferencia"
$IMAGE_TAG = "latest"
$ECR_URI = "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO_NAME"

Write-Host "Cuenta AWS detectada: $AWS_ACCOUNT_ID | Modo: $($Mode.ToUpper()) | Rol Lambda: $LambdaRoleArn" -ForegroundColor Yellow

Write-Host "1. Creando repositorio ECR si no existe..." -ForegroundColor Cyan
aws ecr describe-repositories --repository-names $REPO_NAME --region $AWS_REGION 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    aws ecr create-repository --repository-name $REPO_NAME --region $AWS_REGION | Out-Null
}

Write-Host "2. Autenticando Docker con ECR..." -ForegroundColor Cyan
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

Write-Host "3. Compilando y subiendo imagen a ECR en formato compatible con Lambda..." -ForegroundColor Cyan
docker buildx build `
  --platform linux/amd64 `
  --provenance=false `
  --sbom=false `
  --output type=registry,oci-mediatypes=false `
  -t "${ECR_URI}:${IMAGE_TAG}" `
  -f ../lambda_inferencia/Dockerfile ../lambda_inferencia/

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Fallo la compilacion/subida de la imagen a ECR." -ForegroundColor Red
    exit 1
}

Write-Host "Imagen subida exitosamente: ${ECR_URI}:${IMAGE_TAG}" -ForegroundColor Green

$EnvVars = "Variables={S3_BUCKET=${BucketName},DYNAMODB_TABLE=${DynamoTable}"
if ($IotEndpoint) {
    $EnvVars += ",IOT_ENDPOINT=https://${IotEndpoint}"
}
$EnvVars += "}"

Write-Host "4. Creando o actualizando funcion AWS Lambda con Rol ($LambdaRoleArn)..." -ForegroundColor Cyan
aws lambda get-function --function-name $REPO_NAME --region $AWS_REGION 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    aws lambda create-function `
      --function-name $REPO_NAME `
      --package-type Image `
      --code ImageUri="${ECR_URI}:${IMAGE_TAG}" `
      --role $LambdaRoleArn `
      --timeout 60 `
      --memory-size 2048 `
      --environment "$EnvVars" `
      --region $AWS_REGION | Out-Null
} else {
    aws lambda update-function-code `
      --function-name $REPO_NAME `
      --image-uri "${ECR_URI}:${IMAGE_TAG}" `
      --region $AWS_REGION | Out-Null

    aws lambda wait function-updated --function-name $REPO_NAME --region $AWS_REGION 2>$null
    aws lambda update-function-configuration `
      --function-name $REPO_NAME `
      --role $LambdaRoleArn `
      --environment "$EnvVars" `
      --region $AWS_REGION 2>$null | Out-Null
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Fallo la actualizacion de la funcion Lambda." -ForegroundColor Red
    exit 1
}

Write-Host "Funcion Lambda actualizada exitosamente con Rol ($LambdaRoleArn)." -ForegroundColor Green
