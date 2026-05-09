"""
ingest/cmi_writer.py — Schreib-Schicht ans CMI.

Quelle: 99_myUtilsTACMIHTTP.pm der Pierschke-FHEM-Anlage. Bewaehrt seit Jahren.
URL-Schema: GET menupage.cgi?page=<HEX>&changeadr=<ADDR>&changeto=<WERT>

Nur whitelisted Funktionen. Direkte Aktor-Schaltungen (3E91*, Heizstab direkt)
sind weder in der Whitelist noch hier — bewusst.

Aufrufer:
  - REST-Endpunkte in api/rest.py
  - im DRY_RUN-Modus wird nur geloggt + Audit, kein HTTP-Call
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

import aiohttp

if TYPE_CHECKING:
    from wp_state_machine.config import Config

log = logging.getLogger(__name__)

# Funktions-Pages am CMI (zweiter URL-Parameter)
PAGE_F1 = "3E01581E"  # F:1 FBHEIZ — Betriebsart, Normalsoll, Absenksoll, WW-Soll
PAGE_F9 = "3E09580E"  # F:9 WW_ANF.2 — WW-Boost Start/Stop


@dataclass(frozen=True)
class WriteCommand:
    """Eine konkrete CMI-Write-Operation. Nur diese Adressen sind erlaubt."""
    page: str
    address: str
    value: int | float
    name: str  # menschenlesbar fuer Log


# Erlaubte Schreib-Adressen mit Zuordnung zur page.
# Spiegelt die Whitelist in safety.py — beide muessen synchron bleiben.
ADDRESS_TO_PAGE: dict[str, str] = {
    "3E9001301C": PAGE_F1,  # Betriebsart 1..7
    "3EB001300C": PAGE_F1,  # Normalsoll
    "3EB001300D": PAGE_F1,  # Absenksoll
    "3EB0023118": PAGE_F1,  # WW-Soll
    "3E80093125": PAGE_F9,  # WW-Boost START
    "3E80093126": PAGE_F9,  # WW-Boost STOP
}


@dataclass(frozen=True)
class WriteResult:
    success: bool
    address: str
    value: int | float
    cmi_status: Optional[int]
    response_text: str
    reason: str = ""


async def write_to_cmi(config: Config, address: str, value: int | float) -> WriteResult:
    """
    Schreibt einen Funktions-Parameter ans CMI via menupage.cgi.

    WICHTIG: pruef VORHER mit safety.check_write — diese Funktion macht
    keine eigene Whitelist-Pruefung mehr, vertraut auf den Aufrufer.

    Bei DRY_RUN soll dieser Call gar nicht erst aufgerufen werden — der
    Aufrufer entscheidet das.
    """
    address = address.upper().strip()
    if address not in ADDRESS_TO_PAGE:
        return WriteResult(
            success=False, address=address, value=value, cmi_status=None,
            response_text="", reason=f"Adresse nicht in cmi_writer-Mapping: {address}",
        )
    page = ADDRESS_TO_PAGE[address]
    # CMI erwartet Integer fuer changeto — wir formatieren entsprechend.
    if isinstance(value, float) and value.is_integer():
        value_str = str(int(value))
    else:
        value_str = str(value)

    url = f"{config.cmi_base_url()}/menupage.cgi?page={page}&changeadr={address}&changeto={value_str}"
    auth = aiohttp.BasicAuth(*config.cmi_auth())
    timeout = aiohttp.ClientTimeout(total=config.cmi_timeout)

    try:
        async with aiohttp.ClientSession(auth=auth, timeout=timeout) as session:
            async with session.get(url) as resp:
                text = await resp.text()
                status = resp.status
                ok = status == 200
                log.info(
                    "CMI-WRITE addr=%s value=%s page=%s status=%d (%s)",
                    address, value_str, page, status, "OK" if ok else "FAIL",
                )
                return WriteResult(
                    success=ok, address=address, value=value,
                    cmi_status=status, response_text=text[:200],
                    reason="OK" if ok else f"HTTP {status}",
                )
    except asyncio.TimeoutError:
        log.error("CMI-WRITE timeout addr=%s value=%s", address, value_str)
        return WriteResult(
            success=False, address=address, value=value, cmi_status=None,
            response_text="", reason="Timeout",
        )
    except Exception as exc:
        log.error("CMI-WRITE exception addr=%s value=%s: %s", address, value_str, exc)
        return WriteResult(
            success=False, address=address, value=value, cmi_status=None,
            response_text="", reason=f"Exception: {exc}",
        )


# ---------------------------------------------------------------------------
# Convenience-Funktionen (eine pro Whitelist-Adresse)
# ---------------------------------------------------------------------------


async def set_betriebsart(config: Config, value: int) -> WriteResult:
    """F:1 Betriebsart 1..7. Whitelist via safety.check_write vorher!"""
    return await write_to_cmi(config, "3E9001301C", value)


async def set_normalsoll(config: Config, temp_celsius: float) -> WriteResult:
    """F:1 Raum-Soll Normal in °C (10..30). Whitelist vorher!"""
    return await write_to_cmi(config, "3EB001300C", temp_celsius)


async def set_absenksoll(config: Config, temp_celsius: float) -> WriteResult:
    """F:1 Raum-Soll Abgesenkt in °C (5..25). Whitelist vorher!"""
    return await write_to_cmi(config, "3EB001300D", temp_celsius)


async def set_wwsoll(config: Config, temp_celsius: float) -> WriteResult:
    """F:9 WW-Soll-Temperatur in °C (30..70). Whitelist vorher!"""
    return await write_to_cmi(config, "3EB0023118", temp_celsius)


async def start_ww_boost(config: Config) -> WriteResult:
    """F:9 WW_ANF.2 STARTEN=1 (Legionellenschutz / WW-Boost)."""
    return await write_to_cmi(config, "3E80093125", 1)


async def stop_ww_boost(config: Config) -> WriteResult:
    """F:9 WW_ANF.2 STOP=1 (manueller Abbruch des WW-Boost)."""
    return await write_to_cmi(config, "3E80093126", 1)
