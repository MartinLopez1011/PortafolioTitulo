#!/bin/bash
# Configuración de credenciales AWS para GitHub Actions.
# 1. Intenta configurar OIDC (sin claves estáticas).
# 2. Si una Service Control Policy (SCP) de AWS Organizations bloquea OIDC,
#    crea automáticamente un usuario IAM de mínimo privilegio (github-actions-qla-deploy)
#    y genera AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY para GitHub Secrets.
set -euo pipefail

REPO="${REPO:-MartinLopez1011/PortafolioTitulo}"
ROLE_NAME="${ROLE_NAME:-github-actions-qla-deploy}"
USER_NAME="${USER_NAME:-github-actions-qla-deploy}"
REGION="${AWS_REGION:-$(aws configure get region 2>/dev/null || echo us-east-2)}"
AQUI="$(cd "$(dirname "$0")" && pwd)"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
PROVIDER_ARN="arn:aws:iam::${ACCOUNT}:oidc-provider/token.actions.githubusercontent.com"
POLICY=$(sed -e "s/__ACCOUNT__/${ACCOUNT}/g" -e "s/__REGION__/${REGION}/g" "$AQUI/github_deploy_policy.json")

echo ">> Cuenta $ACCOUNT, región $REGION, repo $REPO"

OIDC_OK=true
if ! aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$PROVIDER_ARN" >/dev/null 2>&1; then
  echo ">> Intentando crear proveedor OIDC de GitHub..."
  if ! aws iam create-open-id-connect-provider \
      --url https://token.actions.githubusercontent.com \
      --client-id-list sts.amazonaws.com \
      --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 >/dev/null 2>&1; then
    echo ">> AVISO: La cuenta tiene una SCP que bloquea crear proveedores OIDC. Cambiando a modo Usuario IAM + GitHub Secrets..."
    OIDC_OK=false
  fi
fi

if [ "$OIDC_OK" = true ]; then
  TRUST=$(cat <<JSON
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Federated": "$PROVIDER_ARN"},
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {"token.actions.githubusercontent.com:aud": "sts.amazonaws.com"},
      "StringLike": {"token.actions.githubusercontent.com:sub": [
        "repo:${REPO}:ref:refs/heads/main",
        "repo:${REPO}:environment:production"
      ]}
    }
  }]
}
JSON
  )
  if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
    aws iam update-assume-role-policy --role-name "$ROLE_NAME" --policy-document "$TRUST"
  else
    aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document "$TRUST" \
      --description "Despliegue CI/CD QLA desde GitHub Actions" --max-session-duration 3600 >/dev/null
  fi
  aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name qla-cicd-deploy --policy-document "$POLICY"
  ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query Role.Arn --output text)
  echo
  echo "Listo (Modo OIDC). Configura en GitHub > Settings > Secrets and variables > Actions > Variables:"
  echo "  AWS_ROLE_ARN = $ROLE_ARN"
  echo "  AWS_REGION   = $REGION"
  exit 0
fi

# Fallback: Usuario IAM con política de mínimo privilegio
if ! aws iam get-user --user-name "$USER_NAME" >/dev/null 2>&1; then
  echo ">> Creando usuario IAM $USER_NAME..."
  aws iam create-user --user-name "$USER_NAME" >/dev/null
fi

aws iam put-user-policy --user-name "$USER_NAME" --policy-name qla-cicd-deploy --policy-document "$POLICY"

# Limpiar llaves antiguas si ya tiene el máximo de 2
EXISTING_KEYS=$(aws iam list-access-keys --user-name "$USER_NAME" --query 'AccessKeyMetadata[].AccessKeyId' --output text)
COUNT=$(echo "$EXISTING_KEYS" | wc -w)
if [ "$COUNT" -ge 2 ]; then
  FIRST_KEY=$(echo "$EXISTING_KEYS" | awk '{print $1}')
  aws iam delete-access-key --user-name "$USER_NAME" --access-key-id "$FIRST_KEY"
fi

CREDS=$(aws iam create-access-key --user-name "$USER_NAME" --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text)
AK_ID=$(echo "$CREDS" | awk '{print $1}')
AK_SECRET=$(echo "$CREDS" | awk '{print $2}')

echo
echo "=================================================================="
echo "Listo (Modo IAM Secrets). Configura en tu repositorio de GitHub:"
echo "1) En Settings > Secrets and variables > Actions > Secrets (New repository secret):"
echo "   AWS_ACCESS_KEY_ID     = $AK_ID"
echo "   AWS_SECRET_ACCESS_KEY = $AK_SECRET"
echo
echo "2) En Settings > Secrets and variables > Actions > Variables (New repository variable):"
echo "   AWS_REGION            = $REGION"
echo "=================================================================="
