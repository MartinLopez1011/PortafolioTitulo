# ==============================================================================
# Script de Provisionamiento de Roles IAM de Minimo Privilegio (Modo AWS Normal / Prod)
# Proyecto: Sistema Predictivo y Telemetría Molino Coloidal QLA
# NOTA: Este script SOLO se ejecuta cuando DEPLOY_MODE = 'prod'.
#       En AWS Academy Learner Lab (DEPLOY_MODE = 'lab') NO se invoca, respetando
#       la restriccion estricta de usar exclusivamente LabRole.
# ==============================================================================

param(
    [Parameter(Mandatory=$true)]
    [string]$AccountId,

    [Parameter(Mandatory=$false)]
    [string]$Region = "us-east-1",

    [Parameter(Mandatory=$false)]
    [string]$BucketName = "backup-planta-asfalto-molino-ml",

    [Parameter(Mandatory=$false)]
    [string]$DynamoTable = "QLA_Molino_Telemetria",

    [Parameter(Mandatory=$false)]
    [string]$FirehoseStream = "stream-backup-planta-asfalto",

    [Parameter(Mandatory=$false)]
    [string]$GlueDatabase = "qla_planta_asfalto",

    [Parameter(Mandatory=$false)]
    [string]$GlueTable = "telemetria_molino"
)

$ErrorActionPreference = "Continue"

$LAMBDA_ROLE_NAME   = "QLA_Lambda_Inference_Role"
$FIREHOSE_ROLE_NAME = "QLA_Firehose_Delivery_Role"
$IOT_RULE_ROLE_NAME = "QLA_IoT_Rule_Role"

function Ensure-IamRole {
    param(
        [string]$RoleName,
        [string]$ServicePrincipal,
        [string]$PolicyName,
        [string]$PolicyJson
    )

    $TrustPolicy = @"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "$ServicePrincipal"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
"@
    $TrustFile = "$env:TEMP\trust_${RoleName}.json"
    $PolicyFile = "$env:TEMP\policy_${RoleName}.json"
    $TrustPolicy | Set-Content -Path $TrustFile -Encoding UTF8
    $PolicyJson  | Set-Content -Path $PolicyFile -Encoding UTF8

    aws iam get-role --role-name $RoleName 2>$null | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  -> Creando rol IAM '$RoleName' ($ServicePrincipal)..." -ForegroundColor Cyan
        aws iam create-role `
            --role-name $RoleName `
            --assume-role-policy-document "file://$TrustFile" `
            --description "Rol Least-Privilege para $ServicePrincipal en proyecto Molino Coloidal QLA" | Out-Null
    } else {
        Write-Host "  -> Rol IAM '$RoleName' ya existe. Actualizando politicas..." -ForegroundColor DarkCyan
        aws iam update-assume-role-policy `
            --role-name $RoleName `
            --policy-document "file://$TrustFile" 2>$null | Out-Null
    }

    aws iam put-role-policy `
        --role-name $RoleName `
        --policy-name $PolicyName `
        --policy-document "file://$PolicyFile" | Out-Null
}

# 1. Rol para AWS Lambda (Inferencia ML)
$LambdaPolicyJson = @"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:${Region}:${AccountId}:*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:GetItem",
        "dynamodb:Query"
      ],
      "Resource": "arn:aws:dynamodb:${Region}:${AccountId}:table/${DynamoTable}"
    },
    {
      "Effect": "Allow",
      "Action": [
        "iot:Publish"
      ],
      "Resource": "arn:aws:iot:${Region}:${AccountId}:topic/planta/asfalto/molino/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::${BucketName}",
        "arn:aws:s3:::${BucketName}/*"
      ]
    }
  ]
}
"@
Ensure-IamRole -RoleName $LAMBDA_ROLE_NAME -ServicePrincipal "lambda.amazonaws.com" -PolicyName "QLA_Lambda_Inference_Policy" -PolicyJson $LambdaPolicyJson

# 2. Rol para Amazon Data Firehose (Conversion JSON -> Parquet en S3 con esquema Glue)
$FirehosePolicyJson = @"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:AbortMultipartUpload",
        "s3:GetBucketLocation",
        "s3:GetObject",
        "s3:ListBucket",
        "s3:ListBucketMultipartUploads",
        "s3:PutObject"
      ],
      "Resource": [
        "arn:aws:s3:::${BucketName}",
        "arn:aws:s3:::${BucketName}/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "glue:GetTable",
        "glue:GetTableVersion",
        "glue:GetTableVersions"
      ],
      "Resource": [
        "arn:aws:glue:${Region}:${AccountId}:catalog",
        "arn:aws:glue:${Region}:${AccountId}:database/${GlueDatabase}",
        "arn:aws:glue:${Region}:${AccountId}:table/${GlueDatabase}/${GlueTable}"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:${Region}:${AccountId}:log-group:/aws/kinesisfirehose/*"
    }
  ]
}
"@
Ensure-IamRole -RoleName $FIREHOSE_ROLE_NAME -ServicePrincipal "firehose.amazonaws.com" -PolicyName "QLA_Firehose_Delivery_Policy" -PolicyJson $FirehosePolicyJson

# 3. Rol para AWS IoT Core Topic Rule hacia Firehose
$IotRulePolicyJson = @"
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "firehose:PutRecord",
        "firehose:PutRecordBatch"
      ],
      "Resource": "arn:aws:firehose:${Region}:${AccountId}:deliverystream/${FirehoseStream}"
    }
  ]
}
"@
Ensure-IamRole -RoleName $IOT_RULE_ROLE_NAME -ServicePrincipal "iot.amazonaws.com" -PolicyName "QLA_IoT_Firehose_Rule_Policy" -PolicyJson $IotRulePolicyJson

Write-Host "  -> Esperando propagacion de roles IAM (8 segundos)..." -ForegroundColor DarkGray
Start-Sleep -Seconds 8

return @{
    LambdaRoleArn   = "arn:aws:iam::${AccountId}:role/${LAMBDA_ROLE_NAME}"
    FirehoseRoleArn = "arn:aws:iam::${AccountId}:role/${FIREHOSE_ROLE_NAME}"
    IotRuleRoleArn  = "arn:aws:iam::${AccountId}:role/${IOT_RULE_ROLE_NAME}"
}
