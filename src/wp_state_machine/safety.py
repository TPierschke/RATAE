"""
safety.py — Whitelist-Enforcement fuer CMI-Schreibzugriffe.

Einzige Stelle im Code die entscheidet ob ein Schreib-Call ans CMI
erlaubt ist. Keine Ausnahmen. Kein Bypass.

Whitelist (Phase 1):
  F:1 FBHEIZ:
    3E9001301C  Betriebsart (1=Standby..7=Feiertag)
    3EB001300C  Normal-Soll (°C)
    3EB001300D  Absenk-Soll (°C)
  F:9 WW_ANF.2:
    3E80093125=1  Verdichter-WW-Boost starten (Legionellenschutz-Trigger)

Verboten:
  Alle 3E91*-Adressen  (direkte Output-Schalter A1-A10)
  3E80153125           (F:21 WW_ANF.9 Heizstab direkt — Energieverschwendung)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Whitelist (abgeschlossene Menge — kein generisches Muster)
# ---------------------------------------------------------------------------

WHITELIST: Final[dict[str, dict]] = {
    "3E9001301C": {
        "name": "FBHEIZ Betriebsart",
        "function": "F:1",
        "allowed_values": {1, 2, 3, 4, 5, 6, 7},
        "description": "1=Standby 2=Zeit 3=Normal 4=Abgesenkt 5=Party 6=Urlaub 7=Feiertag",
    },
    "3EB001300C": {
        "name": "FBHEIZ Normal-Soll",
        "function": "F:1",
        "value_range": (10, 30),
        "description": "Raumsoll Normal in Grad C (10..30)",
    },
    "3EB001300D": {
        "name": "FBHEIZ Absenk-Soll",
        "function": "F:1",
        "value_range": (5, 25),
        "description": "Raumsoll Abgesenkt in Grad C (5..25)",
    },
    "3E80093125": {
        "name": "WW_ANF.2 STARTEN",
        "function": "F:9",
        "allowed_values": {1},
        "description": "Verdichter-WW-Boost. 1=starten. Auto-Stop bei 70 Grad.",
    },
    "3E80093126": {
        "name": "WW_ANF.2 STOPPEN",
        "function": "F:9",
        "allowed_values": {1},
        "description": "Verdichter-WW-Boost manuell stoppen.",
    },
    "3EB0023118": {
        "name": "WW_ANF.2 WW-Soll",
        "function": "F:9",
        "value_range": (30, 70),
        "description": "WW-Soll-Temperatur Legionellenschutz (30..70 Grad C).",
    },
}

# ---------------------------------------------------------------------------
# Verbotene Adressen + Praefixe
# ---------------------------------------------------------------------------

FORBIDDEN_PREFIXES: Final[tuple[str, ...]] = ("3E91",)  # direkte Aktor-Ausgaenge A1-A10

FORBIDDEN_EXACT: Final[frozenset[str]] = frozenset(
    {
        "3E80153125",  # F:21 WW_ANF.9 Heizstab direkt
        "3E80153126",  # F:21 WW_ANF.9 Heizstab stop (auch verboten — nur via Funktion)
    }
)


# ---------------------------------------------------------------------------
# Ergebnis-Datentyp
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WhitelistResult:
    allowed: bool
    address: str
    value: int | float | None
    reason: str


# ---------------------------------------------------------------------------
# Haupt-Funktion
# ---------------------------------------------------------------------------


def check_write(address: str, value: int | float) -> WhitelistResult:
    """
    Prueft ob ein Schreib-Call ans CMI erlaubt ist.

    Gibt WhitelistResult zurueck. Bei allowed=False darf KEIN HTTP-Call gemacht werden.
    Diese Funktion wird immer aufgerufen, auch im DRY_RUN-Modus (um Fehler fruehzeitig
    zu erkennen).
    """
    address = address.upper().strip()

    # 1. Explizit verboten?
    if address in FORBIDDEN_EXACT:
        reason = f"VERBOTEN: {address} ist in der Sperrliste (direkte Heizstab/Aktor-Schaltung)"
        log.warning("safety.check_write BLOCKED: %s value=%s — %s", address, value, reason)
        return WhitelistResult(allowed=False, address=address, value=value, reason=reason)

    # 2. Verbotenes Praefix?
    for prefix in FORBIDDEN_PREFIXES:
        if address.startswith(prefix):
            reason = (
                f"VERBOTEN: {address} beginnt mit {prefix} "
                f"(direkte Aktor-Ausgaenge gesperrt)"
            )
            log.warning("safety.check_write BLOCKED: %s value=%s — %s", address, value, reason)
            return WhitelistResult(allowed=False, address=address, value=value, reason=reason)

    # 3. Auf Whitelist?
    if address not in WHITELIST:
        reason = f"NICHT AUF WHITELIST: {address} — nur whitelisted Adressen duerfen geschrieben werden"
        log.warning("safety.check_write BLOCKED: %s value=%s — %s", address, value, reason)
        return WhitelistResult(allowed=False, address=address, value=value, reason=reason)

    entry = WHITELIST[address]

    # 4. Wertebereich pruefen
    if "allowed_values" in entry:
        allowed_vals = entry["allowed_values"]
        try:
            int_value = int(value)
        except (TypeError, ValueError):
            reason = f"UNGÜLTIGER WERT: {value!r} ist kein Integer fuer {address}"
            log.warning("safety.check_write BLOCKED: %s value=%s — %s", address, value, reason)
            return WhitelistResult(allowed=False, address=address, value=value, reason=reason)
        if int_value not in allowed_vals:
            reason = (
                f"WERT AUSSERHALB: {value} nicht in erlaubten Werten {allowed_vals} "
                f"fuer {address} ({entry['name']})"
            )
            log.warning("safety.check_write BLOCKED: %s value=%s — %s", address, value, reason)
            return WhitelistResult(allowed=False, address=address, value=value, reason=reason)

    elif "value_range" in entry:
        lo, hi = entry["value_range"]
        try:
            num_value = float(value)
        except (TypeError, ValueError):
            reason = f"UNGÜLTIGER WERT: {value!r} ist keine Zahl fuer {address}"
            log.warning("safety.check_write BLOCKED: %s value=%s — %s", address, value, reason)
            return WhitelistResult(allowed=False, address=address, value=value, reason=reason)
        if not (lo <= num_value <= hi):
            reason = (
                f"WERT AUSSERHALB RANGE: {value} nicht in [{lo}..{hi}] "
                f"fuer {address} ({entry['name']})"
            )
            log.warning("safety.check_write BLOCKED: %s value=%s — %s", address, value, reason)
            return WhitelistResult(allowed=False, address=address, value=value, reason=reason)

    reason = f"OK: {address} ({entry['name']}) value={value} — whitelisted"
    log.debug("safety.check_write ALLOWED: %s value=%s", address, value)
    return WhitelistResult(allowed=True, address=address, value=value, reason=reason)


def get_whitelist_info() -> dict[str, dict]:
    """Gibt lesbare Kopie der Whitelist zurueck (fuer /health und UI)."""
    return {
        addr: {k: (list(v) if isinstance(v, (set, frozenset)) else v) for k, v in entry.items()}
        for addr, entry in WHITELIST.items()
    }
