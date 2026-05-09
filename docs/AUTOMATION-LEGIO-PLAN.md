# Legionellenschutz + Solar-Boost — Plan

## Prinzip

**Solar-getrieben, nicht Tibber-getrieben.** Tibber-Fenster nur als Fallback wenn bis Freitag 20:00 keine 70 °C erreicht wurden.

## Wochenzyklus (Mi–Di)

| Tag | 70 °C-Boost erlaubt? | 60 °C-Boost erlaubt? |
|---|---|---|
| Mi | ja | nein |
| Do | ja, wenn Mi nicht erreicht | nein |
| Fr | ja, wenn Mi-Do nicht erreicht | nein |
| Fr 20:00 | Tibber-Fallback wenn `legio_done=False` | — |
| Sa, So, Mo, Di | nein | ja, wenn Sonne |

`legio_done` Reset beim Uebergang Di 23:59 → Mi 00:00.

## Boost-Auswahl (70 oder 60 °C)

```
if not legio_done and weekday in (Mi, Do, Fr) and solar_ok:
    target = 70  # Legio-Versuch via F:9, CMI stoppt bei 70
elif legio_done and solar_ok:
    target = 60  # Reiner Sonne-nutzen-Boost, eigener Watcher stoppt bei 60
```

## Solar-Bedingungen (`solar_ok`)

Solcast-Forecast aktiv nutzen (Sonne kommt typisch ab 13–14 Uhr):
```
PV_jetzt >= 3 kW
Senec-Akku >= 80 %
Tibber-Preis < 8 ct/kWh
Aussentemp > 10 °C
Solcast-Forecast naechste 2 h: avg >= 3 kW (Plan-Sicherheit)
```

## Solar-Stop-Logik (bei Solar-weg)

| Aktueller Boost | warmwasser | Aktion |
|---|---|---|
| 70 °C-Modus | >= 65 °C | weiterlaufen lassen bis CMI bei 70 stoppt |
| 70 °C-Modus | < 65 °C | F:9 STOP, `legio_done` bleibt False |
| 60 °C-Modus | >= 60 °C | F:9 STOP, fertig |
| 60 °C-Modus | < 60 °C | F:9 STOP |

Cooldown 30 min nach jedem Stop.

## Tibber-Fallback (Freitag 20:00)

Trigger nur wenn `legio_done=False`:
1. Tibber-API: Preise naechste 48 h
2. Billigstes 2-h-Fenster waehlen, optional mit Solcast-PV als Bonus-Faktor
3. Asyncio-Schedule auf Window-Start → F:9 START
4. CMI stoppt bei 70 °C → `legio_done=True`

## Edge-Cases

| Fall | Verhalten |
|---|---|
| Mi 70 °C erreicht | `legio_done=True`, Rest der Woche nur 60 °C-Boosts |
| Mi-Do-Fr nichts erreicht | Tibber-Fallback Fr 20:00 |
| Stromausfall waehrend Boost | bei Wiederkehr `legio_done` aus DB pruefen, ggf. erneut |
| WW > 70 °C ohne Boost (selten) | nur Merker setzen, kein Boost |
| Tibber-API down | Fallback fix Sa 02:00 + Telegram-Alarm |

## State (persistent in Postgres)

```
legio_state(week_id INT, legio_done BOOL, last_boost_at TIMESTAMP, source TEXT)
```

## Phase-2-Bauplan

1. Tibber-API-Modul (price feed)
2. Solcast-Reader (HA-Sensor)
3. `automation/legio_scheduler.py` mit der obigen Logik
4. Postgres-Tabelle `legio_state`
5. Tests mit `freezegun` fuer Tag/Zeit-Logik
6. n8n-Legio-Workflow ist inaktiv — sauber loeschen wenn State-Machine produktiv
