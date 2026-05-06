#!/bin/bash
# postgres-init.sh — Postgres-DB fuer WP State Machine auf .10 einrichten
# Ausfuehren als: bash postgres-init.sh
set -euo pipefail

DB_NAME="wp_state_machine"
DB_USER="wp_sm"
DB_PASS="${WP_SM_DB_PASS:-CHANGEME_BITTE}"
SCHEMA_FILE="/opt/wp-state-machine/src/wp_state_machine/storage/schema.sql"

echo "=== Postgres-Init fuer WP State Machine ==="
echo "DB: ${DB_NAME}, User: ${DB_USER}"
echo ""

# User anlegen (falls nicht vorhanden)
sudo -u postgres psql -c "
  DO \$\$
  BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
      CREATE ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASS}';
    END IF;
  END
  \$\$;
"

# Datenbank anlegen
sudo -u postgres createdb -O "${DB_USER}" "${DB_NAME}" 2>/dev/null || echo "DB ${DB_NAME} existiert bereits"

# Schema anwenden
sudo -u postgres psql -d "${DB_NAME}" -f "${SCHEMA_FILE}"

echo ""
echo "=== Postgres-Init abgeschlossen ==="
echo "URL: postgresql://${DB_USER}:${DB_PASS}@localhost:5432/${DB_NAME}"
echo "Bitte in .env eintragen: POSTGRES_URL=postgresql://${DB_USER}:${DB_PASS}@192.168.178.10:5432/${DB_NAME}"
