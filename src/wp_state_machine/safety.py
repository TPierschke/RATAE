"""
safety.py — Whitelist-Enforcement fuer CMI-Schreibzugriffe.

Einzige Stelle im Code die entscheidet ob ein Schreib-Call ans CMI
erlaubt ist. Keine Ausnahmen. Kein Bypass.

Whitelist (Phase 2, gehaertet 2026-05-15):
  F:1 FBHEIZ:
    3E9001301C  Betriebsart — nur {1=Standby, 3=Normal}
                (Tibber-Heizpause/-Lade Steuerung)
  F:9 WW_ANF.2:
    3E80093125=1  WW-Boost starten (Legionellenschutz, Auto-Stop bei 70 Grad)
    3E80093126=1  WW-Boost stoppen

Bewusst NICHT in Whitelist (User-Regel 2026-05-15):
  3EB001300C  Normal-Soll  — nur ueber CMI/Anlage selbst
  3EB001300D  Absenk-Soll  — nur ueber CMI/Anlage selbst
  3EB0023118  WW-Soll      — disruptiv (HD-Schalter-Risiko bei >50 Grad)
  Betriebsart-Werte 2,4,5,6,7 (Zeit/Abgesenkt/Party/Urlaub/Feiertag) — manuell nur

Verboten:
  Alle 3E91*-Adressen  (direkte Output-Schalter A1-A10)
  3E80153125           (F:21 WW_ANF.9 Heizstab direkt — Energieverschwendung)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Final

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Whitelist (abgeschlossene Menge — kein generisches Muster)
# Optional pro Eintrag:
#   dry_run_override: bool | None
# ---------------------------------------------------------------------------

WHITELIST: Final[dict[str, dict]] = {
    "3E9001301C": {
        "name": "FBHEIZ Betriebsart",
        "function": "F:1",
        "allowed_values": {1, 3},
        "description": "Nur 1=Standby (Heizpause) und 3=Normal (Heizung an). Andere Modi nur ueber CMI/Anlage.",
    },
    "3E80093125": {
        "name": "WW_ANF.2 STARTEN",
        "function": "F:9",
        "allowed_values": {1},
        "description": "Verdichter-WW-Boost / Legionellenschutz. 1=starten. Auto-Stop bei 70 Grad.",
    },
    "3E80093126": {
        "name": "WW_ANF.2 STOPPEN",
        "function": "F:9",
        "allowed_values": {1},
        "description": "Verdichter-WW-Boost manuell stoppen.",
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
    effective_dry_run: bool | None = field(default=None)


# ---------------------------------------------------------------------------
# Haupt-Funktion
# ---------------------------------------------------------------------------


def check_write(
    address: str, value: int | float, global_dry_run: bool = True
) -> WhitelistResult:
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

    if "dry_run_override" in entry:
        effective_dry_run = entry["dry_run_override"]
    else:
        effective_dry_run = global_dry_run

    reason = f"OK: {address} ({entry['name']}) value={value} — whitelisted"
    log.debug("safety.check_write ALLOWED: %s value=%s", address, value)
    return WhitelistResult(
        allowed=True,
        address=address,
        value=value,
        reason=reason,
        effective_dry_run=effective_dry_run,
    )


def get_whitelist_info() -> dict[str, dict]:
    """Gibt lesbare Kopie der Whitelist zurueck (fuer /health und UI)."""
    return {
        addr: {k: (list(v) if isinstance(v, (set, frozenset)) else v) for k, v in entry.items()}
        for addr, entry in WHITELIST.items()
    }
