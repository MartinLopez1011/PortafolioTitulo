# Guía de Despliegue de Infraestructura y Lambda (AWS Academy)

Este documento contiene la secuencia exacta de comandos y configuraciones validadas para desplegar la arquitectura del sistema de predicción y diagnóstico en **AWS Academy Learner Lab** y en **AWS CLI**.

---

## 📌 Consideraciones Clave en AWS Academy
1. **Restricción de IAM**: En AWS Academy (`voclabs`) no se permite crear roles (`iam:CreateRole`) ni adjuntar políticas personalizadas.
2. **Rol de Ejecución**: Se debe utilizar obligatoriamente el rol pre-creado del laboratorio:
   ```text
   arn:aws:iam::<TU_ID_DE_CUENTA>:role/LabRole
   ```
3. **Formato de Imagen Docker**: AWS Lambda requiere imágenes en formato **Docker V2 Schema 2** sin atestaciones OCI. Por ello, el comando de compilación debe incluir `--provenance=false --sbom=false --output type=registry,oci-mediatypes=false`.

---

## 🚀 Paso 1: Crear la Tabla en Amazon DynamoDB

Crea la tabla para el almacenamiento de telemetría y diagnósticos en modo bajo demanda (Pay-Per-Request):

### En PowerShell / Git Bash (una sola línea):
```bash
aws dynamodb create-table --table-name QLA_Molino_Telemetria --attribute-definitions AttributeName=equipo_id,AttributeType=S AttributeName=timestamp,AttributeType=N --key-schema AttributeName=equipo_id,KeyType=HASH AttributeName=timestamp,KeyType=RANGE --billing-mode PAY_PER_REQUEST --region us-east-1
```

### O con formato multilínea (Bash / Git Bash con `\`):
```bash
aws dynamodb create-table \
  --table-name QLA_Molino_Telemetria \
  --attribute-definitions \
      AttributeName=equipo_id,AttributeType=S \
      AttributeName=timestamp,AttributeType=N \
  --key-schema \
      AttributeName=equipo_id,KeyType=HASH \
      AttributeName=timestamp,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-1
```

---

## 🐳 Paso 2: Compilar y Subir la Imagen Docker a Amazon ECR

Asegúrate de que **Docker Desktop** esté abierto y en ejecución.

Ejecuta el script automatizado [build_and_push_ecr.ps1](file:///c:/Users/Soporte/Documents/PortafolioTitulo/Fase%202/Evidencias%20Proyecto/Evidencia%20de%20sistema%20aplicacion/infraestructura_aws/build_and_push_ecr.ps1) desde la carpeta `infraestructura_aws`:

```powershell
cd "Fase 2\Evidencias Proyecto\Evidencia de sistema aplicacion\infraestructura_aws"
.\build_and_push_ecr.ps1
```

### Comandos manuales equivalentes (PowerShell):
```powershell
$AWS_REGION = "us-east-1"
$AWS_ACCOUNT_ID = (aws sts get-caller-identity --query "Account" --output text)
$REPO_NAME = "qla-molino-inferencia"
$IMAGE_TAG = "latest"
$ECR_URI = "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com/$REPO_NAME"

# 1. Crear el repositorio en ECR (si no existe)
aws ecr create-repository --repository-name $REPO_NAME --region $AWS_REGION

# 2. Autenticar Docker con Amazon ECR
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin "$AWS_ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com"

# 3. Compilar y publicar con formato compatible para Lambda
docker buildx build `
  --platform linux/amd64 `
  --provenance=false `
  --sbom=false `
  --output type=registry,oci-mediatypes=false `
  -t "${ECR_URI}:${IMAGE_TAG}" `
  -f ../lambda_inferencia/Dockerfile ../lambda_inferencia/
```

---

## ⚡ Paso 3: Crear la Función AWS Lambda

Una vez que la imagen esté disponible en ECR, crea la función Lambda configurando 2048 MB de memoria RAM y 30 segundos de timeout para los modelos de Machine Learning.

### En PowerShell:
```powershell
$ACCOUNT_ID = (aws sts get-caller-identity --query "Account" --output text)

aws lambda create-function `
  --function-name qla-molino-inferencia `
  --package-type Image `
  --code ImageUri="$ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/qla-molino-inferencia:latest" `
  --role "arn:aws:iam::$ACCOUNT_ID:role/LabRole" `
  --timeout 60 `
  --memory-size 2048 `
  --region us-east-1
```

### En Bash / Git Bash (o comando directo con tu cuenta):
```bash
aws lambda create-function \
  --function-name qla-molino-inferencia \
  --package-type Image \
  --code ImageUri=441381011844.dkr.ecr.us-east-1.amazonaws.com/qla-molino-inferencia:latest \
  --role arn:aws:iam::441381011844:role/LabRole \
  --timeout 60 \
  --memory-size 2048 \
  --region us-east-1
```

---

## 🔄 Paso 4: Actualizar la Función Lambda (Nuevas Versiones)

Si realizas cambios en el código o modelos de [lambda_inferencia](file:///c:/Users/Soporte/Documents/PortafolioTitulo/Fase%202/Evidencias%20Proyecto/Evidencia%20de%20sistema%20aplicacion/lambda_inferencia), vuelve a ejecutar `.\build_and_push_ecr.ps1` y luego actualiza la Lambda:

```powershell
aws lambda update-function-code `
  --function-name qla-molino-inferencia `
  --image-uri 441381011844.dkr.ecr.us-east-1.amazonaws.com/qla-molino-inferencia:latest `
  --region us-east-1
```

---

## 🧪 Paso 5: Invocar y Probar la Función Lambda

Para probar la inferencia con el archivo de prueba [test_payload.json](file:///c:/Users/Soporte/Documents/PortafolioTitulo/Fase%202/Evidencias%20Proyecto/Evidencia%20de%20sistema%20aplicacion/lambda_inferencia/app/test_payload.json):

```powershell
aws lambda invoke `
  --function-name qla-molino-inferencia `
  --cli-binary-format raw-in-base64-out `
  --payload fileb://../lambda_inferencia/app/test_payload.json `
  --region us-east-1 `
  response.json
```

El resultado de la ejecución quedará guardado en `response.json`.
