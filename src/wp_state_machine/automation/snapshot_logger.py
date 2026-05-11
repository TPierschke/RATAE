"""
automation/snapshot_logger.py — Hartes Sampling aller Sensoren-Felder alle 5 min.

Schreibt nach Postgres-Tabelle telemetry. Ohne Postgres-Verbindung:
Warnung im Log, kein Fallback (ist mit Absicht — Postgres ist die einzige
Source-of-Truth fuer Pattern-Analyse).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from wp_state_machine.core.models import TelemetryRecord

log = logging.getLogger(__name__)

DEFAULT_INTERVAL = 300  # 5 Minuten


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
                # Snapshot timestamp = wall-clock now, not last sensor update.
                # Otherwise stale sensors produce gaps + duplicate timestamps in time-series.
                record.timestamp = datetime.now(timezone.utc)
                await app_state.postgres.insert_telemetry(record.model_dump())
            else:
                log.warning("snapshot_logger: Postgres nicht verbunden, Snapshot verloren")
        except Exception as exc:
            log.error("snapshot_logger Fehler: %s", exc)

        await asyncio.sleep(interval)
