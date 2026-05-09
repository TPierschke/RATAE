# WP State Machine — TODOs

## Design-C Telemetry (Design-C Korrektur, 2026-05-09)

### Backend Tasks

- [ ] **Raum-IST als eigenes Sensor-Feld mappen**
  - S5 oder Modbus-Adresse prüfen (siehe CMI-MODBUS-CONFIG-IST.md)
  - Backend: neues Feld `raum1_ist` in sensoren-Modell
  - Frontend: separate Kachel für "Raum-IST" + Display in Telemetry-Grid
  - Status: Abhängig von Modbus-Konfiguration

- [ ] **WW-Soll als eigenes Sensor-Feld plus computed-property**
  - Backend: neues Feld `ww_soll` in sensoren-Modell
  - Logik: F:2 oder F:9 abfangen, 50° (Normal) oder 70° (Legionellenschutz)
  - live-bindings.js aktuell: harte Werte (50/70), soll dann Backend-Wert verwenden
  - Status: Aktuell Frontend-only computed, Backend-Integration pending

## Referenzen

- mockup-c.html: Raumtemp-Kachel → Raum-Soll (traum1 = Raum-Soll laut models.py)
- live-bindings.js: applyWwSollBindings() — WW-Soll berechnung nach wp_state
- version.json: FE 0.2.2 (2026-05-09)
