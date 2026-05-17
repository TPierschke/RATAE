"""
ingest/web_scraper.py — CMI menupage.cgi HTML-Scraper.

Liest Sensor-Werte und Betriebszustaende durch Parsen der CMI-Web-UI.
Kein JSON-API fuer Outputs (CMI-Bug: Outputs leer in JSON-API).

Pages:
  3E01581E  Funktionsuebersicht  (Betriebsart, Sollwerte, Eingaenge)
  3E005806  Ausgaenge-Zustand    (A1-A10 EIN/AUS/AUTO)
  3E005804  Messwerteuebersicht  (Temperaturen kompakt)
  3E01580E  FBHEIZ Detail        (Betriebsart, Sollwerte)
  3E06580E  F:6 Zaehler Heizstab HZ (Betriebsstunden Heizstab FBH)
  3E07580E  F:7 Zaehler Heizstab WW (Betriebsstunden Heizstab WW)

Parsing: BeautifulSoup4 + regex auf text-content.

Hinweis: Tests duerfen NIEMALS einen echten HTTP-Call machen!
         HTML-Fixtures aus tests/fixtures/menupage_pages/ nutzen.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

_TEMP_RE = re.compile(r"([-+]?\d+[,.]?\d*)\s*[AÂ°]?\s*°?\s*[Cc]?(?:\s*°C)?")
_TEMP_SIMPLE = re.compile(r"([-+]?\d+(?:[,.]\d+)?)\s*(?:Â\s*°C|°C|°|Grad)")


def _parse_temp(text: str) -> Optional[float]:
    """
    Parst Temperatur aus CMI-HTML-Text.
    CMI kodiert Grad-Zeichen oft als 'Â°C' (UTF-8-Mojibake fuer °C).
    """
    text = text.strip()
    # "12,3 Â°C" oder "12,3 °C" oder "12.3°C"
    m = re.search(r"([-+]?\d+)[,.](\d+)\s*(?:Â\s*°C|°C|°|Grad)", text)
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    m = re.search(r"([-+]?\d+)\s*(?:Â\s*°C|°C|°|Grad)", text)
    if m:
        return float(m.group(1))
    return None


def _is_ein(text: str) -> bool:
    """Erkennt EIN-Zustand in CMI-Output-Text."""
    t = text.upper().strip()
    return "EIN" in t or "ON" in t or "AUTO/EIN" in t


def _is_aus(text: str) -> bool:
    """Erkennt AUS-Zustand."""
    t = text.upper().strip()
    return "AUS" in t or "OFF" in t or "AUTO/AUS" in t


# ---------------------------------------------------------------------------
# Page 3E005806 — Ausgaenge (Output-States)
# ---------------------------------------------------------------------------


def parse_outputs_page(html: str) -> dict[str, Optional[bool | float]]:
    """
    Parst Ausgaenge-Seite (3E005806).

    Gibt dict mit Ausgangs-Zustaenden zurueck:
      verdichter: bool
      ventil_ww: bool
      alarm: bool
      heizstab_hz: bool
      heizstab_ww: bool
      pumpe_zirku: bool
      pumpe_hzkr_ein: bool  (A1 EIN/AUS; genaue % nur via JSON-API)
      ladepumpe_ein: bool

    Pattern: "&nbsp;3:&nbsp;Verdichter<br>&nbsp;&nbsp;&nbsp;&nbsp;AUTO/AUS..."
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")

    result: dict[str, Optional[bool | float]] = {}

    # Mapping: Ausgangs-Nummer → Feldname
    output_map = {
        "1": "pumpe_hzkr_ein",
        "2": "ladepumpe_ein",
        "3": "verdichter",
        "5": "alarm",
        "7": "ventil_ww",
        "8": "heizstab_hz",
        "9": "heizstab_ww",
        "10": "pumpe_zirku",
    }

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Suche nach Zeilen wie " 3: Verdichter" oder "10: Pumpe-Zirku"
        m = re.match(r"^[\x00\s]*(\d{1,2})\s*:\s*(.+)$", line)
        if m:
            num = m.group(1).strip()
            if num in output_map:
                field = output_map[num]
                # Naechste Zeile hat Status
                if i + 1 < len(lines):
                    status_line = lines[i + 1].strip()
                    result[field] = _is_ein(status_line)
        i += 1

    log.debug("parse_outputs_page: %s", result)
    return result


# ---------------------------------------------------------------------------
# Page 3E01581E — Funktionsuebersicht (Betriebsart, Sollwerte, Eingaenge)
# ---------------------------------------------------------------------------

_BETRIEBSART_MAP = {
    "STANDBY": 1,
    "ZEIT": 2,
    "AUTO": 2,
    "NORMAL": 3,
    "ABGESENKT": 4,
    "PARTY": 5,
    "URLAUB": 6,
    "FEIERTAG": 7,
}


def _parse_betriebsart(text: str) -> Optional[int]:
    """Parst Betriebsart-String zu Int. Gibt None wenn nicht erkannt."""
    t = text.upper().strip()
    for key, val in _BETRIEBSART_MAP.items():
        if key in t:
            return val
    return None


def parse_functions_overview(html: str) -> dict[str, object]:
    """
    Parst Funktionsuebersicht (3E01581E).

    Liefert:
      betriebsart: int (1-7)
      normal_soll: float (°C)
      absenk_soll: float (°C)
      vorlauf_ist: float (°C)
      vorlauf_soll: float (°C)
      raum_ist: float (°C)
      ww_soll_normal: float (°C, aus F:2 Tww.SOLL)
      ww_ist: float (°C, aus F:2 Tww.IST)
      aussen: float (°C)
      vorlauf: float (°C, Puffer S2)
      ruecklauf: float (°C, FBH-RL S3)
      warmwasser: float (°C, WW-Speicher S4)
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    result: dict[str, object] = {}

    for i, line in enumerate(lines):
        uline = line.upper()

        # Betriebsart: "BETRIEB: NORMAL"
        if "BETRIEB:" in uline or "BETRIEBSART" in uline:
            m = re.search(r"BETRIEB:\s*(\w+)", uline)
            if m:
                ba = _parse_betriebsart(m.group(1))
                if ba is not None:
                    result["betriebsart"] = ba

        # Normal-Soll: "Traum.NORMAL: 24 °C"
        elif "NORMAL" in uline and ("SOLL" in uline or "TRAUM" in uline):
            t = _parse_temp(line)
            if t is not None:
                result["normal_soll"] = t

        # Absenk-Soll: "Traum.ABSENK: 21 °C"
        elif "ABSENK" in uline:
            t = _parse_temp(line)
            if t is not None:
                result["absenk_soll"] = t

        # Raum-IST: "Traum.IST: 27,2 °C"
        # Muss vor anderen Traum-Patterns geprueft werden
        elif "TRAUM" in uline and "IST" in uline and "SOLL" not in uline:
            t = _parse_temp(line)
            if t is not None:
                result["raum_ist"] = t

        # WW-Soll Normal: "Tww.SOLL: 49 °C" aus F:2 WW_ANF.1
        elif "TWW" in uline and "SOLL" in uline:
            t = _parse_temp(line)
            if t is not None:
                result["ww_soll_normal"] = t

        # WW-IST: "Tww.IST: 45,3 °C"
        elif "TWW" in uline and "IST" in uline:
            t = _parse_temp(line)
            if t is not None:
                result["ww_ist"] = t

        # Vorlauf-IST aus FBHEIZ-Block: "Tvorl.IST: 27,5 °C"
        elif "TVORL" in uline and "IST" in uline:
            t = _parse_temp(line)
            if t is not None:
                result["vorlauf_ist"] = t

        # Vorlauf-Soll: "Tvorl.SOLL: 29,5 °C"
        elif "TVORL" in uline and "SOLL" in uline:
            t = _parse_temp(line)
            if t is not None:
                result["vorlauf_soll"] = t

        # Eingaenge Abschnitt — Sensor-Mapping
        # "1: Temp.Aussen" → naechste Zeile hat Wert
        elif re.match(r"^\s*1\s*:\s*Temp", line, re.I):
            if i + 1 < len(lines):
                t = _parse_temp(lines[i + 1])
                if t is not None:
                    result["aussen"] = t

        elif re.match(r"^\s*2\s*:\s*TPuffer", line, re.I):
            if i + 1 < len(lines):
                t = _parse_temp(lines[i + 1])
                if t is not None:
                    result["vorlauf"] = t

        elif re.match(r"^\s*3\s*:\s*THeiz", line, re.I):
            if i + 1 < len(lines):
                t = _parse_temp(lines[i + 1])
                if t is not None:
                    result["ruecklauf"] = t

        elif re.match(r"^\s*4\s*:\s*TWW", line, re.I):
            if i + 1 < len(lines):
                t = _parse_temp(lines[i + 1])
                if t is not None:
                    result["warmwasser"] = t

    log.debug("parse_functions_overview: %s", result)
    return result


# ---------------------------------------------------------------------------
# Page 3E01580E — FBHEIZ Detail
# ---------------------------------------------------------------------------


def parse_fbheiz_detail(html: str) -> dict[str, object]:
    """
    Parst FBHEIZ-Detailseite (3E01580E).

    Liefert: betriebsart, normal_soll, absenk_soll, vorlauf_ist, vorlauf_soll, aussen.
    Redundant zu parse_functions_overview, aber praeziser fuer F:1-Werte.
    """
    return parse_functions_overview(html)


# ---------------------------------------------------------------------------
# Pages 3E06580E + 3E07580E — Betriebsstundenzaehler Heizstaebe (F:6, F:7)
# ---------------------------------------------------------------------------

_BETRIEBS_HR_RE = re.compile(r"Betriebsdauer[:\s]*\n?\s*(\d+)\s*hr", re.I)


def parse_heizstab_page(html: str) -> Optional[int]:
    """
    Parst eine BETRSTDZ-Seite (F:6 oder F:7).
    Liefert Betriebsdauer in Stunden (int) oder None.

    HTML-Muster:
        Betriebsdauer:
                    71 hr
    """
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(separator="\n")
    m = _BETRIEBS_HR_RE.search(text)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    # Fallback: find "Betriebsdauer:" line, next non-empty line with digits + hr
    lines = [l.strip() for l in text.splitlines()]
    for i, line in enumerate(lines):
        if "betriebsdauer" in line.lower():
            for j in range(i + 1, min(i + 4, len(lines))):
                nm = re.match(r"^(\d+)\s*hr", lines[j], re.I)
                if nm:
                    return int(nm.group(1))
    return None


# ---------------------------------------------------------------------------
# Zusammenfassender Parser — alle relevanten Pages
# ---------------------------------------------------------------------------


def merge_scrape_results(
    outputs: dict,
    functions: dict,
    heizstab_hz_h: Optional[int] = None,
    heizstab_ww_h: Optional[int] = None,
) -> dict[str, object]:
    """
    Merged Outputs-Page + Functions-Overview + Heizstab-Zaehler in ein gemeinsames dict.
    Functions-Werte ueberschreiben Outputs-Werte bei Konflikten.
    Extrahiert zusaetzlich ein 'setpoints' sub-dict mit Sollwerten.
    """
    merged = {}
    merged.update(outputs)
    merged.update(functions)
    if heizstab_hz_h is not None:
        merged["betr_std_heizstab_fb"] = heizstab_hz_h
    if heizstab_ww_h is not None:
        merged["betr_std_heizstab_ww"] = heizstab_ww_h

    # Extrahiere Setpoints als sub-dict fuer app_state.setpoints
    setpoints = {}
    if "ww_soll_normal" in functions:
        setpoints["ww_soll_normal"] = functions["ww_soll_normal"]
    if "ww_ist" in functions:
        setpoints["ww_ist"] = functions["ww_ist"]
    if "normal_soll" in functions:
        setpoints["normal_soll"] = functions["normal_soll"]
    if "absenk_soll" in functions:
        setpoints["absenk_soll"] = functions["absenk_soll"]
    if "vorlauf_soll" in functions:
        setpoints["vorlauf_soll"] = functions["vorlauf_soll"]

    if setpoints:
        merged["setpoints"] = setpoints

    return merged


# ---------------------------------------------------------------------------
# Fixture-Lader fuer Tests
# ---------------------------------------------------------------------------


def load_fixture(page_id: str, fixture_dir: Path) -> str:
    """
    Laedt HTML-Fixture aus fixture_dir fuer gegebene page_id.
    Wirft FileNotFoundError wenn nicht vorhanden.
    """
    path = fixture_dir / f"page_{page_id}.html"
    if not path.exists():
        raise FileNotFoundError(f"Fixture nicht gefunden: {path}")
    return path.read_text(encoding="utf-8", errors="replace")
