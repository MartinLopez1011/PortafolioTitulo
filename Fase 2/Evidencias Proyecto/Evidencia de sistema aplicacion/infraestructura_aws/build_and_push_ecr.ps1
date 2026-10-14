#Imagen DOCKER para subir a ECR

# Variables de despliegue
$AWS_REGION = "us-east-1"
$AWS_ACCOUNT_ID = (aws sts get-caller-identity --query "Account" --output text)
$REPO_NAME = "qla-molino-inferencia"
$IMAGE_TAG = "latest"
$ECR_URI = "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO_NAME"

Write-Host "1. Creando repositorio ECR si no existe..." -ForegroundColor Cyan
aws ecr describe-repositories --repository-names $REPO_NAME --region $AWS_REGION 2>$null
if ($LASTEXITCODE -ne 0) {
    aws ecr create-repository --repository-name $REPO_NAME --region $AWS_REGION
}

Write-Host "2. Autenticando Docker con ECR..." -ForegroundColor Cyan
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

# 3 y 4. Compilando y subiendo directamente en formato Docker V2 (compatible con AWS Lambda)
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
docker push "${ECR_URI}:${IMAGE_TAG}"
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Falló la subida de la imagen a ECR (docker push)." -ForegroundColor Red
    exit 1
}

Write-Host "Imagen subida exitosamente: ${ECR_URI}:${IMAGE_TAG}" -ForegroundColor Green