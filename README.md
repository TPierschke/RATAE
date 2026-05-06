# wp-state-machine

**Version:** 0.1  
**Status:** Phase 1 — DRY_RUN aktiv, kein echter CMI-Schreibzugriff  
**Deploy-Target:** FHEM-Server `192.168.178.10` (Debian 12)

Zentrale State Machine fuer die Waermepumpe (CMI 192.168.178.45). Einzige Komponente
die TCP/IP zum CMI macht. Alle anderen Systeme (FHEM, HA, Telegram) reden mit ihr.

## Architektur

```
FHEM / HA / Telegram / ThoPAS
           |
    WP STATE MACHINE  (REST + MQTT + Web-UI)
           |
          CMI  192.168.178.45  (einziger Zugriff)
```

## Schnell-Start (lokale Entwicklung)

Voraussetzung: Python 3.11+ via Homebrew (`/opt/homebrew/bin/python3`).

```bash
# Abhaengigkeiten installieren (kein venv noetig)
pip install --break-system-packages -r requirements.txt

# Oder als editierbares Paket
pip install --break-system-packages -e .

# Env-File anlegen
cp .env.example .env
# .env anpassen (Postgres-URL, Telegram-Token etc.)

# Config anlegen
cp config.example.toml config.toml

# Starten
python3 -m wp_state_machine

# Tests ausfuehren
pytest tests/ -v

# Linting
ruff check src/
black --check src/
```

## DRY_RUN-Modus

Phase 1 ist DRY_RUN by default. Kein echter CMI-Schreibzugriff.  
Im Web-UI erscheint ein sichtbarer "DRY-RUN"-Banner.  
Zum Deaktivieren: `DRY_RUN=false` in `.env` setzen — **nur nach expliziter Freigabe!**

## Konfiguration

Alle Secrets in `.env` (nicht einchecken, in `.gitignore`).  
Strukturierte Config in `config.toml` (aus `config.example.toml`).

## Abhaengigkeiten

Installiert via `pip install --break-system-packages -r requirements.txt`.  
Kein virtualenv. Kein Docker. System-Python Homebrew.

## Deploy

Deploy-Skript und systemd-Unit unter `deploy/`:

```bash
# Auf .10 deployen (SSH-Key erforderlich)
bash deploy/deploy.sh
```

Postgres-Init: `bash deploy/postgres-init.sh`

## Coverage

Tests laufen gegen Fixture-Snapshots aus `tests/fixtures/` (kein Live-CMI).

```bash
pytest --cov=wp_state_machine --cov-report=term-missing tests/
```

## Sicherheits-Imperative

1. Schreiben nur via menupage.cgi (Browser-Emulation), nie JSON-API-writes.
2. Funktionen schalten, nicht Aktoren.
3. Heizstaebe A8/A9 sind DANGEROUS — direkte Schaltung gesperrt.
4. DRY_RUN=True bis explizite Freigabe.
5. CMI Rate-Limit: 1 req/sek max, 1/min beim Polling.
