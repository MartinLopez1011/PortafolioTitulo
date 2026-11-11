#!/usr/bin/env bash
# ==============================================================================
# Script de Provisionamiento de Roles IAM de Mínimo Privilegio (Modo AWS Normal / Prod)
# Proyecto: Sistema Predictivo y Telemetría Molino Coloidal QLA
# ==============================================================================
set -u

ACCOUNT_ID="${1:-}"
REGION="${2:-us-east-1}"
BUCKET_NAME="${3:-backup-planta-asfalto-molino-ml}"
DYNAMO_TABLE="${4:-QLA_Molino_Telemetria}"
FIREHOSE_STREAM="${5:-stream-backup-planta-asfalto}"
GLUE_DATABASE="${6:-qla_planta_asfalto}"
GLUE_TABLE="${7:-telemetria_molino}"

TMP_DIR="/tmp/qla_aws_deploy"
mkdir -p "$TMP_DIR"

LAMBDA_ROLE_NAME="QLA_Lambda_Inference_Role"
FIREHOSE_ROLE_NAME="QLA_Firehose_Delivery_Role"
IOT_RULE_ROLE_NAME="QLA_IoT_Rule_Role"

ensure_iam_role() {
    local role_name="$1"
    local service_principal="$2"
    local policy_name="$3"
    local policy_file="$4"
    local trust_file="${TMP_DIR}/trust_${role_name}.json"

    cat > "$trust_file" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "${service_principal}"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
EOF

    if ! aws iam get-role --role-name "$role_name" >/dev/null 2>&1; then
        echo -e "  -> \033[1;36mCreando rol IAM '${role_name}' (${service_principal})...\033[0m"
        aws iam create-role \
            --role-name "$role_name" \
            --assume-role-policy-document "file://${trust_file}" \
            --description "Rol Least-Privilege para ${service_principal} en proyecto Molino Coloidal QLA" >/dev/null
    else
        echo -e "  -> \033[0;36mRol IAM '${role_name}' ya existe. Actualizando políticas...\033[0m"
        aws iam update-assume-role-policy \
            --role-name "$role_name" \
            --policy-document "file://${trust_file}" >/dev/null 2>&1 || true
    fi

    aws iam put-role-policy \
        --role-name "$role_name" \
        --policy-name "$policy_name" \
        --policy-document "file://${policy_file}" >/dev/null
}

# 1. Rol para AWS Lambda (Inferencia ML)
cat > "${TMP_DIR}/policy_${LAMBDA_ROLE_NAME}.json" <<EOF
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
      "Resource": "arn:aws:logs:${REGION}:${ACCOUNT_ID}:*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:GetItem",
        "dynamodb:Query"
      ],
      "Resource": "arn:aws:dynamodb:${REGION}:${ACCOUNT_ID}:table/${DYNAMO_TABLE}"
    },
    {
      "Effect": "Allow",
      "Action": [
        "iot:Publish"
      ],
      "Resource": "arn:aws:iot:${REGION}:${ACCOUNT_ID}:topic/planta/asfalto/molino/*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::${BUCKET_NAME}",
        "arn:aws:s3:::${BUCKET_NAME}/*"
      ]
    }
  ]
}
EOF
ensure_iam_role "$LAMBDA_ROLE_NAME" "lambda.amazonaws.com" "QLA_Lambda_Inference_Policy" "${TMP_DIR}/policy_${LAMBDA_ROLE_NAME}.json"

# 2. Rol para Amazon Data Firehose
cat > "${TMP_DIR}/policy_${FIREHOSE_ROLE_NAME}.json" <<EOF
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
        "arn:aws:s3:::${BUCKET_NAME}",
        "arn:aws:s3:::${BUCKET_NAME}/*"
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
        "arn:aws:glue:${REGION}:${ACCOUNT_ID}:catalog",
        "arn:aws:glue:${REGION}:${ACCOUNT_ID}:database/${GLUE_DATABASE}",
        "arn:aws:glue:${REGION}:${ACCOUNT_ID}:table/${GLUE_DATABASE}/${GLUE_TABLE}"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:/aws/kinesisfirehose/*"
    }
  ]
}
EOF
ensure_iam_role "$FIREHOSE_ROLE_NAME" "firehose.amazonaws.com" "QLA_Firehose_Delivery_Policy" "${TMP_DIR}/policy_${FIREHOSE_ROLE_NAME}.json"

# 3. Rol para AWS IoT Core Topic Rule hacia Firehose
cat > "${TMP_DIR}/policy_${IOT_RULE_ROLE_NAME}.json" <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "firehose:PutRecord",
        "firehose:PutRecordBatch"
      ],
      "Resource": "arn:aws:firehose:${REGION}:${ACCOUNT_ID}:deliverystream/${FIREHOSE_STREAM}"
    }
  ]
}
EOF
ensure_iam_role "$IOT_RULE_ROLE_NAME" "iot.amazonaws.com" "QLA_IoT_Firehose_Rule_Policy" "${TMP_DIR}/policy_${IOT_RULE_ROLE_NAME}.json"

echo -e "  -> Esperando propagación de roles IAM (8 segundos)..."
sleep 8

