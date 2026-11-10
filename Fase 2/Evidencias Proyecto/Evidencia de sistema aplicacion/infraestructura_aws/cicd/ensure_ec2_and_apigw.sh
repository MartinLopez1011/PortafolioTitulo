#!/bin/bash
# Asegura que en us-east-2 existan:
# 1. Rol + Instance Profile (qla-ec2-profile) con acceso a ECR, SSM, S3, DynamoDB e IoT
# 2. Security Group (qla-web-sg) con puerto 80 abierto
# 3. Instancia EC2 (qla-servidor) en estado running con /opt/qla/Backend/.env
# 4. IP Elástica y API Gateway HTTPS (qla-dashboard) apuntando a la EC2
set -euo pipefail

REGION="${AWS_REGION:-us-east-2}"
EC2_TAG="${EC2_TAG:-qla-servidor}"
SG_NAME="qla-web-sg"
PROFILE_NAME="qla-ec2-profile"
ROLE_NAME="qla-ec2-role"
API_NAME="${API_NAME:-qla-dashboard}"
TIPO_INSTANCIA="${EC2_INSTANCE_TYPE:-t3.small}"

log() { echo "[provision] $*" >&2; }

# 1. Rol e Instance Profile para la EC2
if ! aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  log "Creando rol IAM $ROLE_NAME para la EC2..."
  aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document '{
    "Version":"2012-10-17",
    "Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]
  }' >/dev/null
  for pol in AmazonSSMManagedInstanceCore AmazonEC2ContainerRegistryReadOnly AmazonS3FullAccess AmazonDynamoDBFullAccess AWSIoTDataAccess AWSLambda_ReadOnlyAccess; do
    aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "arn:aws:iam::aws:policy/$pol" || true
  done
fi

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
  JWT_SEC="${JWT_SECRET_ENV:-$(openssl rand -hex 32)}"
  INGESTA_SEC="${CLAVE_INGESTA_ENV:-$(openssl rand -hex 24)}"
  DB_URL="${DATABASE_URL_ENV:-}"
  DEMO_MODE="1"
  [ -n "$DB_URL" ] && DEMO_MODE="0"

  cat > /tmp/ud.sh <<USERDATA
#!/bin/bash
set -euo pipefail
dnf install -y docker
systemctl enable --now docker
mkdir -p /opt/qla/Backend
cat > /opt/qla/Backend/.env <<'ENVEOF'
MODO_DEMO=${DEMO_MODE}
DEMO_CLAVE=ClaveDemo2026
DATABASE_URL=${DB_URL}
JWT_SECRET=${JWT_SEC}
CLAVE_INGESTA=${INGESTA_SEC}
AWS_DEFAULT_REGION=${REGION}
ENVEOF
chmod 600 /opt/qla/Backend/.env
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
for _ in $(seq 1 30); do
  PING=$(aws ssm describe-instance-information --region "$REGION" \
    --filters "Key=InstanceIds,Values=$IID" --query "InstanceInformationList[0].PingStatus" --output text 2>/dev/null || true)
  [ "$PING" = "Online" ] && break
  sleep 5
done

# Asegurar que /opt/qla/Backend/.env exista en la instancia
aws ssm send-command --region "$REGION" --instance-ids "$IID" --document-name AWS-RunShellScript \
  --parameters 'commands=["mkdir -p /opt/qla/Backend && [ -f /opt/qla/Backend/.env ] || printf \"MODO_DEMO=1\nDEMO_CLAVE=ClaveDemo2026\nJWT_SECRET=$(openssl rand -hex 32)\nCLAVE_INGESTA=$(openssl rand -hex 24)\nAWS_DEFAULT_REGION='"$REGION"'\n\" > /opt/qla/Backend/.env"]' >/dev/null

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
