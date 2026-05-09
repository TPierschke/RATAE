# RATAE — Wärmepumpen-State-Machine

Zentrale Python-basierte Steuerung für private Wärmepumpenanlage (Heizkreis + Warmwasser).
**Version 0.1** | Phase 1 (DRY_RUN aktiv) | 368 Tests grün | Python 3.14 + FastAPI + Modbus-Slave

---

## Status

| Aspekt | Status |
|--------|--------|
| **Tests** | 368 passing |
| **DRY_RUN** | aktiv (Live-Writes blockiert bis `DRY_RUN=false`) |
| **Modbus-Slave** | Port 5020 aktiv, primäre Datenquelle |
| **Postgres-Telemetrie** | aktiv auf nucthp (.10), 5-min-Snapshots |
| **Web-UI** | FastAPI auf Port 8765 |
| **Phase** | 1 — Datenerfassung + Read-Only-API validieren |

---

## Architektur

```
UVR1611 (Heizung) + CMI (Controller)
          |
      CAN-Bus (UVR → CMI-NetzOutput)
          |
         CMI 192.168.178.45
          |
   [Modbus-TCP Push] ← primär
   [Web-Scraper]    ← fallback (wenn Modbus > 300s stale)
          |
    WP State Machine (Mac .3)
          |
    ┌─────┼─────┐
    |     |     |
  REST  SSE  Postgres
  :8765 /stream  (telemetry + audit)
    |     |     |
   [Web-UI] [Logger] [Dashboard]
```

**Datenfluss:**
- **CMI** ist Modbus-Master, schreibt aktiv FC16 (Registers) + FC05 (Coils) an Port 5020
- **State Machine** dekodiert Modbus, speichert in Postgres, exposiert REST + SSE
- **Web-Scraper** startet nur wenn Modbus > 300s inaktiv (Fallback-Pfad)

---

## Quickstart

### Voraussetzungen
- Python 3.14+
- Postgres 17+ (asyncpg)
- Homebrew Python an `/opt/homebrew/bin/python3`
- CMI 192.168.178.45 erreichbar

### Installation
```bash
git clone <repo> wp-state-machine && cd wp-state-machine
pip install --break-system-packages -r requirements.txt

# oder editierbar:
pip install --break-system-packages -e .
```

### Konfiguration
```bash
cp .env.example .env
# Anpassen: CMI_USER, CMI_PASS, WPSM_POSTGRES_URL, TELEGRAM_TOKEN
cp config.example.toml config.toml
```

### Ausführung
```bash
# DRY_RUN (default)
python3 -m wp_state_machine

# oder mit angepasstem Port:
python3 -m wp_state_machine --port 8765

# LIVE-Modus (VORSICHT!)
python3 -m wp_state_machine --dry-run-off
```

### Tests
```bash
pytest tests/ -v
pytest --cov=wp_state_machine tests/
```

---

## Konfiguration

### Umgebungsvariablen (`.env`)
```env
DRY_RUN=true                 # Default: Schreib-Calls geloggt, nicht ausgeführt
LOG_LEVEL=INFO
PORT=8765
CMI_HOST=192.168.178.45
CMI_USER=admin
CMI_PASS=admin
WPSM_POSTGRES_URL=postgresql://wp_sm:PASS@192.168.178.10/wp_state_machine
TELEGRAM_TOKEN=...
TELEGRAM_CHAT_ID=...
MODBUS_PORT=5020
```

### Strukturierte Config (`config.toml`)
```toml
[modbus]
enabled = true
port = 5020
slave_id = 1

[modbus.sensor_offsets]
vorlauf = 0.0        # Sensor-Kalibrierung (offset)
ruecklauf = 0.0
```

---

## API-Endpunkte

### Read-Only
- **GET** `/` — Web-UI (HTML)
- **GET** `/health` — Status (dry_run, modbus_ok, postgres_ok, last_update)
- **GET** `/state` — Aktueller WP-State + alle Sensoren
- **GET** `/telemetry` — aktuell Sensor-Snapshot
- **GET** `/functions/{id}` — F:1 (Heizkreis) oder F:9 (Warmwasser)
- **GET** `/stream` — Server-Sent-Events (3s-Tick, Live-Updates)

### Write (alle DRY_RUN-geschützt + Whitelist)
- **POST** `/functions/F1/betriebsart` — 1..7 (Standby, Zeit, Normal, etc.)
- **POST** `/functions/F1/normalsoll` — 10..30 °C
- **POST** `/functions/F1/absenksoll` — 5..25 °C
- **POST** `/functions/F9/wwsoll` — 30..70 °C
- **POST** `/functions/F9/start` — WW-Boost (Legionellenschutz)
- **POST** `/functions/F9/stop` — WW-Boost stoppen

Alle Schreib-Calls werden geloggt + in `function_audit`-Tabelle dokumentiert.

---

## Modbus-Register

### Holding-Register (Analog)

| Addr | Sensor | Typ | Faktor | Bemerkung |
|------|--------|-----|--------|-----------|
| 1 | Aussentemperatur | int16 | 0.01 | M1 (C1) |
| 2 | Vorlauf | int16 | 0.01 | M2 (C2) |
| 3 | Rücklauf | int16 | 0.01 | M3 (C3) |
| 4 | Warmwasser | int16 | 0.01 | M4 (C4) |
| 6 | TRaum1 | int16 | 0.01 | M6 (C6) |
| 7 | Heissgas | int16 | 0.01 | M7 (C7) |
| 8 | Flüssigkeit | int16 | 0.01 | M8 (C8) |
| 9 | Saugleitung | int16 | 0.01 | M9 (C9) |
| 10–11 | BetrStdVerdichter | uint32 | 1.0 | 2 Register |
| 12–13 | SchaltungenVerdichter | uint32 | 1.0 | 2 Register |
| 14–15 | BetrStdHeizstabFB | uint32 | 1.0 | 2 Register |
| 16–17 | BetrStdHeizstabWW | uint32 | 1.0 | 2 Register |
| 18 | MessageFB | uint16 | 1.0 | |
| 19 | MessageWW | uint16 | 1.0 | |
| 20 | VorlaufSoll | int16 | 0.01 | |

**Coils** (Digital): 1–16 (Phasenwaechter, Verdichter, ND/HD, Pumpen, Ventile, Heizstaebe)

**Adress-Schema:** CMI-Seite `outmag=N` → Wire-Adresse `N+1` (1-based).

---

## Sicherheit

### Whitelist (safety.py)

Nur folgende Adressen + Wertebereiche sind erlaubt:

| Adresse | Funktion | Wert | Beschreibung |
|---------|----------|------|--------------|
| `3E9001301C` | F:1 | 1–7 | Betriebsart (Standby..Feiertag) |
| `3EB001300C` | F:1 | 10–30 °C | Normal-Soll Heizkreis |
| `3EB001300D` | F:1 | 5–25 °C | Absenk-Soll Heizkreis |
| `3EB0023118` | F:9 | 30–70 °C | WW-Soll (Legionellenschutz) |
| `3E80093125` | F:9 | 1 | WW-Boost START |
| `3E80093126` | F:9 | 1 | WW-Boost STOP |

### Verboten
- `3E91*` — direkte Aktor-Ausgänge A1–A10 (umgehen UVR-Logik)
- `3E80153125`, `3E80153126` — Heizstab-Direct (nur via F:9 mit Eskalation)

### Sicherheits-Imperative

1. **DRY_RUN=true** (default) — Writes werden geloggt, nicht ausgeführt
2. **Whitelist-Enforcement** — `check_write()` entscheidet alle Writes
3. **Audit-Logging** — jeder Versuch in `function_audit`-Tabelle
4. **Telegram-Alarm** — bei jedem LIVE-Write
5. **Cool-Down** — Rate-Limit 1 req/sec gegen CMI-Überlast

---

## Repo-Layout

```
wp-state-machine/
├── src/wp_state_machine/
│   ├── __main__.py           # Startup (FastAPI + Poll-Loop + Heartbeat)
│   ├── api/rest.py           # REST-Endpunkte + AppState
│   ├── ingest/
│   │   ├── modbus_slave.py   # Modbus-TCP-Slave (primäre Datenquelle)
│   │   ├── web_scraper.py    # CMI-Web-UI-Scraper (Fallback)
│   │   └── cmi_writer.py     # HTTP-Write-Pfad ans CMI (menupage.cgi)
│   ├── core/models.py         # Pydantic-Modelle (Sensoren, WPState)
│   ├── safety.py              # Whitelist-Enforcement
│   ├── storage/
│   │   ├── postgres.py        # asyncpg-Adapter
│   │   └── schema.sql         # DB-Schema (telemetry, function_audit)
│   ├── automation/
│   │   ├── snapshot_logger.py # 5-min-Telemetrie-Snapshots
│   │   └── coil_audit.py      # Alarm/Verdichter-Edge-Handler
│   └── config.py              # Config-Loader (.env + config.toml)
├── tests/
│   ├── test_modbus_slave.py   # Dekodierungs-Tests (decode_register/coil)
│   ├── test_api.py            # REST-Endpoint-Tests
│   ├── test_safety.py         # Whitelist-Tests
│   └── fixtures/              # Snapshot-Daten
├── tools/
│   ├── cmi_bulk_modbus_setup.py      # Analog-Output-Mapping (M1..M16)
│   ├── cmi_bulk_modbus_digital.py    # Digital-Output-Mapping (M-1..M-16)
│   ├── cmi_verify_full.py            # Verifizierung der CMI-Config
│   ├── modbus_test_slave.py          # Standalone-Debug-Slave
│   └── plausibility_check.py         # Sensor-Plausibilitätsprüfung
├── docs/
│   ├── CMI-WRITE-API.md       # Adressen-Tabelle + Verbotene-Adressen
│   └── ARCHITECTURE.md        # Detaillierte Architektur
├── deploy/
│   ├── deploy.sh              # Push auf .10 (SSH + systemd-reload)
│   └── postgres-init.sh       # DB-Initialisierung
├── .env.example               # Template
├── config.example.toml        # Template
├── requirements.txt           # Dependencies (FastAPI, pymodbus 3.8, asyncpg)
└── README.md                  # Diese Datei
```

---

## Tools

### CMI-Setup (einmalig, vor LIVE)
```bash
python3 tools/cmi_bulk_modbus_setup.py      # Analog-Outputs auf .3 mappen
python3 tools/cmi_bulk_modbus_digital.py    # Digital-Outputs auf .3 mappen
python3 tools/cmi_verify_full.py            # Konfiguration verifizieren
```

### Debugging
```bash
# Standalone-Modbus-Slave (zeigt alle CMI-Writes)
python3 tools/modbus_test_slave.py

# Sensor-Plausibilität prüfen
python3 tools/plausibility_check.py
```

---

## Bekannte Limitierungen

1. **DRY_RUN noch nicht scharf** — Phase 1. Live-Mode wird später freigegeben.
2. **Web-Scraper ↔ Modbus Revival** — Bei Modbus-Wiederherstellung nach Stale kann es zu Race-Conditions kommen (Edge-Case).
3. **Telemetry-Insert 32 Parameter** — `insert_telemetry()` hat 32 positional-$-Variablen in SQL (Wartungs-Risiko, Refactoring pending).
4. **Keine echten Integration-Tests** — nur Unit-Tests gegen Fixtures. Live-CMI-Tests folgen nach Phase 1 Abnahme.
5. **Modbus Offset-Kalibrierung** — sensor_offsets in config.toml sind placeholder, erst nach Feldmessung setzen.

---

## Deployment

### Lokal (Mac)
```bash
# Port 5020 braucht keine Root-Rechte (< 1024)
python3 -m wp_state_machine --port 8765
```

### Remote (.10, Debian 12)
```bash
cd <repo>
bash deploy/deploy.sh          # SSH-basiert, systemd-reload
bash deploy/postgres-init.sh   # DB-Schema initialisieren
```

Postgres-Schema wird automatisch beim Startup angewendet (falls `WPSM_POSTGRES_URL` gesetzt).

---

## Lizenz

[**PolyForm Noncommercial 1.0.0**](https://polyformproject.org/licenses/noncommercial/1.0.0) — siehe [`LICENSE`](LICENSE).

Heisst: Privat, fuer Forschung, Bildung, Hobby, gemeinnuetzige Organisationen — frei nutzbar.
**Kommerzielle Nutzung untersagt.**

---

## Support

**Works for me. Fork if you need changes.**

Es gibt keinen Support. Issues werden nicht beantwortet, Pull Requests nicht reviewed,
Bugs nicht gefixt. Schaeden durch Nutzung dieser Software liegen ausschliesslich beim
Anwender — keine Garantie, keine Haftung. Siehe [`LICENSE`](LICENSE) Abschnitt
"No Liability".

Wenn du was anderes brauchst: fork das Repo und mach es selber.

---

## Projekt

**RATAE** — Codename der Waermepumpen-Steuerung der Anlage Pierschke (private installation).
