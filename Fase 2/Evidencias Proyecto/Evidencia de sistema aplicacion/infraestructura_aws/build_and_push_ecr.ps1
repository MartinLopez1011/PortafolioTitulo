# Imagen DOCKER para subir a ECR (Compatible con AWS Academy Learner Lab - LabRole)

$AWS_REGION = "us-east-1"
$AWS_ACCOUNT_ID = (aws sts get-caller-identity --query "Account" --output text).Trim()
$LAB_ROLE_ARN = "arn:aws:iam::${AWS_ACCOUNT_ID}:role/LabRole"
$REPO_NAME = "qla-molino-inferencia"
$IMAGE_TAG = "latest"
$ECR_URI = "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO_NAME"

Write-Host "Cuenta AWS detectada: $AWS_ACCOUNT_ID | Rol: $LAB_ROLE_ARN" -ForegroundColor Yellow

Write-Host "1. Creando repositorio ECR si no existe..." -ForegroundColor Cyan
aws ecr describe-repositories --repository-names $REPO_NAME --region $AWS_REGION 2>$null
if ($LASTEXITCODE -ne 0) {
    aws ecr create-repository --repository-name $REPO_NAME --region $AWS_REGION
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
    Write-Host "ERROR: Falló la compilación/subida de la imagen a ECR." -ForegroundColor Red
    exit 1
}

Write-Host "Imagen subida exitosamente: ${ECR_URI}:${IMAGE_TAG}" -ForegroundColor Green

Write-Host "4. Creando o actualizando función AWS Lambda con LabRole..." -ForegroundColor Cyan
aws lambda get-function --function-name $REPO_NAME --region $AWS_REGION 2>$null
if ($LASTEXITCODE -ne 0) {
    aws lambda create-function `
      --function-name $REPO_NAME `
      --package-type Image `
      --code ImageUri="${ECR_URI}:${IMAGE_TAG}" `
      --role $LAB_ROLE_ARN `
      --timeout 60 `
      --memory-size 2048 `
      --region $AWS_REGION
} else {
    aws lambda update-function-code `
      --function-name $REPO_NAME `
      --image-uri "${ECR_URI}:${IMAGE_TAG}" `
      --region $AWS_REGION
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Falló la actualización de la función Lambda." -ForegroundColor Red
    exit 1
}

Write-Host "Función Lambda actualizada exitosamente con LabRole ($LAB_ROLE_ARN)." -ForegroundColor Green
