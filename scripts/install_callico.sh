#!/usr/bin/env bash
set -euo pipefail

IMAGE="${CALILCO_IMAGE:-registry.gitlab.teklia.com/callico/callico:0.6.0}"
COMPOSE_FILE="${CALILCO_COMPOSE_FILE:-$(dirname "$0")/docker-compose.callico.yml}"
SERVICE_NAME="${CALILCO_SERVICE_NAME:-callico}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Error: docker is required to install Callico." >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "Error: docker compose v2 is required. Install Docker Compose Plugin or Docker Desktop >= 20.10." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Warning: Docker daemon does not appear to be running." >&2
  exit 1
fi

export CALILCO_IMAGE="$IMAGE"

cat <<MSG
Using Callico image: "$CALILCO_IMAGE"
If the image is hosted on Teklia's private registry, ensure you are logged in first:
  docker login registry.gitlab.teklia.com
MSG

# Pull the published image as recommended by the official deployment guide.
docker compose -f "$COMPOSE_FILE" pull "$SERVICE_NAME"

# Start Callico using docker compose without cloning any Git repository.
docker compose -f "$COMPOSE_FILE" up -d "$SERVICE_NAME"

cat <<MSG
Callico should now be running. View logs with:
  docker compose -f "$COMPOSE_FILE" logs -f "$SERVICE_NAME"
MSG
