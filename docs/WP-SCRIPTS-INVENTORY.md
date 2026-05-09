# WP-Skripte und Logik — Inventur

Stand: 2026-05-06. Vor Migration auf die WP-State-Machine.
Quelle: SSH-Suche ueber alle Hosts in `~/.ssh/config`.

## Hosts geprueft

| Host | IP | User | Status |
|---|---|---|---|
| Mac lokal | - | thp | siehe unten |
| nucthp (FHEM) | 192.168.178.10 | nibbles | siehe unten |
| pihole | 192.168.178.5 | nibbles | nichts gefunden |
| proxmox | 192.168.178.17 | root | nichts gefunden |
| haos | 192.168.178.19 | root | siehe unten |

## nucthp — die zentrale WP-Logik

### `/opt/fhem/FHEM/99_myUtilsTACMIHTTP.pm`

Perl-Modul mit 8 Funktionen die direkt ans CMI schreiben (menupage.cgi):

- `wpbetriebsart(arg)` — F:1 Betriebsart 1..7
- `wpnormalsoll(temp)` — F:1 Normal-Soll
- `wpabsenktemp(temp)` — F:1 Absenk-Soll
- `wpwwsoll(temp)` — F:9 WW-Soll
- `wpwwjetzt(start|stop)` — F:9 WW-Boost ein/aus
- `wpwwzirkulation(auto|start|stop)` — Aktor-Direkt-Schaltung Zirku-Pumpe
- `wpfbheizkrpumpe(auto|start|stop)` — Aktor-Direkt-Schaltung FBH-Pumpe
- `wpfbheizstab(start|stop)` — Direkter Heizstab-Schaltung (POTENTIELL DESTRUKTIV)

Aufruf ueber FHEM-DOIF / Notify / `set DI_WPSteuerung wwjetzt start` → triggert `wpwwjetzt`.

### `/opt/fhem/fhem.cfg` — die laufende Steuer-Logik

- **`DI_FreigabeWWHeizstab`** — kompletter DOIF mit Tibber-Preis + Senec-Akku-Stand:
  - schaltet WW-Boost ein wenn Bedingungen passen
  - blockiert Heizstab bei zu hohem Netzbezug
  - nightlySelfReset
  - Aufruf-Pfad: → `set DI_WPSteuerung wwjetzt start` → Perl `wpwwjetzt("start")` → `menupage.cgi?changeadr=3E80093125`
- **`DI_WPSteuerung`** — Container-DOIF mit Notify-Hooks:
  - `wwjetzt` (start/stop/running) → ruft Perl-Funktion
  - `Normalsoll` (für Tibber-Hochheize-Strategie)
  - `wwzirkulation`, `fbheizkrpumpe`, `wwsoll`
- **WP-Hochheiz-Strategie** (~Zeile 2090..2230): Tibber-best-Window suchen, Normalsoll temporaer auf 24..26 °C anheben, WP heizt vor billigem Strom voll, danach zurueck

### `/home/nibbles/scripts/legionellenschutz_v2.py` — 315 Zeilen

- **Status: DEAKTIVIERT** seit 2026-04-25 (Cron-Eintrag auskommentiert)
- Trigger war: Freitag 18:00 (nicht Samstag 02:00 wie v1)
- Sucht 36 h vor das billigste 2 h Tibber-Fenster, gewichtet mit Solcast-PV-Forecast
- Bei Window-Start: `fhem_cmd("set DI_WPSteuerung wwjetzt start")` → Perl-Wrapper → CMI
- Hard-Coded Tokens: Tibber, HA-Token, Telegram (in der Datei selbst — sollte nach Migration in env)
- Letzter Lauf: 2026-04-25 11:02:53 (DRY RUN exit, fand Sat 14:00 als guenstigstes)

### `/home/nibbles/scripts/legionellenschutz.py.DEACTIVATED-2026-04-25`

Alte v1, nur fix Samstag 02:00, kein Tibber-Fenster-Search. Umbenannt am 2026-04-25.

## Mac lokal

Im OpenClaw-Backup vom 2026-02-20 liegt eine **fruehere WP-State-Machine-Variante**:

- `~/Desktop/openclaw-backup-20260220-222422/workspace/scripts/wp-machine/wp_api.py`
- `~/Desktop/openclaw-backup-20260220-222422/workspace/scripts/wp-machine/wp_machine.py`
- `~/Desktop/openclaw-backup-20260220-222422/workspace/scripts/legionellenschutz.py`

Das ist Vorgaenger-Material — nicht laufend. Die jetzt produktive State-Machine ist `~/source/repos/wp-state-machine/`.

## HA OS — via HA-API geprueft (2026-05-06 abends)

SSH ist im HA OS nicht aktiviert ("Connection refused"). HA-API (Token `HOMEASSISTANT_KEY`) liefert:

- 1047 Entities total
- **1 WP/WW-relevant:** `input_number.hp_legionella_energy = 8.0` (Helper-Wert fuer Energie-Tracking)
- 42 Automations total, davon WP-relevant:
  - `automation.hp_reset_energy_values_to_read_only` — Helper-Reset
  - `automation.pow_update_tibber_prices_entity` — Tibber-Preise importieren
- **0 Scripts mit WW-Boost / Legionellenschutz**

**Kein aktiver WW-Boost-Trigger in HA.** Die Tibber-Preise werden importiert, aber der WW-Boost wird in FHEM (`DI_FreigabeWWHeizstab` und altes `legionellenschutz_v2.py`) entschieden, nicht in HA.

## NUCTHP2 / pihole — `192.168.178.5`

NUCTHP2 ist der gleiche Host wie `pihole` (192.168.178.5). Pi-hole/DNS + Docker mit RaspberryMatic, SearXNG, Portainer. Keine WP-Skripte gefunden.

## openclaw-vm

SSH-Verbindung Timeout. VM moeglicherweise heruntergefahren (Stufe-0-Hardening 2026-05-05). Keine Daten heute.

## Mac — LaunchAgents (`~/Library/LaunchAgents/`)

Geprueft: keine WP-Skript-LaunchAgent. `com.thp.cc.cmi-plausibility.plist` ist die State-Machine-Plausi (von uns), nicht ein zusaetzliches Skript. Docker-Container laufen aktuell keine.

## Zusammenfassung — wo der WW-Boost tatsaechlich getriggert wird

1. **FHEM `DI_FreigabeWWHeizstab`** (laeuft, Tibber+Senec-getrieben) → `set DI_WPSteuerung wwjetzt start` → `wpwwjetzt("start")` → CMI
2. **legionellenschutz_v2.py auf nucthp** (DEAKTIVIERT seit 2026-04-25, 2-h-Tibber-Fenster mit PV-Forecast)

Alles andere geht ueber dieselben FHEM-Funktionen (`DI_WPSteuerung`-Set-Befehle) oder gar nicht. **Damit ist der Migrationspfad klar:** alle WW-Boost-Pfade laufen aktuell durch `wpwwjetzt`. Wenn diese eine Perl-Funktion auf HTTP-POST an die State-Machine umgestellt wird, hat man alle Trigger auf einmal abgefangen.

## Migration auf die WP-State-Machine — Plan

### Phase 1.5 (parallel zu LIVE-Writes-Aktivierung)

1. **`legionellenschutz_v2.py` umstellen:** statt `fhem_cmd("set DI_WPSteuerung wwjetzt start")` → `requests.post("http://192.168.178.3:8765/functions/F9/start")`. Damit:
   - Audit-Log in Postgres
   - Telegram-Alarm aus der State-Machine (statt aus dem Skript selbst)
   - Whitelist-Schutz greift
   - DRY_RUN-Schutz greift
   - Skript wird kuerzer (weniger Auth-Logik)

2. **Cron auf nucthp wieder aktivieren** — gegen die State-Machine, mit DRY_RUN=false explizit getestet.

3. **`DI_FreigabeWWHeizstab` in fhem.cfg laesst sich vorerst** — ruft weiterhin den Perl-Wrapper. Spaeter (Phase 3) wird das DOIF auf HTTP-POST umgebaut.

### Phase 3 (HA-Migration)

- `99_myUtilsTACMIHTTP.pm` — die Perl-Wrapper-Funktionen werden umgeschrieben: statt direktem `wget` an `menupage.cgi` machen sie HTTP-POST an die State-Machine. Damit sind FHEM und State-Machine entkoppelt; FHEM bleibt UI/Logik, CMI-Zugriff geht nur ueber State-Machine.
- `DI_FreigabeWWHeizstab` bleibt in FHEM (Tibber+Senec-Logik), schreibt aber via State-Machine.
- HA bekommt eigene Automation gegen die State-Machine — z.B. fuer Solar-Ueberschuss-getriebenen WW-Boost.
