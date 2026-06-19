#!/usr/bin/env bash
# clear_cache.sh — clear in-memory cache of a service by sending a signal SIGHUP
#
# Usage:
#   bash clear_cache.sh --service <name> [--dry-run]
#
# Exit codes:
#   0 = success (or dry-run)
#   1 = failure

set -euo pipefail

SERVICE=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --service)  SERVICE="$2"; shift 2 ;;
    --dry-run)  DRY_RUN=true; shift ;;
    *) echo "Unknown arg: $1"; exit 1 ;;
  esac
done

if [[ -z "$SERVICE" ]]; then
  echo "[clear_cache] ERROR: --service <name> required"
  exit 1
fi

# Chuẩn hóa tên service và container
if [[ "$SERVICE" == ronki-* ]]; then
  SERVICE="${SERVICE#ronki-}"
fi
CONTAINER="ronki-${SERVICE}"

if $DRY_RUN; then
  echo "[DRY-RUN] would execute: docker kill --signal=SIGHUP $CONTAINER"
  exit 0
fi

echo "[clear_cache] Sending SIGHUP to $CONTAINER to flush cache..."
if ! docker inspect "$CONTAINER" > /dev/null 2>&1; then
  echo "[clear_cache] ERROR: container $CONTAINER not found."
  exit 1
fi

docker kill --signal=SIGHUP "$CONTAINER"
echo "[clear_cache] SIGHUP sent to $CONTAINER. Cache flush triggered."
exit 0
