#!/usr/bin/env python3
"""
tools/plausibility_check.py — Plausibility-Check: Modbus vs CMI Web-UI.

Zieht einmal alle Vergleichs-Werte aus:
  - http://localhost:8765/state  (WP State Machine Modbus-State)
  - http://192.168.178.45/menupage.cgi?page=3E005804  (Messwerte)
  - http://192.168.178.45/menupage.cgi?page=3E005806  (Ausgaenge)

Vergleicht Analog-Werte (Schwelle: 0.5 K) und Digital-States (exakt).
Bei Abweichung: Telegram-Push + Logzeile.
Bei OK: nur Logzeile, kein Telegram.

Rate-Limit: Genau 1 CMI-Anfrage (kombiniert Messwerte-Seite + Ausgabe-Seite = 2 Requests,
aber beide in einem Lauf) — kein Loop.

Cooldown fuer "State-Machine nicht erreichbar": 1x pro Tag via /tmp/.plausibility_lastalert

Exit-Code: 0 = OK oder nur Warnungen gesendet; 1 = fatal (State-Machine down, CMI down).

Praefix fuer Telegram: [ThoPAS|plausibility]
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

STATE_URL = "http://localhost:8765/state"
CMI_BASE = "http://192.168.178.45"
CMI_MESSWERTE_PAGE = "3E005804"
CMI_AUSGAENGE_PAGE = "3E005806"
CMI_USER = "admin"
CMI_PASS = "admin"

TELEGRAM_ENV = Path.home() / ".claude" / "channels" / "telegram" / ".env"
TELEGRAM_CHAT_ID = "5955462676"

LOG_DIR = Path.home() / "Library" / "Logs" / "cc" / "plausibility"
LOG_FILE = LOG_DIR / "plausibility.log"

COOLDOWN_FILE = Path("/tmp/.plausibility_lastalert")

ANALOG_THRESHOLD = 0.5   # Kelvin
TELEGRAM_PREFIX = "[ThoPAS|plausibility]"

HTTP_TIMEOUT = 10         # Sekunden

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("plausibility")


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------


def _load_telegram_token() -> Optional[str]:
    """Liest TELEGRAM_BOT_TOKEN aus ~/.claude/channels/telegram/.env."""
    if not TELEGRAM_ENV.exists():
        log.warning("Telegram .env nicht gefunden: %s", TELEGRAM_ENV)
        return None
    for line in TELEGRAM_ENV.read_text().splitlines():
        line = line.strip()
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            return line.split("=", 1)[1].strip()
    log.warning("TELEGRAM_BOT_TOKEN nicht in .env gefunden")
    return None


def send_telegram(message: str) -> bool:
    """
    Sendet Telegram-Nachricht via Bot-API (sync HTTP, kein python-telegram-bot).
    Gibt True bei Erfolg zurueck.
    """
    token = _load_telegram_token()
    if not token:
        log.error("Kein Telegram-Token — kann nicht senden")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": message}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            body = resp.read()
            result = json.loads(body)
            if result.get("ok"):
                log.info("Telegram gesendet: %s", message[:80])
                return True
            log.error("Telegram API Fehler: %s", result)
            return False
    except Exception as exc:
        log.error("Telegram send Fehler: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Cooldown fuer State-Machine-Down-Alarm
# ---------------------------------------------------------------------------


def _cooldown_active() -> bool:
    """
    Prueft ob heute bereits ein Down-Alarm gesendet wurde.
    Datei /tmp/.plausibility_lastalert enthaelt das letzte Alarm-Datum (YYYY-MM-DD).
    """
    if not COOLDOWN_FILE.exists():
        return False
    try:
        last = COOLDOWN_FILE.read_text().strip()
        return last == str(date.today())
    except Exception:
        return False


def _set_cooldown() -> None:
    """Setzt Cooldown auf heute."""
    try:
        COOLDOWN_FILE.write_text(str(date.today()))
    except Exception as exc:
        log.warning("Cooldown-File schreiben fehlgeschlagen: %s", exc)


# ---------------------------------------------------------------------------
# Modbus-State holen (localhost:8765)
# ---------------------------------------------------------------------------


def fetch_modbus_state() -> Optional[dict]:
    """
    GET http://localhost:8765/state → JSON.
    Gibt None bei Fehler oder Timeout.
    """
    req = urllib.request.Request(STATE_URL, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            body = resp.read()
            data = json.loads(body)
            return data
    except Exception as exc:
        log.error("State-Machine nicht erreichbar (%s): %s", STATE_URL, exc)
        return None


def extract_modbus_values(state_json: dict) -> dict:
    """
    Extrahiert Vergleichs-Felder aus /state JSON.

    Analog: aussen, vorlauf, ruecklauf, warmwasser, heissgas
    Digital: verdichter, heizstab_ww, alarm
    """
    s = state_json.get("sensoren", {})
    return {
        # Analog (float or None)
        "aussen": s.get("aussen"),
        "vorlauf": s.get("vorlauf"),
        "ruecklauf": s.get("ruecklauf"),
        "warmwasser": s.get("warmwasser"),
        "heissgas": s.get("heissgas"),
        # Digital (bool or None)
        "verdichter": s.get("verdichter"),
        "heizstab_ww": s.get("heizstab_ww"),
        "alarm": s.get("alarm"),
    }


# ---------------------------------------------------------------------------
# CMI-Werte holen (2 Requests: Messwerte + Ausgaenge)
# ---------------------------------------------------------------------------


def _cmi_http(page: str) -> Optional[str]:
    """
    Ladet CMI-Seite via Basic-Auth HTTP. Gibt HTML als String oder None.
    """
    url = f"{CMI_BASE}/menupage.cgi?page={page}"
    import base64
    credentials = base64.b64encode(f"{CMI_USER}:{CMI_PASS}".encode()).decode()
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Basic {credentials}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            if resp.status == 429:
                log.warning("CMI Rate-Limit (HTTP 429) auf Seite %s", page)
                return None
            if resp.status >= 400:
                log.warning("CMI HTTP %d auf Seite %s", resp.status, page)
                return None
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log.error("CMI-Anfrage fehlgeschlagen (Seite %s): %s", page, exc)
        return None


# ---------------------------------------------------------------------------
# CMI Messwerte-Seite parsen (3E005804)
# ---------------------------------------------------------------------------

_TEMP_RE = re.compile(r"([-+]?\d+)[,.](\d+)\s*\xb0C")
_TEMP_INT_RE = re.compile(r"([-+]?\d+)\s*\xb0C")


def _parse_temp_from_text(text: str) -> Optional[float]:
    """Parst Temperatur aus CMI-HTML-Text (mit °C, Komma oder Punkt)."""
    m = _TEMP_RE.search(text)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    m = _TEMP_INT_RE.search(text)
    if m:
        return float(m.group(1))
    return None


def _is_ein(text: str) -> bool:
    t = text.upper()
    return "EIN" in t or " ON" in t


def parse_messwerte(html: str) -> dict:
    """
    Parst Messwerte-Seite (3E005804).

    Zeilen-Schema (aus Live-Beobachtung):
      1: Aussen(S1)   Vorlauf/Puffer(S2)
      3: Ruecklauf(S3)  WW-Speicher(S4)
      7: Heissgas(S7)   Fluessigkeitsleitung(S8)
      9: Saugleitung(S9)  Phasenwaechter(S10, EIN/AUS)

    Werte kommen als "10,5 °C" (UTF-8 Grad-Zeichen U+00B0).
    BeautifulSoup dekodiert HTML-Entities (&nbsp; → \xa0) automatisch.
    """
    result: dict = {}

    # BS4 dekodiert Entities inkl. &nbsp; → \xa0
    soup = BeautifulSoup(html, "html.parser")
    raw_text = soup.get_text(separator="\n")

    # Normiere \xa0 → Leerzeichen, Null-Bytes entfernen
    text = raw_text.replace("\xa0", " ").replace("\x00", "")

    # Jede Zeile die mit "N:" beginnt ist eine Daten-Zeile
    row_re = re.compile(r"^\s*(\d{1,2}):\s*(.+)$")

    for line in text.splitlines():
        m = row_re.match(line)
        if not m:
            continue
        row_num = int(m.group(1))
        row_text = m.group(2).strip()

        # Splitte in zwei Spalten (durch mehrfache Leerzeichen getrennt)
        parts = re.split(r"\s{2,}", row_text)
        parts = [p.strip() for p in parts if p.strip()]

        col1 = parts[0] if len(parts) > 0 else ""
        col2 = parts[1] if len(parts) > 1 else ""

        if row_num == 1:
            result["aussen"] = _parse_temp_from_text(col1)
            result["vorlauf"] = _parse_temp_from_text(col2)
        elif row_num == 3:
            result["ruecklauf"] = _parse_temp_from_text(col1)
            result["warmwasser"] = _parse_temp_from_text(col2)
        elif row_num == 7:
            result["heissgas"] = _parse_temp_from_text(col1)
            # col2 = Fluessigkeitsleitung S8 (kein Vergleich noetig)
        elif row_num == 9:
            # col2 = Phasenwaechter S10 (EIN/AUS)
            result["phasenwaechter"] = _is_ein(col2) if col2 else None

    return result


def parse_ausgaenge(html: str) -> dict:
    """
    Parst Ausgaenge-Seite (3E005806).

    Extrahiert Verdichter (A3), Alarm ext. (A5), Heizstab WW (A9).
    Pattern: "N: <Name>" gefolgt von Zeile mit AUTO/EIN oder AUTO/AUS.
    BeautifulSoup dekodiert HTML-Entities (&nbsp; → \xa0) automatisch.
    """
    result: dict = {}

    # BS4 dekodiert Entities inkl. &nbsp; → \xa0
    soup = BeautifulSoup(html, "html.parser")
    raw_text = soup.get_text(separator="\n")
    text = raw_text.replace("\xa0", " ").replace("\x00", "")

    # Finde Output-Nummer + Status-Zeile
    # Pattern: Nr: Name → naechste Zeile mit AUTO/EIN oder EIN oder AUS
    output_map = {
        3: "verdichter",
        5: "alarm",
        9: "heizstab_ww",
    }

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    i = 0
    while i < len(lines):
        m = re.match(r"^(\d{1,2})\s*:\s*(.+)$", lines[i])
        if m:
            num = int(m.group(1))
            if num in output_map:
                field = output_map[num]
                # Suche in den naechsten paar Zeilen nach Status
                for j in range(i + 1, min(i + 4, len(lines))):
                    sl = lines[j]
                    if re.search(r"AUTO|EIN|AUS|ON|OFF", sl, re.I):
                        result[field] = _is_ein(sl)
                        break
        i += 1

    return result


# ---------------------------------------------------------------------------
# Vergleich + Warnungen
# ---------------------------------------------------------------------------


def compare_values(
    modbus: dict,
    cmi_messwerte: dict,
    cmi_ausgaenge: dict,
) -> list[str]:
    """
    Vergleicht Modbus-Werte gegen CMI-Werte.

    Analog: Abweichung > ANALOG_THRESHOLD → Warnung
    Digital: Unterschied (bool) → Warnung

    Gibt Liste von Warn-Strings zurueck (leer = alles OK).
    """
    warnings: list[str] = []

    # Analog-Werte
    analog_fields = {
        "aussen": (modbus.get("aussen"), cmi_messwerte.get("aussen")),
        "vorlauf": (modbus.get("vorlauf"), cmi_messwerte.get("vorlauf")),
        "ruecklauf": (modbus.get("ruecklauf"), cmi_messwerte.get("ruecklauf")),
        "warmwasser": (modbus.get("warmwasser"), cmi_messwerte.get("warmwasser")),
        "heissgas": (modbus.get("heissgas"), cmi_messwerte.get("heissgas")),
    }

    for field, (mb_val, cmi_val) in analog_fields.items():
        if mb_val is None or cmi_val is None:
            # Kein Vergleich moeglich wenn einer None ist
            log.debug("Feld %s: mb=%s cmi=%s — kein Vergleich (None)", field, mb_val, cmi_val)
            continue
        diff = abs(mb_val - cmi_val)
        if diff > ANALOG_THRESHOLD:
            msg = (
                f"WARNUNG: {field} modbus={mb_val:.1f} cmi={cmi_val:.1f} diff={diff:.1f}K"
            )
            warnings.append(msg)
            log.warning(msg)
        else:
            log.debug("OK: %s mb=%.1f cmi=%.1f diff=%.2f", field, mb_val, cmi_val, diff)

    # Digital-Werte
    digital_fields = {
        "verdichter": (modbus.get("verdichter"), cmi_ausgaenge.get("verdichter")),
        "heizstab_ww": (modbus.get("heizstab_ww"), cmi_ausgaenge.get("heizstab_ww")),
        "alarm": (modbus.get("alarm"), cmi_ausgaenge.get("alarm")),
    }

    for field, (mb_val, cmi_val) in digital_fields.items():
        if mb_val is None or cmi_val is None:
            log.debug("Feld %s: mb=%s cmi=%s — kein Vergleich (None)", field, mb_val, cmi_val)
            continue
        if mb_val != cmi_val:
            msg = f"WARNUNG: {field} modbus={mb_val} cmi={cmi_val} (Digital-Mismatch)"
            warnings.append(msg)
            log.warning(msg)
        else:
            log.debug("OK: %s mb=%s cmi=%s", field, mb_val, cmi_val)

    return warnings


# ---------------------------------------------------------------------------
# Hauptfunktion
# ---------------------------------------------------------------------------


def main() -> int:
    """
    Fuehrt einen Plausibility-Check-Lauf durch.

    Returns:
        0 = OK (auch wenn Warnungen gesendet)
        1 = Fatal (State-Machine oder CMI nicht erreichbar)
    """
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    log.info("=== Plausibility-Check Start %s ===", ts)

    # 1. Modbus-State holen
    state_json = fetch_modbus_state()
    if state_json is None:
        if not _cooldown_active():
            msg = f"{TELEGRAM_PREFIX} FEHLER: WP State Machine nicht erreichbar ({STATE_URL})"
            send_telegram(msg)
            _set_cooldown()
            log.error("State-Machine down — Telegram gesendet, Cooldown gesetzt")
        else:
            log.warning("State-Machine down — Cooldown aktiv, kein Telegram")
        return 1

    modbus_vals = extract_modbus_values(state_json)
    log.info(
        "Modbus: aussen=%.1f vorlauf=%.1f ruecklauf=%.1f ww=%.1f heissgas=%s",
        modbus_vals.get("aussen") or 0,
        modbus_vals.get("vorlauf") or 0,
        modbus_vals.get("ruecklauf") or 0,
        modbus_vals.get("warmwasser") or 0,
        modbus_vals.get("heissgas"),
    )

    # 2. CMI-Werte holen (Messwerte-Seite)
    messwerte_html = _cmi_http(CMI_MESSWERTE_PAGE)
    if messwerte_html is None:
        log.error("CMI Messwerte-Seite nicht erreichbar — Abbruch")
        return 1

    cmi_messwerte = parse_messwerte(messwerte_html)
    log.info(
        "CMI Messwerte: aussen=%.1f vorlauf=%.1f ruecklauf=%.1f ww=%.1f heissgas=%s",
        cmi_messwerte.get("aussen") or 0,
        cmi_messwerte.get("vorlauf") or 0,
        cmi_messwerte.get("ruecklauf") or 0,
        cmi_messwerte.get("warmwasser") or 0,
        cmi_messwerte.get("heissgas"),
    )

    # Kurze Pause zwischen den CMI-Anfragen (Rate-Limit-Respekt)
    time.sleep(2)

    # 3. CMI-Ausgaenge holen
    ausgaenge_html = _cmi_http(CMI_AUSGAENGE_PAGE)
    if ausgaenge_html is None:
        log.warning("CMI Ausgaenge-Seite nicht erreichbar — Digital-Vergleich uebersprungen")
        cmi_ausgaenge: dict = {}
    else:
        cmi_ausgaenge = parse_ausgaenge(ausgaenge_html)
        log.info(
            "CMI Ausgaenge: verdichter=%s heizstab_ww=%s alarm=%s",
            cmi_ausgaenge.get("verdichter"),
            cmi_ausgaenge.get("heizstab_ww"),
            cmi_ausgaenge.get("alarm"),
        )

    # 4. Vergleich
    warnings = compare_values(modbus_vals, cmi_messwerte, cmi_ausgaenge)

    # 5. Telegram bei Abweichungen
    if warnings:
        for w in warnings:
            tg_msg = f"{TELEGRAM_PREFIX} {w}"
            send_telegram(tg_msg)
        log.warning("Plausibility-Check: %d Warnung(en) gesendet", len(warnings))
    else:
        log.info("Plausibility-Check: alle Werte OK — kein Alarm")

    log.info("=== Plausibility-Check Ende ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
