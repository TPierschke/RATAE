# State-Sub Logik (Dashboard "Aktueller Zustand")

Stand: 2026-05-09. Quelle: `web/static/live-bindings.js` `getStateSubText()`.

Die Hero-Box zeigt unter dem grossen Status-Wort eine zweite Zeile mit Aus-
Bedingung, Diff zum Aus-Punkt und ETA. Pro `wp_state` eigene Heuristik.

## HEIZUNG

UVR-Hysterese (User-Korrektur 2026-05-09):

- AUS, wenn `ruecklauf >= vorlauf_soll + 4K`
- EIN, wenn `ruecklauf <= vorlauf_soll` (4K Hub liegt OBERHALB des Soll;
  schont Verdichter, Puffer wird voll geladen)

Anzeige:

```
diff > 0.1: 'Verdichter aktiv · RL 28.1° · noch 5.1° bis Aus (33.2°) · ETA ~12 min'
diff <= 0:  'Verdichter aktiv · RL 33.2° · am Aus-Punkt (33.2°)'
fallback:   'Verdichter aktiv · Vorlauf 28.1°' (wenn vorlauf_soll fehlt)
```

## WARMWASSER

WP heizt bis `warmwasser >= ww_soll_normal`. Soll kommt aus `state.setpoints.
ww_soll_normal` (gecrawlt aus F:2 WW_ANF.1, typisch 49°C). Fallback im Frontend
50° wenn Crawl fehlt.

## LEGIONELLENSCHUTZ

Fester Ziel-Wert 70° (UVR F:9 WW_ANF.2). Wird im Backend mit
`ww_soll_legio=70.0` als Konstante in den setpoints persistiert, damit das
Frontend nicht hardcoden muss.

# ETA-Strategie

`live-bindings.js` enthält einen generischen 3-Modus-Tracker (heating / ww /
legio):

- Pro Modus: Sliding window (max 6min), eigener `localStorage`-Key
  (`wpsm.rate.<mode>`), eigener Default-Rate (Erfahrungswert).
- Beim Boot: Default-Rate aus `localStorage` (oder Konstante) → sofortige
  ETA-Schaetzung mit Suffix `(Schaetzung)`.
- Sobald >=15s Tracking eine positive Steigung zeigt: Live-Rate ueberschreibt
  Default UND wird in `localStorage` persistiert. Suffix dann ohne Klammer.
- Sticky: letzte gute ETA bleibt 60s sichtbar damit die Anzeige nicht zwischen
  Zahl und "wird ermittelt..." flackert.
- Tracker-Reset bei State-Wechsel: nur der zum aktiven State passende Tracker
  bleibt gefuellt, die anderen zwei werden geleert.

Default-Raten (deg/min, werden live korrigiert):

| Modus | Default | Quelle |
|---|---|---|
| heating | 0.115 | beobachteter Zyklus 2026-05-09 18:24-18:49, RL 27.0 → 29.3 / 20min |
| ww      | 0.5   | typischer WW-Heizverlauf (Annahme) |
| legio   | 0.4   | langsamer wegen hoeherer End-Temp (Annahme) |

# Setpoints-Persistenz (Backend)

`AppState.setpoints` wird via `automation/setpoints_logger.py` alle 5 min aus
der CMI-Funktionsuebersicht (`menupage.cgi?page=3E01581E`) gecrawlt.

- Atomares Schreiben in `~/.config/wp-state-machine/setpoints.json` (analog
  `theme.json`).
- Bei Boot: Datei wird im `AppState`-Constructor gelesen, sodass Werte
  sofort verfuegbar sind ohne 5-min Wartezeit.
- **Merge statt Replace:** ein partieller Crawl (CMI liefert je nach
  Operating-State nicht immer alle Felder) ueberschreibt nur die jeweils
  gelieferten Keys. Vorher-Werte bleiben erhalten.

Felder die der Logger liefert: `ww_soll_normal`, `ww_ist`, `normal_soll`,
`absenk_soll`, `raum_ist`, `vorlauf_soll`, `ww_soll_legio` (konstant 70.0).

# Frontend Setpoints Fallback

`live-bindings.js` `getBoundValue()` faellt auf `state.setpoints[key]` zurueck
wenn der Top-Level `state[key]` null ist. So funktioniert `data-bind="raum_ist"`
auch wenn Modbus den Wert nicht liefert (raum_ist wird nur via Crawl
gefuellt).

`KNOWN_KEYS` enthaelt entsprechend auch Setpoint-Keys, sonst lehnt
`getBoundValue` sie ab bevor der Fallback greift:

```
'raum_ist', 'normal_soll', 'absenk_soll',
'ww_soll_normal', 'ww_soll_legio', 'ww_ist'
```
