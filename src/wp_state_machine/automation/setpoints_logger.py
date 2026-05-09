"""
automation/setpoints_logger.py — Background loop: crawls CMI Funktions-Sollwerte alle 5 min.

Holt Sollwerte von der CMI Funktionsuebersicht-Page (3E01581E):
  - ww_soll_normal: F:2 WW_ANF.1 Sollwert (typischerweise 49-50°C)
  - ww_ist: F:2 WW_ANF.1 Ist-Temperatur
  - normal_soll: F:1 FBHEIZ Raum-Soll Normal
  - absenk_soll: F:1 FBHEIZ Raum-Soll Absenkung
  - vorlauf_soll: F:1 FBHEIZ berechneter Vorlauf-Soll

Aktualisiert app_state.setpoints mit echten CMI-Werten alle 5 Minuten.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

log = logging.getLogger(__name__)

DEFAULT_INTERVAL = 300  # 5 Minuten


async def setpoints_loop(app_state, config: Optional[Any] = None, interval: int = DEFAULT_INTERVAL) -> None:
    """
    Hintergrund-Loop. Aktualisiert app_state.setpoints mit echten CMI-Funktions-Sollwerten.

    Crawlt die Funktionsuebersicht-Page (3E01581E) und extrahiert Sollwerte.
    Falls Crawl fehlschlaegt, beholt vom letzten bekannten Wert oder nutzt Fallbacks.

    Args:
        app_state: AppState-Instanz (muss setpoints dict haben)
        config: Config-Objekt (fuer CMI-Auth und URLs)
        interval: Polling-Intervall in Sekunden (default 300 = 5 min)
    """
    log.info("setpoints_logger gestartet: Funktions-Sollwerte alle %ds", interval)

    while True:
        try:
            # Falls config vorhanden, live vom CMI crawlen; sonst Fallbacks nutzen
            if config:
                import aiohttp
                from wp_state_machine.ingest.web_scraper import parse_functions_overview

                auth = aiohttp.BasicAuth(*config.cmi_auth())
                timeout = aiohttp.ClientTimeout(total=config.cmi_timeout)

                try:
                    async with aiohttp.ClientSession(auth=auth, timeout=timeout) as session:
                        url = config.cmi_menupage_url("3E01581E")
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                html = await resp.text()
                                functions = parse_functions_overview(html)
                                # Extrahiere setpoints aus den geparsten Funktionen
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
                                    app_state.setpoints = setpoints
                                    from datetime import datetime, timezone
                                    app_state.setpoints_last_update = datetime.now(timezone.utc)
                                    log.debug("setpoints_logger: live crawl erfolgreich = %s", setpoints)
                                else:
                                    log.warning("setpoints_logger: keine Sollwerte in 3E01581E gefunden")
                            else:
                                log.warning("setpoints_logger: CMI HTTP %d", resp.status)
                except Exception as exc:
                    log.warning("setpoints_logger: live crawl fehlgeschlagen: %s, nutze fallbacks", exc)
                    # Fallback: Standardwerte nutzen
                    _apply_fallback_setpoints(app_state)
            else:
                # Kein config — fallback nutzen
                _apply_fallback_setpoints(app_state)

        except Exception as exc:
            log.error("setpoints_logger Fehler: %s", exc)
            _apply_fallback_setpoints(app_state)

        await asyncio.sleep(interval)


def _apply_fallback_setpoints(app_state) -> None:
    """Appliziert Fallback-Sollwerte bei CMI-Ausfall oder fehlender Config."""
    setpoints = {
        "ww_soll_normal": 50.0,  # F:2 WW_ANF.1 — typischer Standardwert
        "ww_ist": None,  # Wird live vom Crawl befuellt
        "normal_soll": 24.0,  # F:1 FBHEIZ Raum-Soll Normal
        "absenk_soll": 21.0,  # F:1 FBHEIZ Raum-Soll Absenkung
    }
    app_state.setpoints = setpoints
    log.debug("setpoints_logger: fallback setpoints = %s", setpoints)
