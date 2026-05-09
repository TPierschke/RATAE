# PV-Surplus-Verbraucher-Steuerung — Plan

Stand: 2026-05-06. Erweitert `AUTOMATION-LEGIO-PLAN.md` um Multi-Senken-Orchestrierung. Phase 2/3.

## Prinzip

Akku zuerst (Senec-Eigenlogik), dann gestaffelte Software-Senken via WP-State-Machine. Hardware-Schaltung bleibt CMI (F:9) und FHEM (Pool, Bedampfer). Die State-Machine orchestriert nur — sie schaltet nicht direkt.

## 1. Priorisierungs-Modell

Senken in absteigender Prioritaet, Aktivierung nur wenn jeweilige Schwelle ueberschritten:

| Rang | Senke | Aktivierung (alle UND) | Stop |
|---|---|---|---|
| 0 | Senec-Akku | (Senec-Eigenautomatik) | SoC=100 % |
| 1 | WW-Boost F:9 60 °C | SoC>=80, PV_jetzt>=3 kW, Solcast_2h_avg>=3 kW, Tibber<8 ct, Aussen>10 °C | WW>=60 °C oder Solar weg, Cooldown 30 min |
| 1a | WW-Boost F:9 70 °C (Legio Mi-Fr) | wie 1, plus `legio_done=False` | CMI stoppt automatisch bei 70 |
| 2 | Pool-Heizung | SoC>=85, PV_jetzt>=4 kW, Solcast_2h_avg>=4 kW, Saison Mai-Sep, Pool-Soll<Ist nicht erreicht | SoC<70 oder PV<2 kW |
| 3 | Bedampfer | SoC>=90, PV_jetzt>=2 kW, Tageszeit 11-17 Uhr, Saison Apr-Okt | SoC<80 oder PV<1 kW |

Slack 5 % SoC zwischen Start und Stop verhindert Flackern. Eine Senke pro Tick wird bewertet, beginnend bei Rang 1.

## 2. Wochen- und Tageslogik

- **Legio-Quote:** 1×/Woche 70 °C (Mi-Fr-Solar-Fenster, Fr 20:00 Tibber-Fallback). Sonst 60 °C-Boost als reiner Eigenverbrauch.
- **Pool-Saison:** 1. Mai bis 30. Sep, plus Aussen-Tagesmittel >15 °C als Hard-Gate.
- **Bedampfer:** Apr-Okt, nur 11-17 Uhr (Mittagspeak), Auto-Off via existierendes `DI.Bedampfer.AutoOff`.
- **Tick-Intervall:** 60 s evaluation, 30 s F:9-Watcher waehrend aktivem Boost.

## 3. Architektur in der State-Machine

Neues Verzeichnis `src/wp_state_machine/automation/`:

- `surplus_orchestrator.py` — asyncio-Task `evaluate_surplus_loop()`, 60 s-Tick, ruft Senken-Module
- `sinks/ww_boost.py` — F:9-Wrapper (nutzt vorhandene `/functions/F9/start|stop`)
- `sinks/pool_heater.py` — FHEM-HTTP `set climate.poolheater` ueber `fhem` HTTP-API
- `sinks/bedampfer.py` — FHEM `set DI.Bedampfer.AutoOff` Anstoss
- `legio_scheduler.py` (existierend laut Roadmap, hier konsumiert)
- `ha_client.py` — gepoolter Async-Client gegen HA-API
- `tibber_client.py` — bestehend/neu, GraphQL-Cache 15 min
- `state.py` — Postgres-Persistenz: `surplus_state(sink TEXT, last_start TIMESTAMP, last_stop TIMESTAMP, cooldown_until TIMESTAMP, dry_run BOOL, reason TEXT)`

Schreibvorgaenge ans CMI laufen weiter ueber `cmi_writer.py` und Whitelist in `safety.py`. Pool/Bedampfer gehen ueber FHEM, **nicht** via CMI — kein Whitelist-Eintrag noetig, aber eigene Permission-Schicht: `automation.allow_fhem_write` Gate plus DRY_RUN.

## 4. HA-Anbindung

Polling alle 30 s, Endpunkt `GET http://192.168.178.19:8123/api/states/<entity>` mit Bearer-Token aus `~/.credentials/tokens.env`:

| Entity | Zweck |
|---|---|
| `sensor.senec_local_solar_generated_power` | PV_jetzt (W) |
| `sensor.senec_local_battery_charge_percent` | SoC (%) |
| `sensor.solcast_pv_forecast_power_now` | Forecast jetzt |
| `sensor.solcast_pv_forecast_forecast_today` | Tagesplan |
| `sensor.tibber_*` | Strompreis ct/kWh |
| `weather.home` (oder DWD-FHEM) | Aussentemp |

Forecast-2h-Avg per `forecasts`-Attribut (Solcast-Integration liefert stuendlich) — Mittel ueber jetzt+1h+2h.

## 5. Step-by-Step Bauplan

1. **Phase 2.1:** `ha_client.py` + `tibber_client.py` mit Cache und Read-Only-Tests.
2. **Phase 2.2:** `state.py` Schema + Migration.
3. **Phase 2.3:** `legio_scheduler.py` (Solar-Boost 60/70 °C, Cooldown) — DRY_RUN-only.
4. **Phase 2.4:** `surplus_orchestrator.py` mit Senke `ww_boost` als einzigem Verbraucher.
5. **Phase 2.5:** Live-Aktivierung WW-Boost (User-Freigabe, dann `DRY_RUN=false`).
6. **Phase 3.1:** Senke `pool_heater` (FHEM-Adapter), bleibt DRY_RUN bis User abnimmt.
7. **Phase 3.2:** Senke `bedampfer`.
8. **Phase 3.3:** UI-Card `/automation` mit Live-State, Override-Button, Force-DRY-RUN-Toggle.

Jede Phase landet in eigenem PR mit Tests und Telegram-Alarm-Pfad.

## 6. Test-Strategie

- **`pytest` + `freezegun`** fuer Wochen/Tageslogik (Mi-Fr-Legio, Saison-Gates).
- **`respx`** mockt HA/Tibber/FHEM/CMI-HTTP — keine echten Calls.
- **Szenario-Tests:** Wolkenfeld (PV oszilliert 1-5 kW), Akku-leer-Sonne-weg, Pool aktiv blockt WW.
- **DRY_RUN-Default** in `config.toml`, plus `automation.live=false`-Flag pro Senke separat.
- **Time-Travel-Integrationstest** auf staging-DB: 24-h-Lauf in 60 s mit gemockten Sensorkurven.
- **Smoke-Test live:** mit `DRY_RUN=true` 48 h gegen echte HA-Daten, Audit-Log auswerten — keine Schaltvorgaenge erwartet.

## 7. Risiken / Tradeoffs

- **Wolkenfeld-Flackern:** rolling-avg-Gate (Solcast 2h) plus 30-min-Cooldown pro Senke; Hysterese 5 % SoC.
- **Senke-Konflikt:** Pool-Heizung darf WW-Boost nicht verdraengen. Loesung: strikte Rang-Reihenfolge, hoehere Senken bekommen erst „Recht auf PV", niedrigere nur wenn ihre Schwelle ueber dem Restbedarf liegt.
- **Akku fast leer + Sonne weg:** alle Senken stoppen sofort; Senec-Eigenautomatik priorisiert Hauslast.
- **WW-Soll-Drift:** absolutes Verbot WW-Soll automatisch zu schreiben — `safety.py` bleibt Whitelist-Eintrag, aber kein Automation-Modul ruft `3EB0023118`. Test prueft das per Reflection.
- **Heizstab-Vorgriff:** F:9 eskaliert intern, Cooldown 30 min nach STOP, niemals direkter `3E8015*`-Write (FORBIDDEN_EXACT bleibt).
- **FHEM-Ausfall:** Pool/Bedampfer-Senken degradieren still, Telegram-Alarm, kein Crash.
- **Tibber-Negativpreis:** Sonderfall — alle Senken erlauben, plus Hint im Audit-Log; aber kein automatisches WW-Soll-Anheben.

## State-Diagramm (Kurz)

```
IDLE -> EVAL (60s) -> [Senken-Check] -> START_SINK_X -> RUNNING -> STOP_TRIGGER -> COOLDOWN -> IDLE
```

Persistent: `surplus_state` pro Senke. Reset bei Service-Restart aus DB.

## Critical Files for Implementation

- `src/wp_state_machine/safety.py`
- `src/wp_state_machine/ingest/cmi_writer.py`
- `src/wp_state_machine/api/rest.py`
- `src/wp_state_machine/storage/postgres.py`
- `docs/AUTOMATION-LEGIO-PLAN.md`
