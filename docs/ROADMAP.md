# WP State Machine — Roadmap

Stand: 2026-05-06. Phase 1 zu ~70 % durch.

## Phase 1 abschliessen (vor "v0.2")

### 1. LIVE-Writes ans CMI (Funktionsschaltung)

Aktueller Stand: die REST-Endpunkte sind im `DRY_RUN`-Modus implementiert, schreiben aber noch nicht ans CMI. Whitelist und Audit-Log existieren bereits.

**Was zu tun ist:**

- **Schreib-Pfad evaluieren.** Zwei Wege moeglich:
  1. **Modbus-Master-Rolle:** Mac wird zusaetzlich Modbus-Master und schreibt ans CMI (CMI muss als Slave-Input definiert werden — bisher ist nur die Output-Seite konfiguriert).
  2. **HTTP-API ans CMI:** `INCLUDE/api.cgi` mit `?jsonnode=62&jsonparam=` und `changeF=...` schreibt direkt UVR-Funktions-Parameter. Das ist der dokumentierte TA-Weg.
  Empfehlung: **HTTP-API**, weil bidirektional sauberer und das Modbus-Setup nicht doppelt belastet wird.

- **Endpunkte aktivieren:**
  - `POST /functions/F1/betriebsart` — Betriebsart F:1 (1..7)
  - `POST /functions/F1/normalsoll` — Raum-Soll (Param `RA.NORMAL`)
  - `POST /functions/F1/absenksoll` — Raum-Soll-Absenk (Param `RA.ABGES`)
  - `POST /functions/F9/start` — Legionellenschutz STARTEN=1 (Param)
  - `POST /functions/F9/stop` — Stop-Override (falls noetig)

- **Safety-Whitelist** auf jede Adresse pruefen (existiert bereits in `safety.py` — Whitelist-Eintraege erweitern).

- **Audit-Log in Postgres** je Schreibvorgang (Adresse, Wert, dry_run, cmi_response, success). Tabelle existiert.

- **UI:** der "Setzen"-Button und "Legionellenschutz starten"-Button muessen in LIVE-Mode echte CMI-Calls ausloesen. DRY_RUN-Banner laesst sich per ENV `DRY_RUN=false` deaktivieren.

### 2. Postgres-Telemetrie aktivieren

- Postgres-Server steht auf `192.168.178.10:5432` — aktuell nicht erreichbar (Firewall/nicht gestartet).
- 2nd-Postgres-Instanz auf .10 einrichten (User-Aktion).
- Schema ist bereits vorbereitet (`storage/schema.sql`).
- Telemetrie-Insert pro Modbus-Update + Heartbeat alle 60 s laeuft schon im Code.

### 3. Plausibility-Check-Skript umbauen

Das alte WP-Plausi-Skript laeuft als LaunchAgent (`com.thp.cc.cmi-plausibility`) und vergleicht aktuell direkt CMI-Web vs Modbus-Slave. Mit neuer State-Machine als Single-Source-Of-Truth:

- Neuer Plausi-Modus: vergleicht **State-Machine `/state`** (Modbus-Quelle) gegen **CMI-Web-UI**. Abweichungen > 0.5 K oder Coil-Mismatch → Telegram-Alarm.
- Tool-Pfad: `~/source/repos/wp-state-machine/tools/plausibility_check.py` umschreiben.
- Reduziert Last auf CMI: nur die State-Machine pollt.

### 4. Web-Scraper-Race als Fallback verifizieren

- Implementierung steht: Scraper springt nur an wenn Modbus > 300 s stale.
- Test fehlt: Modbus-Outputs am CMI temporaer deaktivieren, schauen ob Scraper nach 5 min uebernimmt.

### 5. Deploy auf `.10`

- Repo per `git push` zu .10 oder per `rsync`.
- LaunchAgent (linux: systemd unit) aufsetzen — `Restart=always`.
- Port 8765 + 5020 freigeben.
- Postgres-Verbindung `localhost:5432` statt `192.168.178.10:5432`.
- DRY_RUN bleibt `true` bis nach Live-Test.

### 6. Loose Enden

- **DRIFT-Register**: heute offene Punkte abarbeiten (Service-Worker-Restwerte, leichte Drift Heissgas-Wert).
- **Sensor-Offset E2/E3**: -4 K Korrektur an UVR — naechste Heizperiode (kein Code).
- **Heissgas/Fluessigkeit-Drift im Modbus**: 1-2 K weicht von CMI-UI ab. Vermutlich CMI-Push-Latenz, nicht Bug. Beobachten.

## Phase 2 (nach Phase-1-Stabilitaet, ~1 Woche)

### WW-Bereitungs-Erkennung im State-Machine-Status

`Sensoren.derive_state()` erweitern: wenn `ventil_ww=True` UND `verdichter=True`,
dann ist die Anlage im aktiven WW-Bereitungs-Lauf. Eigener WP-State `WARMWASSER`
(existiert schon als Enum-Wert), Anzeige in der Haupt-State-Card mit eigenem Icon
(💧). Plus: die WW-Anstiegs-Rate in der Telemetrie ableitbar machen
(WW-Temperatur ueber Zeit waehrend `WARMWASSER`-State).

### SPS-Schema-View

- Toggle "Liste / Schema" oben in der UI (zusaetzlich zu den Tabs, oder dritter Tab).
- Bilitas-Hebe-Schaltbild als Hintergrund-SVG.
- Sensor-Werte als Overlay (positionierte `<div>` mit absoluten Koordinaten).
- Aktive Aktoren in Gruen, inaktiv Rot (SPS-Konvention wie schon im Dashboard).

### Heizkurven-Auswertung

- Postgres-Telemetrie ueber 1 Heizperiode sammeln.
- Plot Aussentemp vs Vorlauf, Auswertung Steilheit/Niveau.
- Optimierungs-Vorschlag aus Daten ableiten.

## Phase 3 (Hausautomation-Integration)

### HA → FHEM Migration

- HA als Koordinator (entschieden 2026-05-04).
- FHEM bleibt als Hardware-Schaltzentrale.
- WP-State-Machine als zentraler Adapter zwischen HA und CMI.
- MQTT-Bridge fuer Sensoren-Topic.

## Was nicht in Phase 1 gehoert

- CoE-Reanimation (CoE bleibt tot — Modbus uebernimmt komplett).
- Multi-WP-Support.
- Mobile-App (PWA reicht).

## Naechster Schritt

Vorschlag: **LIVE-Writes** zuerst, weil das die einzig fehlende Kern-Funktionalitaet ist. Danach Postgres + Plausi, dann Deploy.

User entscheidet.
