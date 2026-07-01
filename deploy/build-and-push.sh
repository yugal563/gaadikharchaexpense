#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ACR_NAME="${ACR_NAME:-gkexpensedevacr}"
RESOURCE_GROUP="${RESOURCE_GROUP:-GK-Azure_Pocs}"
TAG="${TAG:-latest}"

PLATFORM="${PLATFORM:-linux/amd64}"

cd "$ROOT"

BUILD_ONLY="${BUILD_ONLY:-false}"

if [[ "$BUILD_ONLY" != "true" ]]; then
  echo "==> Logging into ACR $ACR_NAME"
  az acr login --name "$ACR_NAME"
fi

for STAGE in 1 2 3 4 5 6; do
  case $STAGE in
    1) DOCKERFILE_PATH="pipeline/stage1_validation/Dockerfile" ;;
    2) DOCKERFILE_PATH="pipeline/stage2_preprocessing/Dockerfile" ;;
    3) DOCKERFILE_PATH="pipeline/stage3_extraction/Dockerfile" ;;
    4) DOCKERFILE_PATH="pipeline/stage4_mapping/Dockerfile" ;;
    5) DOCKERFILE_PATH="pipeline/stage5_filtering/Dockerfile" ;;
    6) DOCKERFILE_PATH="pipeline/stage6_db_service/Dockerfile" ;;
  esac
  IMAGE="$ACR_NAME.azurecr.io/stage${STAGE}:${TAG}"
  LOCAL_IMAGE="gk-expense-stage${STAGE}:local"
  echo "==> Building $IMAGE (platform=$PLATFORM)"
  docker build --platform "$PLATFORM" -f "$DOCKERFILE_PATH" -t "$IMAGE" -t "$LOCAL_IMAGE" .
  if [[ "$BUILD_ONLY" != "true" ]]; then
    echo "==> Pushing $IMAGE"
    docker push "$IMAGE"
  fi
done

if [[ "$BUILD_ONLY" == "true" ]]; then
  echo "==> All stage images built locally (BUILD_ONLY=true, skipped push)."
else
  echo "==> All stage images built and pushed."
fi
