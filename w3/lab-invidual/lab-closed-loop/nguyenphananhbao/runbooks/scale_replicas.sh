#!/usr/bin/env bash
# scale_replicas.sh — scale a Docker Compose service to N replicas
#
# Usage:
#   bash scale_replicas.sh --service <name> [--replicas <N>] [--dry-run]
#
# Exit codes:
#   0 = success (or dry-run)
#   1 = failure

set -euo pipefail

SERVICE=""
REPLICAS=2
DRY_RUN=false

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/../configs/docker-compose.yml"
# Nếu không tìm thấy ở thư mục cha trực tiếp (khi chạy từ nguyenphananhbao/), 
# tìm ở ../data-pack/configs/docker-compose.yml hoặc configs/docker-compose.yml
if [[ ! -f "$COMPOSE_FILE" ]]; then
  COMPOSE_FILE="$SCRIPT_DIR/../../data-pack/configs/docker-compose.yml"
fi

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service)   SERVICE="$2";   shift 2 ;;
    --replicas)  REPLICAS="$2";  shift 2 ;;
    --dry-run)   DRY_RUN=true;   shift ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

if [[ -z "$SERVICE" ]]; then
  echo "[scale_replicas] ERROR: --service <name> required"
  exit 1
fi

# Chuẩn hóa tên service (Docker compose dùng service name trong yaml file)
if [[ "$SERVICE" == ronki-* ]]; then
  SERVICE="${SERVICE#ronki-}"
fi

if $DRY_RUN; then
  echo "[DRY-RUN] would execute: docker compose -f $COMPOSE_FILE up -d --scale ${SERVICE}=${REPLICAS} --no-recreate"
  exit 0
fi

echo "[scale_replicas] Scaling $SERVICE to $REPLICAS replicas..."
docker compose -f "$COMPOSE_FILE" up -d --scale "${SERVICE}=${REPLICAS}" --no-recreate

echo "[scale_replicas] Scale command sent for $SERVICE → $REPLICAS replicas."
exit 0
