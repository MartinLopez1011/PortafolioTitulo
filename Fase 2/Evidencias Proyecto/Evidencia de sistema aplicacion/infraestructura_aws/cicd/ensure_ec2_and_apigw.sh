#!/bin/bash
# Asegura que en us-east-2 existan:
# 1. Rol + Instance Profile (qla-ec2-profile) con acceso a ECR, SSM, S3, DynamoDB e IoT
# 2. Security Group (qla-web-sg) con puerto 80 abierto
# 3. Instancia EC2 (qla-servidor) en estado running con /opt/qla/Backend/.env
# 4. API Gateway HTTPS (qla-dashboard) apuntando a la IP pública de la EC2
set -euo pipefail

REGION="${AWS_REGION:-us-east-2}"
EC2_TAG="${EC2_TAG:-qla-servidor}"
SG_NAME="qla-web-sg"
PROFILE_NAME="qla-ec2-profile"
ROLE_NAME="qla-ec2-role"
API_NAME="${API_NAME:-qla-dashboard}"
TIPO_INSTANCIA="${EC2_INSTANCE_TYPE:-t3.small}"

log() { echo "[provision] $*" >&2; }

# 1. Rol e Instance Profile para la EC2 (mínimo privilegio)
if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  log "Creando rol IAM $ROLE_NAME para la EC2..."
  aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document '{
    "Version":"2012-10-17",
    "Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]
  }' >/dev/null
  for pol in AmazonSSMManagedInstanceCore AmazonEC2ContainerRegistryReadOnly; do
    aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "arn:aws:iam::aws:policy/$pol"
  done
fi

aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name qla-ec2-app-policy --policy-document '{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
      "Resource": [
        "arn:aws:s3:::qla-*",
        "arn:aws:s3:::qla-*/*",
        "arn:aws:s3:::backup-planta-asfalto-molino-ml*",
        "arn:aws:s3:::backup-planta-asfalto-molino-ml*/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": ["dynamodb:BatchGetItem", "dynamodb:GetItem", "dynamodb:Query"],
      "Resource": "arn:aws:dynamodb:*:*:table/QLA_Molino_Telemetria"
    },
    {
      "Effect": "Allow",
      "Action": ["lambda:GetFunction", "lambda:GetFunctionConfiguration", "lambda:UpdateFunctionConfiguration"],
      "Resource": "arn:aws:lambda:*:*:function:qla-molino-inferencia"
    },
    {
      "Effect": "Allow",
      "Action": "iot:DescribeEndpoint",
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": "iot:Publish",
      "Resource": "arn:aws:iot:*:*:topic/planta/asfalto/molino/*"
    }
  ]
}' >/dev/null

if ! aws iam get-instance-profile --instance-profile-name "$PROFILE_NAME" >/dev/null 2>&1; then
  log "Creando Instance Profile $PROFILE_NAME..."
  aws iam create-instance-profile --instance-profile-name "$PROFILE_NAME" >/dev/null
  aws iam add-role-to-instance-profile --instance-profile-name "$PROFILE_NAME" --role-name "$ROLE_NAME" >/dev/null
  sleep 12
fi

# 2. Buscar instancia existente
IID=$(aws ec2 describe-instances --region "$REGION" \
  --filters "Name=tag:Name,Values=$EC2_TAG" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
  --query "Reservations[0].Instances[0].InstanceId" --output text)

if [ -z "$IID" ] || [ "$IID" = "None" ]; then
  log "No existe EC2 $EC2_TAG en $REGION; aprovisionando servidor..."
  VPC_ID=$(aws ec2 describe-vpcs --region "$REGION" --filters "Name=isDefault,Values=true" --query "Vpcs[0].VpcId" --output text)
  SUBNET_ID=$(aws ec2 describe-subnets --region "$REGION" --filters "Name=vpc-id,Values=$VPC_ID" --query "Subnets[0].SubnetId" --output text)

  SG_ID=$(aws ec2 describe-security-groups --region "$REGION" --filters "Name=group-name,Values=$SG_NAME" "Name=vpc-id,Values=$VPC_ID" --query "SecurityGroups[0].GroupId" --output text)
  if [ -z "$SG_ID" ] || [ "$SG_ID" = "None" ]; then
    SG_ID=$(aws ec2 create-security-group --region "$REGION" --group-name "$SG_NAME" --description "HTTP publico para Dashboard QLA" --vpc-id "$VPC_ID" --query GroupId --output text)
    aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$SG_ID" --protocol tcp --port 80 --cidr 0.0.0.0/0 >/dev/null
  fi

  AMI_ID=$(aws ssm get-parameters --region "$REGION" --names /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 --query "Parameters[0].Value" --output text)

  cat > /tmp/ud.sh <<'USERDATA'
#!/bin/bash
set -euo pipefail
dnf install -y docker
systemctl enable --now docker
mkdir -p /opt/qla/Backend
USERDATA

  IID=$(aws ec2 run-instances --region "$REGION" \
    --image-id "$AMI_ID" \
    --instance-type "$TIPO_INSTANCIA" \
    --subnet-id "$SUBNET_ID" \
    --security-group-ids "$SG_ID" \
    --associate-public-ip-address \
    --iam-instance-profile "Name=$PROFILE_NAME" \
    --metadata-options "HttpTokens=required,HttpPutResponseHopLimit=2,HttpEndpoint=enabled" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$EC2_TAG}]" \
    --user-data file:///tmp/ud.sh \
    --query "Instances[0].InstanceId" --output text)
  rm -f /tmp/ud.sh
  log "Instancia $IID creada; esperando a que arranque y registre SSM..."
  aws ec2 wait instance-running --region "$REGION" --instance-ids "$IID"
else
  STATE=$(aws ec2 describe-instances --region "$REGION" --instance-ids "$IID" --query "Reservations[0].Instances[0].State.Name" --output text)
  log "Instancia existente $IID (estado: $STATE)"
  if [ "$STATE" = "stopped" ]; then
    log "Encendiendo instancia $IID..."
    aws ec2 start-instances --region "$REGION" --instance-ids "$IID" >/dev/null
    aws ec2 wait instance-running --region "$REGION" --instance-ids "$IID"
  elif [ "$STATE" != "running" ]; then
    aws ec2 wait instance-running --region "$REGION" --instance-ids "$IID"
  fi
fi

# Esperar a que SSM Agent esté Online
PING=""
for _ in $(seq 1 30); do
  PING=$(aws ssm describe-instance-information --region "$REGION" \
    --filters "Key=InstanceIds,Values=$IID" --query "InstanceInformationList[0].PingStatus" --output text 2>/dev/null || true)
  [ "$PING" = "Online" ] && break
  sleep 5
done
if [ "$PING" != "Online" ]; then
  log "ERROR: SSM Agent de $IID no alcanzó estado Online (estado: ${PING:-desconocido})"
  exit 1
fi

# Configurar /opt/qla/Backend/.env en la instancia vía SSM (sin exponer secretos en user-data)
DB_B64=$(printf '%s' "${DATABASE_URL_ENV:-}" | base64 | tr -d '\n')
JWT_B64=$(printf '%s' "${JWT_SECRET_ENV:-}" | base64 | tr -d '\n')
INGESTA_B64=$(printf '%s' "${CLAVE_INGESTA_ENV:-}" | base64 | tr -d '\n')
ENV_SCRIPT_B64=$(cat <<'REMOTE_EOF' | base64 | tr -d '\n'
#!/bin/bash
set -euo pipefail
DB_URL=$(printf '%s' "${1:-}" | base64 -d)
JWT_SEC=$(printf '%s' "${2:-}" | base64 -d)
INGESTA_SEC=$(printf '%s' "${3:-}" | base64 -d)
REGION="${4:-us-east-2}"
ENV_FILE=/opt/qla/Backend/.env
mkdir -p /opt/qla/Backend
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

set_kv() {
  local k="$1" v="$2" tmp
  tmp=$(mktemp)
  QLA_VAL="$v" awk -v k="$k" '
    BEGIN { v=ENVIRON["QLA_VAL"]; found=0 }
    index($0, k "=") == 1 { print k "=" v; found=1; next }
    { print }
    END { if (!found) print k "=" v }
  ' "$ENV_FILE" > "$tmp"
  mv "$tmp" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
}

if [ -n "$DB_URL" ]; then
  set_kv "DATABASE_URL" "$DB_URL"
  set_kv "MODO_DEMO" "0"
elif ! grep -q '^MODO_DEMO=' "$ENV_FILE"; then
  set_kv "MODO_DEMO" "1"
fi
grep -q '^DEMO_CLAVE=' "$ENV_FILE" || set_kv "DEMO_CLAVE" "ClaveDemo2026"
if [ -n "$JWT_SEC" ]; then
  set_kv "JWT_SECRET" "$JWT_SEC"
elif ! grep -q '^JWT_SECRET=' "$ENV_FILE"; then
  set_kv "JWT_SECRET" "$(openssl rand -hex 32)"
fi
if [ -n "$INGESTA_SEC" ]; then
  set_kv "CLAVE_INGESTA" "$INGESTA_SEC"
elif ! grep -q '^CLAVE_INGESTA=' "$ENV_FILE"; then
  set_kv "CLAVE_INGESTA" "$(openssl rand -hex 24)"
fi
set_kv "AWS_DEFAULT_REGION" "$REGION"
set_kv "AWS_REGION" "$REGION"
rm -f /tmp/qla_env.sh
REMOTE_EOF
)
PARAMS=$(jq -nc --arg s "$ENV_SCRIPT_B64" --arg db "$DB_B64" --arg jwt "$JWT_B64" --arg ing "$INGESTA_B64" --arg reg "$REGION" \
  '{commands: ["echo \($s) | base64 -d > /tmp/qla_env.sh", "bash /tmp/qla_env.sh \"\($db)\" \"\($jwt)\" \"\($ing)\" \"\($reg)\""]}')
CMD_ID=$(aws ssm send-command --region "$REGION" --instance-ids "$IID" --document-name AWS-RunShellScript \
  --comment "configure backend env" --timeout-seconds 120 \
  --parameters "$PARAMS" --query "Command.CommandId" --output text)
aws ssm wait command-executed --region "$REGION" --command-id "$CMD_ID" --instance-id "$IID" >/dev/null 2>&1 || true
CMD_STATUS=$(aws ssm get-command-invocation --region "$REGION" --command-id "$CMD_ID" --instance-id "$IID" --query "Status" --output text)
if [ "$CMD_STATUS" != "Success" ]; then
  log "ERROR configurando /opt/qla/Backend/.env vía SSM (estado: $CMD_STATUS)"
  aws ssm get-command-invocation --region "$REGION" --command-id "$CMD_ID" --instance-id "$IID" --query "StandardErrorContent" --output text >&2 || true
  exit 1
fi

# Obtener IP pública actual y configurar API Gateway HTTPS apuntando a esa IP
PUBLIC_IP=$(aws ec2 describe-instances --region "$REGION" --instance-ids "$IID" --query "Reservations[0].Instances[0].PublicIpAddress" --output text)
API_ID=$(aws apigatewayv2 get-apis --region "$REGION" --query "Items[?Name=='$API_NAME'].ApiId | [0]" --output text)

if [ -z "$API_ID" ] || [ "$API_ID" = "None" ]; then
  log "Creando API Gateway HTTPS ($API_NAME) -> http://$PUBLIC_IP ..."
  API_ID=$(aws apigatewayv2 create-api --region "$REGION" --name "$API_NAME" --protocol-type HTTP --query ApiId --output text)
  INT1=$(aws apigatewayv2 create-integration --region "$REGION" --api-id "$API_ID" --integration-type HTTP_PROXY --integration-method ANY --integration-uri "http://$PUBLIC_IP/{proxy}" --payload-format-version 1.0 --query IntegrationId --output text)
  INT2=$(aws apigatewayv2 create-integration --region "$REGION" --api-id "$API_ID" --integration-type HTTP_PROXY --integration-method ANY --integration-uri "http://$PUBLIC_IP/" --payload-format-version 1.0 --query IntegrationId --output text)
  aws apigatewayv2 create-route --region "$REGION" --api-id "$API_ID" --route-key "ANY /{proxy+}" --target "integrations/$INT1" >/dev/null
  aws apigatewayv2 create-route --region "$REGION" --api-id "$API_ID" --route-key "ANY /" --target "integrations/$INT2" >/dev/null
  aws apigatewayv2 create-stage --region "$REGION" --api-id "$API_ID" --stage-name '$default' --auto-deploy >/dev/null
else
  # Actualizar integraciones si la IP pública cambió tras apagar/encender
  for IID_INT in $(aws apigatewayv2 get-integrations --region "$REGION" --api-id "$API_ID" --query "Items[].IntegrationId" --output text); do
    URI=$(aws apigatewayv2 get-integration --region "$REGION" --api-id "$API_ID" --integration-id "$IID_INT" --query IntegrationUri --output text)
    if echo "$URI" | grep -q "{proxy}"; then
      aws apigatewayv2 update-integration --region "$REGION" --api-id "$API_ID" --integration-id "$IID_INT" --integration-uri "http://$PUBLIC_IP/{proxy}" >/dev/null
    else
      aws apigatewayv2 update-integration --region "$REGION" --api-id "$API_ID" --integration-id "$IID_INT" --integration-uri "http://$PUBLIC_IP/" >/dev/null
    fi
  done
fi

echo "$IID"
