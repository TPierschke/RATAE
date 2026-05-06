"""
ingest/json_poller.py — CMI JSON-API Poller.

Liest Inputs (Temperaturen, Digital-Inputs) via JSON-API.
Outputs sind in JSON-API leer (CMI-Bug) — deshalb web_scraper.py fuer Outputs.

API-URL: http://admin:admin@192.168.178.45/INCLUDE/api.cgi?jsonnode=62&jsonparam=I,O

Rate-Limit: max 1 req/sek, empfohlen 1/min.
Bei HTTP-Status 4 (TOO MANY REQUESTS): 5 Min warten, nicht wiederholen.

Dieses Modul macht KEINE echten HTTP-Calls in Tests!
Tests verwenden gemockte Response-Dicts (siehe test_json_poller.py).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

log = logging.getLogger(__name__)

# CMI JSON-API Antwort-Struktur (Node 62, Inputs)
# Beispiel: {"StatusCode": 0, "Data": {"Inputs": [...], "Outputs": [...]}}
# Status-Codes: 0=OK, 4=TOO_MANY_REQUESTS

CMI_STATUS_OK = 0
CMI_STATUS_TOO_MANY_REQUESTS = 4

# Input-Index-Mapping (1-basiert, wie in CMI)
INPUT_MAP: dict[int, str] = {
    1: "aussen",
    2: "vorlauf",
    3: "ruecklauf",
    4: "warmwasser",
    7: "heissgas",
    8: "fluessigkeit",
    9: "saugleitung",
    10: "phasenwaechter",
    11: "verdichter_freigabe",
    12: "nd_schalter1",
    13: "hd_schalter",
    14: "nd_schalter2",
}


def parse_json_api_response(data: dict[str, Any]) -> dict[str, Optional[float | bool]]:
    """
    Parst JSON-API-Antwort auf Sensor-Werte.

    Gibt dict mit Sensor-Feldern zurueck. Bei Fehler oder leerem Response: leeres dict.
    Outputs werden IGNORIERT (CMI-Bug: immer leer).

    Erwartet Format:
      {"StatusCode": 0, "Data": {"Inputs": [{"Value": 12.3, "Unit": "°C"}, ...]}}
    """
    status = data.get("StatusCode", -1)
    if status == CMI_STATUS_TOO_MANY_REQUESTS:
        log.warning("CMI JSON-API: TOO MANY REQUESTS — bitte 5 Minuten warten!")
        return {}
    if status != CMI_STATUS_OK:
        log.warning("CMI JSON-API: Unbekannter StatusCode %s", status)
        return {}

    api_data = data.get("Data", {})
    inputs_raw = api_data.get("Inputs", [])

    result: dict[str, Optional[float | bool]] = {}

    for i, entry in enumerate(inputs_raw, start=1):
        field = INPUT_MAP.get(i)
        if field is None:
            continue
        if not isinstance(entry, dict):
            continue

        raw_value = entry.get("Value")
        unit = entry.get("Unit", "")

        if raw_value is None:
            continue

        try:
            # Digitale Inputs: Unit leer oder "Digital", Value 0/1
            if unit in ("", "Digital", None) and i >= 10:
                result[field] = bool(int(raw_value))
            else:
                result[field] = float(raw_value)
        except (ValueError, TypeError) as exc:
            log.debug("JSON-API parse error fuer Input %d (%s): %s", i, field, exc)

    log.debug("parse_json_api_response: %d Felder geparst", len(result))
    return result


def check_status_code(data: dict[str, Any]) -> tuple[bool, str]:
    """
    Prueft StatusCode der JSON-API-Antwort.

    Gibt (ok, message) zurueck.
    """
    status = data.get("StatusCode", -1)
    if status == CMI_STATUS_OK:
        return True, "OK"
    if status == CMI_STATUS_TOO_MANY_REQUESTS:
        return False, "TOO_MANY_REQUESTS — 5 Minuten warten"
    return False, f"Unbekannter StatusCode: {status}"
