# CMI-Write-API — Schreibvorgaenge ans CMI

Quelle: `99_myUtilsTACMIHTTP.pm` aus dem FHEM-Server der Anlage Pierschke.
Bewaehrte Implementierung. Schreib-Schicht uebertragen 1:1 nach Python.

## URL-Schema

```
GET http://<USER>:<PASS>@<CMI>/menupage.cgi?page=<HEX>&changeadr=<ADDR>&changeto=<WERT>
```

Auth in unserer Implementierung via HTTP-Basic-Auth-Header (nicht in URL),
Credentials kommen aus `~/.credentials/tokens.env` (`CMI_USER`/`CMI_PASS`).

Aufruf macht das CMI selbst die Plausibilitaetspruefung, schreibt den
Funktions-Parameter und triggert den UVR-Funktions-Logik-Lauf.
Kein direkter Aktor-Zugriff — geht durch die UVR1611-Funktions-Schicht.

## Adressen-Tabelle (alle erlaubt mit Whitelist)

### F:1 Heizkreis (page=`3E01581E`)

| Funktion | changeadr | Werte | Zweck |
|---|---|---|---|
| Betriebsart | `3E9001301C` | 1..7 | 1=Standby, 2=Zeit/Auto, 3=Normal, 4=Abgesenkt, 5=Party, 6=Urlaub, 7=Feiertag |
| Normalsoll | `3EB001300C` | 10.0..30.0 °C | Raum-Soll Normal |
| Absenksoll | `3EB001300D` | 5.0..25.0 °C | Raum-Soll Abgesenkt |
| WW-Soll | `3EB0023118` | 30.0..70.0 °C | WW-Soll-Temperatur |

### F:9 WW-Bereitung WW_ANF.2 (page=`3E09580E`)

| Funktion | changeadr | Werte | Zweck |
|---|---|---|---|
| WW-Boost START | `3E80093125` | 1 | Legionellenschutz / WW-Boost starten (Soll 70 °C) |
| WW-Boost STOP | `3E80093126` | 1 | WW-Boost manuell stoppen |

## Verbotene Adressen — auf KEINEN Fall schreiben

### `3E91*` — direkte Aktor-Ausgaenge A1..A10

Diese Adressen schalten die Aktoren **direkt** und **umgehen die UVR-Logik**.
Sicherheits-Risiko (Verdichter-Schutz, Pumpen-Mindestlauf etc.).

- `3E910120A1` FBH-Pumpe A1 — VERBOTEN, geht ueber Funktion
- `3E910A20A1` Zirku-Pumpe A10 — VERBOTEN, geht ueber Funktion

### `3E80153125` / `3E80153126` — Heizstab FB direkt

Heizstab darf nur ueber Funktion F:9 (mit Eskalation) eingeschaltet werden.
Direkter Schaltbefehl umgeht den Verdichter-Vorrang (Energieverschwendung).

## Sicherheits-Konzept

1. **Whitelist:** nur die oberen Adressen werden ueberhaupt akzeptiert (`safety.py`).
2. **Wertebereich:** pro Adresse min/max gepruefte Range.
3. **DRY_RUN-Default:** Schreibvorgaenge werden nur geloggt, nicht ausgefuehrt — bis der User explizit `DRY_RUN=false` setzt.
4. **Audit-Log:** jeder Versuch (erlaubt oder geblockt) wird in Postgres `function_audit` geloggt.
5. **Telegram-Alarm** bei jedem LIVE-Write.

## Testreihenfolge (vor LIVE-Schaltung)

1. DRY_RUN: Endpunkt aufrufen, Audit-Log + Log-Output pruefen.
2. LIVE-Test 1: gleiche Betriebsart wie aktuell setzen — keine Wertaenderung, aber Call durchgefuehrt.
3. Im CMI-UI verifizieren dass der Wert noch stimmt + Audit-Log zeigt success=true.
4. Erst danach LIVE-Wertaenderung.
