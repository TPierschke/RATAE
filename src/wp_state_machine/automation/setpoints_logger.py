"""
automation/setpoints_logger.py — Background loop: crawls CMI Funktions-Sollwerte alle 5 min.

Holt Sollwerte von der CMI:
  - F:2 WW_ANF.1 (normaler WW-Soll, typischerweise 50°C)
  - F:9 WW_ANF.2 (Legionellenschutz WW-Soll, typischerweise 70°C)
  - F:1 FBHEIZ Vorlauf-Soll-Berechnung (Basis + Steilheit)

Speichert in app_state.setpoints dict.

HINWEIS: MVP-Version nutzt aktuell statische Defaults (50, 70).
TODO: Live-Crawl aus CMI-Detail-Pages (F:2 und F:9 Hex-IDs ermitteln).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

log = logging.getLogger(__name__)

DEFAULT_INTERVAL = 300  # 5 Minuten


async def setpoints_loop(app_state, config: Optional[Any] = None, interval: int = DEFAULT_INTERVAL) -> None:
    """
    Hintergrund-Loop. Aktualisiert app_state.setpoints mit CMI-Funktions-Sollwerten.

    Aktuell: Statische Defaults (TODO: Live-Crawl implementieren).
      - ww_soll_normal: 50.0 (F:2 WW_ANF.1)
      - ww_soll_legio: 70.0 (F:9 WW_ANF.2)
      - vorlauf_soll_min: 20.0 (F:1 FBHEIZ Basis)

    Args:
        app_state: AppState-Instanz (muss setpoints dict haben)
        config: Config-Objekt (fuer CMI-Auth bei kuenftigem Live-Crawl)
        interval: Polling-Intervall in Sekunden (default 300 = 5 min)
    """
    log.info("setpoints_logger gestartet: Funktions-Sollwerte alle %ds", interval)

    while True:
        try:
            # TODO: Live-Crawl aus CMI implementieren
            # Falls gewuenscht: aiohttp + CMI-Detail-Pages der Funktionen
            # Fuer jetzt: statische Defaults
            setpoints = {
                "ww_soll_normal": 50.0,  # F:2 WW_ANF.1
                "ww_soll_legio": 70.0,   # F:9 WW_ANF.2
                "vorlauf_soll_min": 20.0,  # F:1 FBHEIZ Basis
            }
            app_state.setpoints = setpoints
            log.debug("setpoints_logger: cache aktualisiert = %s", setpoints)
        except Exception as exc:
            log.error("setpoints_logger Fehler: %s", exc)

        await asyncio.sleep(interval)
