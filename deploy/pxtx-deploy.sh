#!/usr/bin/env bash
# Deploy script for pxtx — triggered by systemd path unit.
# Runs as root (needs to restart the service), drops to PXTX_USER for app commands.
set -euo pipefail

PXTX_DIR="${PXTX_DIR:-/usr/share/webapps/pxtx}"
PXTX_USER="${PXTX_USER:-pxtx}"
FLAG_FILE="${PXTX_DEPLOY_FLAG_FILE:-$PXTX_DIR/data/deploy.flag}"
LOG_TAG="pxtx-deploy"

log() { logger -t "$LOG_TAG" "$@"; echo "[$(date -Is)] $*"; }

rm -f "$FLAG_FILE"

log "Deploy started"

cd "$PXTX_DIR"

log "Running git pull"
sudo -u "$PXTX_USER" git pull --ff-only

log "Running uv sync"
sudo -u "$PXTX_USER" uv sync

log "Running migrations"
sudo -u "$PXTX_USER" uv run python src/manage.py migrate --noinput

log "Collecting static files"
sudo -u "$PXTX_USER" uv run python src/manage.py collectstatic --noinput

log "Restarting pxtx service"
systemctl restart pxtx

log "Deploy completed"
