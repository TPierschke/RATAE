#!/bin/bash
# deploy.sh — WP State Machine auf nucthp1 (.10) deployen
# Voraussetzung: SSH-Key fuer user@192.168.178.10 eingerichtet
set -euo pipefail

TARGET_HOST="${DEPLOY_HOST:-192.168.178.10}"
TARGET_USER="${DEPLOY_USER:-thp}"
TARGET_DIR="/opt/wp-state-machine"
SERVICE_NAME="wp-state-machine"

echo "=== WP State Machine Deploy ==="
echo "Ziel: ${TARGET_USER}@${TARGET_HOST}:${TARGET_DIR}"
echo ""

# Lokale Tests ausfuehren
echo "--- Lokale Tests ---"
PYTHONPATH=src python3 -m pytest tests/ -x -q --no-header
echo "Tests OK"
echo ""

# Rsync (ohne .git, ohne __pycache__, ohne .env)
echo "--- Sync Quellcode ---"
rsync -av --progress \
  --exclude='.git' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.env' \
  --exclude='*.log' \
  --exclude='wp_state.json' \
  . "${TARGET_USER}@${TARGET_HOST}:${TARGET_DIR}/"

echo "--- Remote Setup ---"
ssh "${TARGET_USER}@${TARGET_HOST}" bash << 'REMOTE'
  set -euo pipefail
  TARGET_DIR="/opt/wp-state-machine"

  # Python-Abhaengigkeiten installieren
  python3 -m pip install --break-system-packages -r "${TARGET_DIR}/requirements.txt"

  # .env anlegen wenn nicht vorhanden
  if [ ! -f "${TARGET_DIR}/.env" ]; then
    cp "${TARGET_DIR}/.env.example" "${TARGET_DIR}/.env"
    echo "WARNUNG: .env angelegt aus .env.example — bitte anpassen!"
  fi

  # config.toml anlegen wenn nicht vorhanden
  if [ ! -f "${TARGET_DIR}/config.toml" ]; then
    cp "${TARGET_DIR}/config.example.toml" "${TARGET_DIR}/config.toml"
    echo "WARNUNG: config.toml angelegt aus config.example.toml — bitte pruefen!"
  fi

  echo "Remote-Setup OK"
REMOTE

echo "--- systemd Service ---"
ssh "${TARGET_USER}@${TARGET_HOST}" bash << REMOTE
  set -euo pipefail
  sudo cp "${TARGET_DIR}/deploy/systemd/${SERVICE_NAME}.service" /etc/systemd/system/
  sudo systemctl daemon-reload
  sudo systemctl enable ${SERVICE_NAME}
  sudo systemctl restart ${SERVICE_NAME}
  sleep 2
  sudo systemctl status ${SERVICE_NAME} --no-pager
REMOTE

echo ""
echo "=== Deploy abgeschlossen ==="
echo "Service-Status: ssh ${TARGET_USER}@${TARGET_HOST} systemctl status ${SERVICE_NAME}"
echo "Logs: ssh ${TARGET_USER}@${TARGET_HOST} journalctl -u ${SERVICE_NAME} -f"
echo "Web-UI: http://${TARGET_HOST}:8765/"
