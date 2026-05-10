"""Unit-Tests fuer core/models.py."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from wp_state_machine.core.models import (
    Betriebsart,
    Sensoren,
    SetBetriebsartRequest,
    SetNormalsollRequest,
    SetAbsenksollRequest,
    TelemetryRecord,
    WPState,
    WP_STATES,
    WriteResult,
)


class TestBetriebsart:
    def test_all_values_valid(self):
        for i in range(1, 8):
            b = Betriebsart.from_int(i)
            assert b.value == i

    def test_standby_is_1(self):
        assert Betriebsart.STANDBY == 1

    def test_normal_is_3(self):
        assert Betriebsart.NORMAL == 3

    def test_abgesenkt_is_4(self):
        assert Betriebsart.ABGESENKT == 4

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            Betriebsart.from_int(0)

    def test_invalid_8_raises(self):
        with pytest.raises(ValueError):
            Betriebsart.from_int(8)


class TestWPState:
    def test_all_states_in_set(self):
        for state in [WPState.HEIZUNG, WPState.WARMWASSER, WPState.BEREIT, WPState.STANDBY, WPState.LEGIONELLENSCHUTZ, WPState.UNKNOWN]:
            assert state in WP_STATES


class TestSensoren:
    def test_empty_sensoren_ok(self):
        s = Sensoren()
        assert s.aussen is None
        assert s.verdichter is None

    def test_pumpe_hzkr_bool_on(self):
        """FBH-Pumpe ist seit v0.1.5 Zustand (an/aus), kein Prozent."""
        s = Sensoren(pumpe_hzkr=True)
        assert s.pumpe_hzkr is True

    def test_ladepumpe_bool_off(self):
        s = Sensoren(ladepumpe=False)
        assert s.ladepumpe is False

    def test_pumpen_default_none(self):
        s = Sensoren()
        assert s.pumpe_hzkr is None
        assert s.ladepumpe is None

    def test_derive_state_unknown_without_data(self):
        s = Sensoren()
        assert s.derive_state() == WPState.UNKNOWN

    def test_derive_state_standby(self):
        s = Sensoren(betriebsart=Betriebsart.STANDBY, verdichter=False)
        assert s.derive_state() == WPState.STANDBY

    def test_derive_state_heizung(self):
        s = Sensoren(verdichter=True, ventil_ww=False)
        assert s.derive_state() == WPState.HEIZUNG

    def test_derive_state_warmwasser(self):
        s = Sensoren(verdichter=True, ventil_ww=True)
        assert s.derive_state() == WPState.WARMWASSER

    def test_derive_state_legionellenschutz(self):
        s = Sensoren(verdichter=True, ventil_ww=True, heizstab_ww=True)
        assert s.derive_state() == WPState.LEGIONELLENSCHUTZ

    def test_derive_state_legionellenschutz_with_heizstab_ww_only(self):
        s = Sensoren(heizstab_ww=True)
        assert s.derive_state() == WPState.LEGIONELLENSCHUTZ

    def test_derive_state_warmwasser_without_heizstab(self):
        s = Sensoren(verdichter=True, ventil_ww=True, heizstab_ww=False)
        assert s.derive_state() == WPState.WARMWASSER

    def test_derive_state_bereit(self):
        s = Sensoren(verdichter=False, betriebsart=Betriebsart.NORMAL)
        assert s.derive_state() == WPState.BEREIT

    @pytest.mark.parametrize(
        ("sensor_values", "expected_state"),
        [
            ({"heizstab_ww": True}, WPState.LEGIONELLENSCHUTZ),
            ({"verdichter": True, "ventil_ww": True, "heizstab_ww": False}, WPState.WARMWASSER),
            ({"verdichter": False, "betriebsart": Betriebsart.NORMAL}, WPState.BEREIT),
        ],
    )
    def test_derive_state_required_priority_cases(self, sensor_values, expected_state):
        assert Sensoren(**sensor_values).derive_state() == expected_state

    def test_is_heizstab_active_false(self):
        s = Sensoren(heizstab_hz=False, heizstab_ww=False)
        assert s.is_heizstab_active() is False

    def test_is_heizstab_active_hz(self):
        s = Sensoren(heizstab_hz=True)
        assert s.is_heizstab_active() is True

    def test_is_heizstab_active_ww(self):
        s = Sensoren(heizstab_ww=True)
        assert s.is_heizstab_active() is True

    def test_is_verdichter_active(self):
        s = Sensoren(verdichter=True)
        assert s.is_verdichter_active() is True

    def test_timestamp_present(self):
        s = Sensoren()
        assert s.timestamp is not None

    def test_source_field(self):
        s = Sensoren(source="web_scraper")
        assert s.source == "web_scraper"


class TestTelemetryRecord:
    def test_from_sensoren(self):
        s = Sensoren(vorlauf=35.5, aussen=5.2, verdichter=True, ventil_ww=False)
        tr = TelemetryRecord.from_sensoren(s, WPState.HEIZUNG)
        assert tr.vorlauf == 35.5
        assert tr.aussen == 5.2
        assert tr.verdichter is True
        assert tr.wp_state == WPState.HEIZUNG

    def test_from_sensoren_with_betriebsart(self):
        s = Sensoren(betriebsart=Betriebsart.NORMAL, verdichter=False)
        tr = TelemetryRecord.from_sensoren(s, WPState.BEREIT)
        assert tr.betriebsart == 3

    def test_from_sensoren_none_betriebsart(self):
        s = Sensoren()
        tr = TelemetryRecord.from_sensoren(s, WPState.UNKNOWN)
        assert tr.betriebsart is None


class TestSetBetriebsartRequest:
    @pytest.mark.parametrize("v", [1, 2, 3, 4, 5, 6, 7])
    def test_valid(self, v: int):
        req = SetBetriebsartRequest(betriebsart=v)
        assert req.betriebsart == v

    def test_zero_invalid(self):
        with pytest.raises(ValidationError):
            SetBetriebsartRequest(betriebsart=0)

    def test_eight_invalid(self):
        with pytest.raises(ValidationError):
            SetBetriebsartRequest(betriebsart=8)


class TestSetNormalsollRequest:
    def test_valid_range(self):
        req = SetNormalsollRequest(temp=21.0)
        assert req.temp == 21.0

    def test_boundary_low(self):
        req = SetNormalsollRequest(temp=10.0)
        assert req.temp == 10.0

    def test_boundary_high(self):
        req = SetNormalsollRequest(temp=30.0)
        assert req.temp == 30.0

    def test_too_low_invalid(self):
        with pytest.raises(ValidationError):
            SetNormalsollRequest(temp=9.9)

    def test_too_high_invalid(self):
        with pytest.raises(ValidationError):
            SetNormalsollRequest(temp=30.1)


class TestSetAbsenksollRequest:
    def test_valid(self):
        req = SetAbsenksollRequest(temp=18.0)
        assert req.temp == 18.0

    def test_boundary_low(self):
        req = SetAbsenksollRequest(temp=5.0)
        assert req.temp == 5.0

    def test_boundary_high(self):
        req = SetAbsenksollRequest(temp=25.0)
        assert req.temp == 25.0

    def test_too_low_invalid(self):
        with pytest.raises(ValidationError):
            SetAbsenksollRequest(temp=4.9)

    def test_too_high_invalid(self):
        with pytest.raises(ValidationError):
            SetAbsenksollRequest(temp=25.1)


class TestWriteResult:
    def test_success_result(self):
        r = WriteResult(success=True, dry_run=True, address="3E9001301C", value=3, reason="OK")
        assert r.success is True
        assert r.dry_run is True

    def test_failure_result(self):
        r = WriteResult(success=False, dry_run=True, address="3E80153125", reason="VERBOTEN")
        assert r.success is False
