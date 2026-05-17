"""
automation/setpoints_logger.py — background loop: crawls CMI function setpoints every 5 min.

Fetches setpoints from the CMI function-overview page (3E01581E):
  - ww_soll_normal: F:2 WW_ANF.1 setpoint (typically 49-50 deg C)
  - ww_ist: F:2 WW_ANF.1 actual temperature
  - normal_soll: F:1 FBHEIZ room setpoint normal
  - absenk_soll: F:1 FBHEIZ room setpoint setback
  - raum_ist: F:1 FBHEIZ T.Raum.IST (room sensor + dial offset)
  - vorlauf_soll: F:1 FBHEIZ calculated flow setpoint

Updates app_state.setpoints with live CMI values every 5 minutes and persists
them to ~/.config/wp-state-machine/setpoints.json (analog to theme.json) so the
values are immediately available again after a server restart.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

log = logging.getLogger(__name__)

DEFAULT_INTERVAL = 300  # 5 minutes
_HEIZSTAB_INTERVAL = 86400  # fetch operating hours once per day


async def setpoints_loop(app_state, config: Optional[Any] = None, interval: int = DEFAULT_INTERVAL) -> None:
    """
    Background loop. Updates app_state.setpoints with live CMI function setpoints.

    Crawls the function-overview page (3E01581E) and extracts setpoints. If the
    crawl fails, keeps the last known value or applies fallbacks.

    Args:
        app_state: AppState instance (must expose a setpoints dict)
        config: Config object (for CMI auth and URLs)
        interval: polling interval in seconds (default 300 = 5 min)
    """
    log.info("setpoints_logger started: function setpoints every %ds", interval)
    _last_heizstab: float = 0.0

    while True:
        try:
            # If a config is provided, crawl live from CMI; otherwise use fallbacks.
            if config:
                import aiohttp
                from wp_state_machine.ingest.web_scraper import parse_functions_overview

                auth = aiohttp.BasicAuth(*config.cmi_auth())
                timeout = aiohttp.ClientTimeout(total=config.cmi_timeout)

                try:
                    import time
                    from wp_state_machine.ingest.web_scraper import parse_heizstab_page
                    _fetch_heizstab = (time.monotonic() - _last_heizstab) >= _HEIZSTAB_INTERVAL
                    async with aiohttp.ClientSession(auth=auth, timeout=timeout) as session:
                        url = config.cmi_menupage_url("3E01581E")
                        async with session.get(url) as resp:
                            if resp.status == 200:
                                html = await resp.text()
                                functions = parse_functions_overview(html)
                                # Extract setpoints from the parsed functions.
                                setpoints = {}
                                for key in (
                                    "ww_soll_normal", "ww_ist",
                                    "normal_soll", "absenk_soll",
                                    "raum_ist", "vorlauf_soll",
                                ):
                                    if key in functions:
                                        setpoints[key] = functions[key]
                                # Legio target is hard-wired to 70 in UVR (F:9 WW_ANF.2).
                                # Store it as a constant so the frontend does not have to
                                # hardcode it.
                                setpoints.setdefault("ww_soll_legio", 70.0)

                                if setpoints:
                                    # Merge with existing keys so a partial crawl
                                    # (which can happen when the function overview
                                    # omits a value depending on operating state)
                                    # does not wipe previously known fields.
                                    merged = {**(app_state.setpoints or {}), **setpoints}
                                    await app_state.save_setpoints(merged)
                                    log.debug("setpoints_logger: live crawl + persist = %s", merged)
                                else:
                                    log.warning("setpoints_logger: no setpoints found in 3E01581E")
                            else:
                                log.warning("setpoints_logger: CMI HTTP %d", resp.status)

                        if _fetch_heizstab:
                            await asyncio.sleep(config.cmi_min_request_interval)
                            async with session.get(config.cmi_menupage_url("3E06580E")) as r:
                                hz_h = parse_heizstab_page(await r.text()) if r.status == 200 else None
                            await asyncio.sleep(config.cmi_min_request_interval)
                            async with session.get(config.cmi_menupage_url("3E07580E")) as r:
                                ww_h = parse_heizstab_page(await r.text()) if r.status == 200 else None
                            if hz_h is not None and hasattr(app_state, "sensoren") and app_state.sensoren:
                                app_state.sensoren.betr_std_heizstab_fb = hz_h
                            if ww_h is not None and hasattr(app_state, "sensoren") and app_state.sensoren:
                                app_state.sensoren.betr_std_heizstab_ww = ww_h
                            _last_heizstab = time.monotonic()
                            log.info("Heizstab-Stunden aktualisiert: HZ=%s h, WW=%s h", hz_h, ww_h)

                except Exception as exc:
                    log.warning("setpoints_logger: live crawl failed: %s, using fallbacks", exc)
                    # Fallback: apply default values.
                    _apply_fallback_setpoints(app_state)
            else:
                # No config -- use fallback.
                _apply_fallback_setpoints(app_state)

        except Exception as exc:
            log.error("setpoints_logger error: %s", exc)
            _apply_fallback_setpoints(app_state)

        await asyncio.sleep(interval)


def _apply_fallback_setpoints(app_state) -> None:
    """Apply fallback setpoints on CMI outage or missing config."""
    setpoints = {
        "ww_soll_normal": 50.0,  # F:2 WW_ANF.1 -- typical default value
        "ww_ist": None,  # filled in by the live crawl
        "normal_soll": 24.0,  # F:1 FBHEIZ room setpoint normal
        "absenk_soll": 21.0,  # F:1 FBHEIZ room setpoint setback
    }
    app_state.setpoints = setpoints
    log.debug("setpoints_logger: fallback setpoints = %s", setpoints)
