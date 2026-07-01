#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ACR_NAME="${ACR_NAME:-gkexpensedevacr}"
RESOURCE_GROUP="${RESOURCE_GROUP:-GK-Azure_Pocs}"
TAG="${TAG:-latest}"

cd "$ROOT"

"$ROOT/deploy/build-and-push.sh"

ACR_LOGIN_SERVER=$(az acr show -n "$ACR_NAME" -g "$RESOURCE_GROUP" --query loginServer -o tsv)
ACR_USER=$(az acr credential show -n "$ACR_NAME" --query username -o tsv)
ACR_PASS=$(az acr credential show -n "$ACR_NAME" --query "passwords[0].value" -o tsv)

CONN_STR=$(az storage account show-connection-string -n gkexpensedevstorage -g "$RESOURCE_GROUP" -o tsv)
SB_CONN=$(az servicebus namespace authorization-rule keys list \
  --namespace-name gkexpense-dev-bus -g "$RESOURCE_GROUP" \
  --name RootManageSharedAccessKey --query primaryConnectionString -o tsv)

for STAGE in 1 2 3 4 5 6; do
  APP="gk-expense-dev-stage${STAGE}"
  IMAGE="${ACR_LOGIN_SERVER}/stage${STAGE}:${TAG}"

  echo "==> Configuring $APP -> $IMAGE"

  az functionapp config container set \
    -g "$RESOURCE_GROUP" -n "$APP" \
    --docker-custom-image-name "$IMAGE" \
    --docker-registry-server-url "https://${ACR_LOGIN_SERVER}" \
    --docker-registry-server-user "$ACR_USER" \
    --docker-registry-server-password "$ACR_PASS"

  az functionapp config appsettings set -g "$RESOURCE_GROUP" -n "$APP" --settings \
    "WEBSITES_ENABLE_APP_SERVICE_STORAGE=false" \
    "AZURE_STORAGE_CONNECTION_STRING=$CONN_STR" \
    "AZURE_STORAGE_CONTAINER=receipt-stage${STAGE}" \
    "AZURE_SERVICEBUS_CONNECTION_STRING=$SB_CONN" \
    "ServiceBusConnection=$SB_CONN" \
    "AZURE_QUEUE_STAGE${STAGE}=receipt-stage${STAGE}" \
    "STAGE_NUMBER=${STAGE}" \
    "DB_HOST=127.0.0.1" \
    "DB_PORT=3307" \
    "DB_USER=root" \
    "DB_PASSWORD=1234" \
    "DB_NAME=expenses" \
    "SINGLE_PASS_MODE=true" \
    --output none

  az functionapp config appsettings delete -g "$RESOURCE_GROUP" -n "$APP" \
    --setting-names FASTAPI_BASE_URL 2>/dev/null || true

  az functionapp restart -g "$RESOURCE_GROUP" -n "$APP"
done

echo "==> Purging stuck messages from Service Bus queues"
for STAGE in 1 2 3 4 5 6; do
  az servicebus queue purge \
    --namespace-name gkexpense-dev-bus \
    -g "$RESOURCE_GROUP" \
    --name "receipt-stage${STAGE}" 2>/dev/null || true
done

echo "==> Deployment complete."
