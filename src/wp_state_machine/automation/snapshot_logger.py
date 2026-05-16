"""
automation/snapshot_logger.py — Hartes Sampling aller Sensoren-Felder alle 5 min.

Schreibt nach Postgres-Tabelle telemetry. Ohne Postgres-Verbindung:
Warnung im Log, kein Fallback (ist mit Absicht — Postgres ist die einzige
Source-of-Truth fuer Pattern-Analyse).

ETA-Forecast: waehrend WP_STATE=BEREIT werden ww_eta_min und heat_eta_min
gefuellt. Spaeter laesst sich via SELECT mit LEAD-Join messen wie nahe der
Forecast an der Realitaet war.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from wp_state_machine.core.models import TelemetryRecord

log = logging.getLogger(__name__)

DEFAULT_INTERVAL = 300  # 5 Minuten

# Cooldown-Default-Raten (deg/min, positive = cooling rate)
WW_COOLDOWN_RATE   = 0.02   # ~1.2 K/h, typischer WW-Speicher-Verlust
HEAT_COOLDOWN_RATE = 0.04   # ~2.4 K/h, typischer 200L Puffer-Verlust
WW_DIFF_EIN        = -4.0   # F:2 WW_ANF.1 — EIN wenn WW < ww_soll - 4
HEAT_DIFF_EIN      = -3.0   # F:8 HZ_ANF  — EIN wenn TPuffer.o < vorlauf_soll - 3


def _compute_etas(sensoren, setpoints: dict) -> tuple[float | None, float | None]:
    """Forecast-Minuten bis WW/Heizung wieder Bedarf melden. Nur in BEREIT-State.
    Heizung-ETA nur wenn Betriebsart != Standby (=1).
    """
    state = getattr(sensoren, "wp_state", None)
    if state != "BEREIT":
        # derive again locally if sensoren doesn't carry wp_state directly
        try:
            state = sensoren.derive_state()
        except Exception:
            state = None
    if state != "BEREIT":
        return None, None

    ww_eta = None
    ww = getattr(sensoren, "warmwasser", None)
    ww_soll = setpoints.get("ww_soll_normal") if setpoints else None
    if ww is not None and ww_soll is not None:
        diff = ww - (ww_soll + WW_DIFF_EIN)  # WW above EIN-threshold
        if diff > 0.1:
            ww_eta = round(diff / WW_COOLDOWN_RATE, 1)

    heat_eta = None
    betr = getattr(sensoren, "betriebsart", None)
    if betr is not None and int(betr) != 1:  # not Standby
        vl = getattr(sensoren, "vorlauf", None)
        vl_soll = setpoints.get("vorlauf_soll") if setpoints else None
        if vl_soll is None:
            vl_soll = getattr(sensoren, "vorlauf_soll", None)
        if vl is not None and vl_soll is not None:
            diff = vl - (vl_soll + HEAT_DIFF_EIN)
            if diff > 0.1:
                heat_eta = round(diff / HEAT_COOLDOWN_RATE, 1)

    return ww_eta, heat_eta


async def snapshot_loop(app_state, interval: int = DEFAULT_INTERVAL) -> None:
    """
    Hintergrund-Loop. Schreibt alle <interval>s den kompletten Sensoren-State
    in die Postgres-`telemetry`-Tabelle.
    Ohne Postgres-Connection: Warnung pro Tick, kein Insert.
    """
    log.info("snapshot_logger gestartet: Postgres telemetry alle %ds", interval)

    while True:
        try:
            if app_state.postgres and app_state.postgres.is_connected:
                # Pass setpoints dict so CMI function setpoints are stored alongside
                # sensor readings.  None/missing keys become NULL — no insert error.
                setpoints = getattr(app_state, "setpoints", None) or {}
                record = TelemetryRecord.from_sensoren(
                    app_state.sensoren,
                    app_state.wp_state,
                    setpoints=setpoints,
                )
                # Forecast-ETAs (BEREIT-State only).
                ww_eta, heat_eta = _compute_etas(app_state.sensoren, setpoints)
                record.ww_eta_min = ww_eta
                record.heat_eta_min = heat_eta
                # Snapshot timestamp = wall-clock now, not last sensor update.
                # Otherwise stale sensors produce gaps + duplicate timestamps in time-series.
                record.timestamp = datetime.now(timezone.utc)
                await app_state.postgres.insert_telemetry(record.model_dump())
            else:
                log.warning("snapshot_logger: Postgres nicht verbunden, Snapshot verloren")
        except Exception as exc:
            log.error("snapshot_logger Fehler: %s", exc)

        await asyncio.sleep(interval)
