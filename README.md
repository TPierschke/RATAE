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

## Playwright Setup (SPA-Scraping)

Fuer JavaScript-rendernde Seiten (CMI-Web-UI, SPAs wo curl nur Skelett liefert):

```bash
# Playwright installieren (system-pip, kein venv)
python3 -m pip install --break-system-packages playwright

# Chromium-Browser herunterladen (~250 MB, landet in ~/Library/Caches/ms-playwright/)
python3 -m playwright install chromium

# Verifizieren
python3 -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_page()
    page.goto('https://example.com')
    print(page.title())
    b.close()
"
# Erwartet: Example Domain
```

**Versionen (2026-05-06):** Playwright 1.59.0, Chrome for Testing 147.0.7727.15 (chromium-1217).
Disk-Verbrauch: ~260 MB in `~/Library/Caches/ms-playwright/`.

### CMI Playwright Probe

`tools/cmi_playwright_probe.py` liest CoE-Output-Konfigurationen vom CMI (192.168.178.45):

```bash
python3 tools/cmi_playwright_probe.py
# Ergebnis: tools/cmi_e_outputs.json
```

**Architektur-Hinweis:** Die CMI-Web-UI ist eine SPA (cmi142.js / jQuery). Der
Detail-Endpunkt fuer E-Outputs ist `settings_output-E.cgi?cmioutput=<X>` —
er liefert ein HTML-Fieldset direkt (kein weiteres AJAX). Das Skript nutzt
Playwright fuer HTTP-Auth und kuenftige echte SPA-Targets. Rate-Limit: 5s
zwischen Requests, bei HTTP 429 Abbruch + 60s Pause.

## Sicherheits-Imperative

1. Schreiben nur via menupage.cgi (Browser-Emulation), nie JSON-API-writes.
2. Funktionen schalten, nicht Aktoren.
3. Heizstaebe A8/A9 sind DANGEROUS — direkte Schaltung gesperrt.
4. DRY_RUN=True bis explizite Freigabe.
5. CMI Rate-Limit: 1 req/sek max, 1/min beim Polling.
