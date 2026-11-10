#!/bin/bash
# Configuración ÚNICA en la cuenta AWS para que GitHub Actions despliegue sin claves (OIDC).
# Requisitos: AWS CLI con credenciales de administrador de la cuenta, jq.
# Uso:
#   ./setup_github_oidc.sh                       # repo por defecto MartinLopez1011/PortafolioTitulo
#   EC2_ROLE=MiRolEC2 ./setup_github_oidc.sh     # además da permiso ECR de lectura al rol de la EC2
set -euo pipefail

REPO="${REPO:-MartinLopez1011/PortafolioTitulo}"
ROLE_NAME="${ROLE_NAME:-github-actions-qla-deploy}"
REGION="${AWS_REGION:-us-east-1}"
AQUI="$(cd "$(dirname "$0")" && pwd)"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
PROVIDER_ARN="arn:aws:iam::${ACCOUNT}:oidc-provider/token.actions.githubusercontent.com"

echo ">> Cuenta $ACCOUNT, región $REGION, repo $REPO"

if ! aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$PROVIDER_ARN" >/dev/null 2>&1; then
  echo ">> Creando proveedor OIDC de GitHub"
  aws iam create-open-id-connect-provider \
    --url https://token.actions.githubusercontent.com \
    --client-id-list sts.amazonaws.com \
    --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1 >/dev/null
else
  echo ">> Proveedor OIDC ya existe"
fi

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
  echo ">> Actualizando trust policy de $ROLE_NAME"
  aws iam update-assume-role-policy --role-name "$ROLE_NAME" --policy-document "$TRUST"
else
  echo ">> Creando rol $ROLE_NAME"
  aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document "$TRUST" \
    --description "Despliegue CI/CD QLA desde GitHub Actions" --max-session-duration 3600 >/dev/null
fi

POLICY=$(sed -e "s/__ACCOUNT__/${ACCOUNT}/g" -e "s/__REGION__/${REGION}/g" "$AQUI/github_deploy_policy.json")
aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name qla-cicd-deploy --policy-document "$POLICY"
echo ">> Política de mínimo privilegio aplicada"

if [ -n "${EC2_ROLE:-}" ]; then
  aws iam attach-role-policy --role-name "$EC2_ROLE" \
    --policy-arn arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly
  aws iam attach-role-policy --role-name "$EC2_ROLE" \
    --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
  echo ">> Rol de la EC2 ($EC2_ROLE) con lectura ECR + SSM"
fi

ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query Role.Arn --output text)
echo
echo "Listo. Configura en GitHub (Settings > Secrets and variables > Actions > Variables):"
echo "  AWS_ROLE_ARN = $ROLE_ARN"
echo "  AWS_REGION   = $REGION"
echo "o con gh CLI:"
echo "  gh variable set AWS_ROLE_ARN -R $REPO -b '$ROLE_ARN'"
echo "  gh variable set AWS_REGION   -R $REPO -b '$REGION'"
