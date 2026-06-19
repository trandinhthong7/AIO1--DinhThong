#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting billing, index, and placement"
docker compose -f "$SCRIPT_DIR/docker-compose.yml" start
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] all reproduction services started"
