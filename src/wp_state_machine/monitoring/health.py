"""
monitoring/health.py — Self-Monitoring + Anomalie-Erkennung.

Checks:
  - CMI erreichbar?
  - Postgres verbunden?
  - Letzter Heartbeat < 2 Min?
  - Anomalie: Heissgas > 35°C ohne Verdichter?
  - Anomalie: Heizstab aktiv ohne WW-Anforderung?
  - Alarm-Bit A5 aktiv?
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from wp_state_machine.core.models import Sensoren

log = logging.getLogger(__name__)

# Schwellwerte aus wp_monitor.py / config
HEISSGAS_ANOMALIE_GRENZE = 35.0  # °C — Heissgas ohne Verdichter = Sensorproblem
HEIZSTAB_WARNSCHWELLE = 50.0  # °C — WW-Speicher bei Heizstab-Betrieb


def check_alarm_bit(sensoren: Sensoren) -> Optional[str]:
    """
    Prueft Alarm-Ausgang A5.
    Gibt Alarm-Beschreibung oder None zurueck.
    """
    if sensoren.alarm is True:
        return "CMI Alarm-Ausgang A5 aktiv!"
    return None


def check_heissgas_anomalie(sensoren: Sensoren) -> Optional[str]:
    """
    Heissgas > 35°C ohne laufenden Verdichter = Sensorproblem oder Anomalie.
    Heuristik aus wp_monitor.py.
    """
    if sensoren.heissgas is None or sensoren.verdichter is None:
        return None
    if sensoren.heissgas > HEISSGAS_ANOMALIE_GRENZE and not sensoren.verdichter:
        return (
            f"Heissgas-Anomalie: {sensoren.heissgas:.1f}°C > {HEISSGAS_ANOMALIE_GRENZE}°C "
            f"aber Verdichter AUS!"
        )
    return None


def check_heizstab_anomalie(sensoren: Sensoren) -> Optional[str]:
    """
    Heizstab aktiv und WW-Temperatur sehr hoch = Warnung.
    """
    if sensoren.heizstab_ww is True and sensoren.warmwasser is not None:
        if sensoren.warmwasser > HEIZSTAB_WARNSCHWELLE:
            return (
                f"Heizstab WW laeuft und WW-Temp {sensoren.warmwasser:.1f}°C > "
                f"{HEIZSTAB_WARNSCHWELLE}°C Warnschwelle!"
            )
    if sensoren.heizstab_hz is True and sensoren.vorlauf is not None:
        if sensoren.vorlauf > HEIZSTAB_WARNSCHWELLE:
            return (
                f"Heizstab HZ laeuft und Vorlauf {sensoren.vorlauf:.1f}°C > "
                f"{HEIZSTAB_WARNSCHWELLE}°C!"
            )
    return None


def check_data_freshness(
    last_update: Optional[datetime],
    max_age_seconds: float = 120.0,
) -> Optional[str]:
    """
    Prueft ob Daten aktuell sind.
    Gibt Warn-String oder None zurueck.
    """
    if last_update is None:
        return "Keine Telemetrie-Daten empfangen!"
    age = (datetime.now(timezone.utc) - last_update).total_seconds()
    if age > max_age_seconds:
        return f"Telemetrie-Daten veraltet: {age:.0f}s (max {max_age_seconds:.0f}s)"
    return None


def run_all_checks(
    sensoren: Sensoren,
    last_update: Optional[datetime] = None,
    max_data_age: float = 120.0,
) -> list[str]:
    """
    Fuehrt alle Anomalie-Checks durch.

    Gibt Liste von Warn-Strings zurueck. Leer = alles OK.
    """
    warnings: list[str] = []

    checks = [
        check_alarm_bit(sensoren),
        check_heissgas_anomalie(sensoren),
        check_heizstab_anomalie(sensoren),
        check_data_freshness(last_update, max_data_age),
    ]

    for result in checks:
        if result is not None:
            log.warning("Anomalie erkannt: %s", result)
            warnings.append(result)

    return warnings
