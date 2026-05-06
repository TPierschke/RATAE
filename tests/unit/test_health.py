"""Unit-Tests fuer monitoring/health.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from wp_state_machine.core.models import Sensoren
from wp_state_machine.monitoring.health import (
    HEISSGAS_ANOMALIE_GRENZE,
    HEIZSTAB_WARNSCHWELLE,
    check_alarm_bit,
    check_data_freshness,
    check_heissgas_anomalie,
    check_heizstab_anomalie,
    run_all_checks,
)


class TestCheckAlarmBit:
    def test_no_alarm(self):
        s = Sensoren(alarm=False)
        assert check_alarm_bit(s) is None

    def test_alarm_active(self):
        s = Sensoren(alarm=True)
        result = check_alarm_bit(s)
        assert result is not None
        assert "Alarm" in result or "A5" in result

    def test_alarm_none(self):
        s = Sensoren()
        assert check_alarm_bit(s) is None


class TestCheckHeissgasAnomalie:
    def test_no_anomalie_verdichter_an(self):
        s = Sensoren(heissgas=45.0, verdichter=True)
        assert check_heissgas_anomalie(s) is None

    def test_anomalie_heissgas_hoch_verdichter_aus(self):
        s = Sensoren(heissgas=40.0, verdichter=False)
        result = check_heissgas_anomalie(s)
        assert result is not None
        assert "Heissgas" in result

    def test_no_anomalie_heissgas_niedrig_verdichter_aus(self):
        s = Sensoren(heissgas=20.0, verdichter=False)
        assert check_heissgas_anomalie(s) is None

    def test_boundary_exact_grenze(self):
        """Exakt an der Grenze: kein Alarm (> nicht >=)."""
        s = Sensoren(heissgas=HEISSGAS_ANOMALIE_GRENZE, verdichter=False)
        assert check_heissgas_anomalie(s) is None

    def test_above_grenze_triggers(self):
        s = Sensoren(heissgas=HEISSGAS_ANOMALIE_GRENZE + 0.1, verdichter=False)
        assert check_heissgas_anomalie(s) is not None

    def test_missing_heissgas_no_anomalie(self):
        s = Sensoren(verdichter=False)
        assert check_heissgas_anomalie(s) is None

    def test_missing_verdichter_no_anomalie(self):
        s = Sensoren(heissgas=50.0)
        assert check_heissgas_anomalie(s) is None


class TestCheckHeizstabAnomalie:
    def test_heizstab_ww_normal_temp_ok(self):
        s = Sensoren(heizstab_ww=True, warmwasser=45.0)
        assert check_heizstab_anomalie(s) is None

    def test_heizstab_ww_high_temp_anomalie(self):
        s = Sensoren(heizstab_ww=True, warmwasser=55.0)
        result = check_heizstab_anomalie(s)
        assert result is not None
        assert "Heizstab" in result

    def test_heizstab_hz_high_vorlauf_anomalie(self):
        s = Sensoren(heizstab_hz=True, vorlauf=55.0)
        result = check_heizstab_anomalie(s)
        assert result is not None

    def test_heizstab_aus_no_anomalie(self):
        s = Sensoren(heizstab_ww=False, heizstab_hz=False)
        assert check_heizstab_anomalie(s) is None

    def test_no_heizstab_data_no_anomalie(self):
        s = Sensoren()
        assert check_heizstab_anomalie(s) is None


class TestCheckDataFreshness:
    def test_fresh_data_ok(self):
        now = datetime.now(timezone.utc)
        assert check_data_freshness(now, max_age_seconds=120) is None

    def test_old_data_warning(self):
        old = datetime.now(timezone.utc) - timedelta(seconds=200)
        result = check_data_freshness(old, max_age_seconds=120)
        assert result is not None
        assert "veraltet" in result.lower() or "alt" in result.lower() or "200" in result

    def test_no_data_warning(self):
        result = check_data_freshness(None)
        assert result is not None

    def test_exact_boundary_fresh(self):
        ts = datetime.now(timezone.utc) - timedelta(seconds=119)
        assert check_data_freshness(ts, max_age_seconds=120) is None


class TestRunAllChecks:
    def test_all_ok_returns_empty(self):
        s = Sensoren(
            alarm=False,
            heissgas=30.0,
            verdichter=True,
            heizstab_ww=False,
            heizstab_hz=False,
        )
        now = datetime.now(timezone.utc)
        warnings = run_all_checks(s, last_update=now)
        assert warnings == []

    def test_alarm_detected(self):
        s = Sensoren(alarm=True)
        now = datetime.now(timezone.utc)
        warnings = run_all_checks(s, last_update=now)
        assert len(warnings) >= 1
        assert any("Alarm" in w or "A5" in w for w in warnings)

    def test_stale_data_detected(self):
        s = Sensoren(alarm=False)
        old = datetime.now(timezone.utc) - timedelta(seconds=300)
        warnings = run_all_checks(s, last_update=old)
        assert any("veraltet" in w.lower() or "Telemetrie" in w for w in warnings)

    def test_multiple_anomalies_all_reported(self):
        s = Sensoren(
            alarm=True,
            heissgas=45.0,
            verdichter=False,
        )
        warnings = run_all_checks(s, last_update=None)
        assert len(warnings) >= 2  # mindestens Alarm + fehlende Daten

    def test_returns_list(self):
        s = Sensoren()
        result = run_all_checks(s, last_update=None)
        assert isinstance(result, list)
