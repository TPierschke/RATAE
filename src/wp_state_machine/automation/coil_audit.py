"""
automation/coil_audit.py — Coil-Mapping-Wahrheits-Test bei Verdichter-Lauf.

Triggert sich selbst wenn der Verdichter von AUS auf AN wechselt:
- Sofort einen Web-Scrape ausloesen (Wahrheit aus der CMI-UI)
- Coil-Zustaende der State-Machine gegen Scraper-Werte vergleichen
- Bei Diskrepanz: Telegram-Alarm und ausfuehrliches Log
- Bei Konsens: kurzes Log "audit OK"

Entstanden 2026-05-07 nach User-Hinweis dass Coil-Mapping schon einmal
falsch war. Soll proaktiv erkennen wenn das Mapping wieder kippt
(z.B. nach CMI-Konfig-Aenderung).
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from wp_state_machine.api.rest import AppState
    from wp_state_machine.config import Config

log = logging.getLogger(__name__)

# Coil-Felder im Sensoren-Modell die wir mit Web-Scraper-Werten vergleichen.
# Web-Scraper liefert die Outputs-Page-Felder mit denselben Namen.
COMPARE_FIELDS: tuple[str, ...] = (
    "verdichter",
    "ventil_ww",
    "heizstab_hz",
    "heizstab_ww",
    "pumpe_zirku",
    "alarm",
)

# Web-Scraper-spezifische Feld-Aliase (manche Felder heissen im Scraper anders)
SCRAPER_ALIAS: dict[str, str] = {
    "pumpe_hzkr": "pumpe_hzkr_ein",
    "ladepumpe":  "ladepumpe_ein",
}


async def _telegram_alert(message: str) -> None:
    """Schickt eine Nachricht via ThoPAS-Bot. Schluckt alle Fehler still."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        # Lade aus Datei wenn nicht im Env
        try:
            with open(os.path.expanduser("~/.claude/channels/telegram/.env")) as f:
                for line in f:
                    if line.startswith("TELEGRAM_BOT_TOKEN="):
                        token = line.split("=", 1)[1].strip()
                        break
        except Exception:
            return
    if not token:
        return
    try:
        import aiohttp
        async with aiohttp.ClientSession() as s:
            await s.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                data={"chat_id": "5955462676", "text": message[:3500]},
                timeout=aiohttp.ClientTimeout(total=8),
            )
    except Exception as exc:
        log.warning("Telegram-Alert failed: %s", exc)


async def _audit_now(app_state, config) -> dict:
    """
    Loest einen Web-Scrape aus und vergleicht mit Modbus-Werten.
    Return: {field: (modbus_val, scraper_val, match)}
    """
    from wp_state_machine.__main__ import scrape_once
    try:
        merged = await scrape_once(config, app_state)
    except Exception as exc:
        log.error("coil_audit: scrape fehlgeschlagen: %s", exc)
        return {}

    sensoren = app_state.sensoren
    diff: dict[str, tuple] = {}
    for f in (*COMPARE_FIELDS, *SCRAPER_ALIAS.keys()):
        modbus_val = getattr(sensoren, f, None)
        scraper_key = SCRAPER_ALIAS.get(f, f)
        scraper_val = merged.get(scraper_key)
        match = (modbus_val == scraper_val) if scraper_val is not None else None
        diff[f] = (modbus_val, scraper_val, match)
    return diff


async def _self_heal_alarm(app_state, scraper_alarm: bool) -> None:
    """
    Wenn Modbus faelschlich Alarm meldet aber Scraper nicht, korrigieren wir
    das in der State-Machine, damit die UI keinen Panik-Pulse zeigt.
    """
    async with app_state._lock:
        updated = app_state.sensoren.model_copy(
            update={"alarm": scraper_alarm, "timestamp": datetime.now(timezone.utc)}
        )
        app_state.sensoren = updated
    log.warning("coil_audit: Modbus-Alarm war falsch, in AppState auf %s korrigiert", scraper_alarm)


async def _send_real_alarm_burst(app_state) -> None:
    """
    Echter Alarm verifiziert. Burst von 4 Telegram-Nachrichten direkt hintereinander
    (mehrfacher Notification-Sound = klar dringend). Danach alle 10 min eine
    Erinnerung bis der Alarm zurueckgesetzt ist (Modbus liefert alarm=False).
    """
    s = app_state.sensoren
    detail = (
        f"Verdichter={s.verdichter} Vorlauf={s.vorlauf} Heissgas={s.heissgas} "
        f"HD-Schalter={s.hd_schalter} ND1={s.nd_schalter1} ND2={s.nd_schalter2}"
    )
    base_msg = (
        "[ThoPAS|ALARM] Waermepumpe meldet ALARM-Ausgang A5.\n"
        "Beide Quellen (Modbus + Web-Scraper) bestaetigen.\n"
        f"Status: {detail}\n"
        "Bitte SOFORT die Anlage pruefen."
    )
    # Initial-Burst: 4 Nachrichten direkt hintereinander
    for i in range(1, 5):
        await _telegram_alert(f"({i}/4) {base_msg}")
        await asyncio.sleep(0.3)

    # Erinnerung alle 10 min bis Alarm weg ist
    reminder_count = 0
    while app_state.sensoren.alarm is True:
        await asyncio.sleep(600)
        if app_state.sensoren.alarm is not True:
            break
        reminder_count += 1
        await _telegram_alert(
            f"[ThoPAS|ALARM] Erinnerung #{reminder_count} — Alarm steht noch an. "
            "Bitte Anlage pruefen."
        )

    # Alarm wurde zurueckgesetzt — Entwarnung
    await _telegram_alert("[ThoPAS|ALARM] Alarm wurde zurueckgesetzt. Anlage wieder OK.")
    log.info("Alarm-Burst beendet — Alarm wieder False, %d Reminder versendet", reminder_count)


async def handle_alarm_edge(app_state, config) -> None:
    """
    Wird DIREKT aus update_coil_from_modbus aufgerufen sobald Alarm
    von False auf True wechselt — kein Loop, kein Polling.
    Verifiziert mit Web-Scraper, self-heals oder triggert Burst.
    """
    log.warning("handle_alarm_edge: Modbus-Alarm aktiv — sofortige Verifikation")
    try:
        diff = await _audit_now(app_state, config)
        _, scraper_alarm, match = diff.get("alarm", (None, None, None))
        if scraper_alarm is False and match is False:
            await _self_heal_alarm(app_state, scraper_alarm=False)
            await _telegram_alert(
                "[ThoPAS|coil-audit] Hinweis (kein echter Alarm): Modbus meldete "
                "Alarm, Web-Scraper bestaetigt das nicht. Wert in der UI wurde "
                "automatisch korrigiert. Anlage laeuft normal."
            )
        elif scraper_alarm is True:
            await _send_real_alarm_burst(app_state)
    except Exception as exc:
        log.error("handle_alarm_edge fehlgeschlagen: %s", exc)


VERDICHTER_AUDIT_COOLDOWN_SEC = 300  # 5 min — gibt dem 5-min Web-Scraper Zeit zu konvergieren


async def handle_verdichter_edge(app_state, config) -> None:
    """
    Wird direkt aus update_coil_from_modbus aufgerufen wenn Verdichter
    von False auf True wechselt — Mapping-Audit zur Diagnose.

    Cooldown vor dem Audit: Modbus liest live, der Web-Scraper laeuft aber
    nur alle 5 min. Ein sofortiger Vergleich erzeugt deshalb regelmaessig
    false-positive DISKREPANZ-Meldungen direkt nach dem Anspringen des
    Verdichters. 5 min Karenz, dann Re-Check ob Verdichter ueberhaupt
    noch laeuft, dann Audit.
    """
    log.info("handle_verdichter_edge: Cooldown %ds bevor Audit startet", VERDICHTER_AUDIT_COOLDOWN_SEC)
    await asyncio.sleep(VERDICHTER_AUDIT_COOLDOWN_SEC)
    if app_state.sensoren.verdichter is not True:
        log.info("handle_verdichter_edge: Verdichter inzwischen wieder AUS — kein Audit")
        return
    log.info("handle_verdichter_edge: Audit gegen Web-Scraper")
    try:
        diff = await _audit_now(app_state, config)
        mismatches = [
            f"{f}: modbus={mb} scraper={sc}"
            for f, (mb, sc, m) in diff.items()
            if m is False
        ]
        if mismatches:
            msg = (
                "[ThoPAS|coil-audit] DISKREPANZ erkannt bei Verdichter-Lauf:\n"
                + "\n".join(mismatches)
            )
            log.warning(msg)
            await _telegram_alert(msg)
        else:
            log.info("coil_audit OK: Modbus und Scraper konsistent")
    except Exception as exc:
        log.error("handle_verdichter_edge fehlgeschlagen: %s", exc)
