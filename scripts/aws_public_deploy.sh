#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TF_DIR="${ROOT_DIR}/infra/terraform"

AWS_REGION="${AWS_REGION:-us-east-1}"
HOSTED_ZONE_NAME="${HOSTED_ZONE_NAME:-}"
HOSTED_ZONE_ID="${HOSTED_ZONE_ID:-}"
API_SUBDOMAIN="${API_SUBDOMAIN:-api}"
VPC_ID="${VPC_ID:-}"
SUBNET_IDS_CSV="${SUBNET_IDS_CSV:-}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
DESIRED_COUNT="${DESIRED_COUNT:-1}"
OLLAMA_MODEL="${OLLAMA_MODEL:-llama3.1}"
CORS_ALLOW_ORIGINS="${CORS_ALLOW_ORIGINS:-*}"
API_KEY_VALUE="${API_KEY_VALUE:-}"
AUTO_APPROVE="${AUTO_APPROVE:-false}"

usage() {
  cat <<'EOF'
Usage:
  scripts/aws_public_deploy.sh \
    --hosted-zone-name neweraon.com \
    --hosted-zone-id Z1234567890ABC \
    --vpc-id vpc-0123456789abcdef0 \
    --subnet-ids subnet-a,subnet-b

Options:
  --aws-region us-east-1
  --hosted-zone-name <domain>
  --hosted-zone-id <zone-id>
  --api-subdomain api
  --vpc-id <vpc-id>
  --subnet-ids <subnet-a,subnet-b>
  --image-tag latest
  --desired-count 1
  --ollama-model llama3.1
  --cors-allow-origins "*"
  --api-key-value "<strong-api-key>"   # optional
  --auto-approve                       # optional terraform auto-approve
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --aws-region) AWS_REGION="$2"; shift 2 ;;
    --hosted-zone-name) HOSTED_ZONE_NAME="$2"; shift 2 ;;
    --hosted-zone-id) HOSTED_ZONE_ID="$2"; shift 2 ;;
    --api-subdomain) API_SUBDOMAIN="$2"; shift 2 ;;
    --vpc-id) VPC_ID="$2"; shift 2 ;;
    --subnet-ids) SUBNET_IDS_CSV="$2"; shift 2 ;;
    --image-tag) IMAGE_TAG="$2"; shift 2 ;;
    --desired-count) DESIRED_COUNT="$2"; shift 2 ;;
    --ollama-model) OLLAMA_MODEL="$2"; shift 2 ;;
    --cors-allow-origins) CORS_ALLOW_ORIGINS="$2"; shift 2 ;;
    --api-key-value) API_KEY_VALUE="$2"; shift 2 ;;
    --auto-approve) AUTO_APPROVE="true"; shift 1 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1"; usage; exit 1 ;;
  esac
done

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: '$1' is not installed or not on PATH." >&2
    exit 1
  fi
}

if [[ -z "${HOSTED_ZONE_NAME}" || -z "${HOSTED_ZONE_ID}" || -z "${VPC_ID}" || -z "${SUBNET_IDS_CSV}" ]]; then
  echo "ERROR: Missing required values." >&2
  usage
  exit 1
fi

require_cmd aws
require_cmd terraform
require_cmd docker

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker daemon is not running. Start Colima or Docker Desktop first." >&2
  exit 1
fi

IFS=',' read -r -a SUBNET_ARRAY <<<"${SUBNET_IDS_CSV}"
if [[ "${#SUBNET_ARRAY[@]}" -lt 2 ]]; then
  echo "ERROR: Provide at least two subnet IDs (comma-separated)." >&2
  exit 1
fi

SUBNET_TF_LIST="["
for raw in "${SUBNET_ARRAY[@]}"; do
  subnet="$(echo "${raw}" | xargs)"
  if [[ -z "${subnet}" ]]; then
    continue
  fi
  if [[ "${SUBNET_TF_LIST}" != "[" ]]; then
    SUBNET_TF_LIST+=","
  fi
  SUBNET_TF_LIST+="\"${subnet}\""
done
SUBNET_TF_LIST+="]"

TF_VARS=(
  -var "aws_region=${AWS_REGION}"
  -var "hosted_zone_name=${HOSTED_ZONE_NAME}"
  -var "hosted_zone_id=${HOSTED_ZONE_ID}"
  -var "api_subdomain=${API_SUBDOMAIN}"
  -var "vpc_id=${VPC_ID}"
  -var "subnet_ids=${SUBNET_TF_LIST}"
  -var "ollama_model=${OLLAMA_MODEL}"
  -var "cors_allow_origins=${CORS_ALLOW_ORIGINS}"
)

TF_APPLY_ARGS=()
if [[ "${AUTO_APPROVE}" == "true" ]]; then
  TF_APPLY_ARGS+=("-auto-approve")
fi

echo "==> Terraform init"
(
  cd "${TF_DIR}"
  command terraform init
)

echo "==> Terraform apply (bootstrap with desired_count=0)"
(
  cd "${TF_DIR}"
  command terraform apply "${TF_APPLY_ARGS[@]}" \
    "${TF_VARS[@]}" \
    -var "image_tag=bootstrap" \
    -var "desired_count=0"
)

ECR_REPO_URL="$(cd "${TF_DIR}" && command terraform output -raw ecr_repository_url)"
API_KEY_SECRET_ARN="$(cd "${TF_DIR}" && command terraform output -raw api_key_secret_arn)"

if [[ -n "${API_KEY_VALUE}" ]]; then
  echo "==> Updating API key in Secrets Manager"
  command aws secretsmanager put-secret-value \
    --region "${AWS_REGION}" \
    --secret-id "${API_KEY_SECRET_ARN}" \
    --secret-string "${API_KEY_VALUE}" >/dev/null
else
  echo "==> Skipping API key update (set --api-key-value or API_KEY_VALUE to configure it now)"
fi

echo "==> ECR login"
command aws ecr get-login-password --region "${AWS_REGION}" \
  | command docker login --username AWS --password-stdin "${ECR_REPO_URL%/*}"

echo "==> Build and push API image: ${ECR_REPO_URL}:${IMAGE_TAG}"
command docker build -f "${ROOT_DIR}/docker/Dockerfile" -t "${ECR_REPO_URL}:${IMAGE_TAG}" "${ROOT_DIR}"
command docker push "${ECR_REPO_URL}:${IMAGE_TAG}"

echo "==> Terraform apply (service on)"
(
  cd "${TF_DIR}"
  command terraform apply "${TF_APPLY_ARGS[@]}" \
    "${TF_VARS[@]}" \
    -var "image_tag=${IMAGE_TAG}" \
    -var "desired_count=${DESIRED_COUNT}"
)

API_BASE_URL="$(cd "${TF_DIR}" && command terraform output -raw api_base_url)"
echo
echo "Deployment complete."
echo "API URL: ${API_BASE_URL}"
echo "Readiness: curl -sS ${API_BASE_URL}/readyz | python -m json.tool"
echo "Answer call:"
echo "curl -sS -X POST ${API_BASE_URL}/answer \\"
echo "  -H 'Content-Type: application/json' \\"
echo "  -H 'X-API-Key: <YOUR_API_KEY>' \\"
echo "  -d '{\"question\":\"What is SNAP?\"}' | python -m json.tool"
