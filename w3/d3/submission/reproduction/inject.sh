#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] intended target=billing"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] executing unscoped command: docker compose stop"
docker compose -f "$SCRIPT_DIR/docker-compose.yml" stop --timeout 1
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] billing, index, and placement stopped"
