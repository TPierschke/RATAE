"""Unit tests for setpoint columns in telemetry snapshot pipeline.

Covers:
- Migration idempotency (SQL-level, via mocked apply_schema)
- TelemetryRecord.from_sensoren includes setpoints values
- NULL setpoints produce no insert error
- _TELEMETRY_COLUMNS contains all six new setpoint columns
- snapshot_loop passes setpoints to insert_telemetry
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from wp_state_machine.core.models import Sensoren, TelemetryRecord
from wp_state_machine.storage.postgres import PostgresStore, _TELEMETRY_COLUMNS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_connected_store() -> tuple[PostgresStore, MagicMock]:
    """Return a PostgresStore with a mocked asyncpg pool."""
    store = PostgresStore("postgresql://test:test@localhost/test")
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value=None)
    mock_conn.fetchrow = AsyncMock(return_value=None)

    @asynccontextmanager
    async def fake_acquire():
        yield mock_conn

    mock_pool = MagicMock()
    mock_pool.acquire = fake_acquire
    mock_pool.close = AsyncMock()

    store._pool = mock_pool
    store._connected = True
    return store, mock_conn


def _minimal_sensoren() -> Sensoren:
    return Sensoren(vorlauf=45.0, aussen=8.0, warmwasser=51.0)


# ---------------------------------------------------------------------------
# TelemetryRecord — setpoint propagation
# ---------------------------------------------------------------------------


class TestTelemetryRecordSetpoints:
    def test_from_sensoren_includes_all_six_setpoints(self):
        """All six setpoint fields are written when setpoints dict is complete."""
        s = _minimal_sensoren()
        sp = {
            "normal_soll": 22.5,
            "absenk_soll": 19.0,
            "raum_ist": 21.3,
            "ww_soll_normal": 50.0,
            "ww_soll_legio": 70.0,
            "ww_ist": 48.7,
        }
        rec = TelemetryRecord.from_sensoren(s, "HEIZUNG", setpoints=sp)
        assert rec.normal_soll == 22.5
        assert rec.absenk_soll == 19.0
        assert rec.raum_ist == 21.3
        assert rec.ww_soll_normal == 50.0
        assert rec.ww_soll_legio == 70.0
        assert rec.ww_ist == 48.7

    def test_from_sensoren_null_setpoints_no_error(self):
        """None/missing setpoints are stored as None — no exception."""
        s = _minimal_sensoren()
        rec = TelemetryRecord.from_sensoren(s, "BEREIT", setpoints=None)
        assert rec.normal_soll is None
        assert rec.absenk_soll is None
        assert rec.raum_ist is None
        assert rec.ww_soll_normal is None
        assert rec.ww_soll_legio is None
        assert rec.ww_ist is None

    def test_from_sensoren_empty_dict_setpoints(self):
        """Empty setpoints dict → all six fields are None."""
        s = _minimal_sensoren()
        rec = TelemetryRecord.from_sensoren(s, "STANDBY", setpoints={})
        assert rec.normal_soll is None
        assert rec.ww_ist is None

    def test_from_sensoren_partial_setpoints(self):
        """Partial setpoints dict: present keys set, absent keys are None."""
        s = _minimal_sensoren()
        sp = {"normal_soll": 23.0, "ww_soll_legio": 70.0}
        rec = TelemetryRecord.from_sensoren(s, "WARMWASSER", setpoints=sp)
        assert rec.normal_soll == 23.0
        assert rec.ww_soll_legio == 70.0
        assert rec.absenk_soll is None
        assert rec.raum_ist is None
        assert rec.ww_soll_normal is None
        assert rec.ww_ist is None

    def test_vorlauf_soll_prefers_setpoints_over_sensor(self):
        """vorlauf_soll from setpoints wins over the sensor value."""
        s = Sensoren(vorlauf=45.0, vorlauf_soll=35.0)
        sp = {"vorlauf_soll": 38.0}
        rec = TelemetryRecord.from_sensoren(s, "HEIZUNG", setpoints=sp)
        assert rec.vorlauf_soll == 38.0

    def test_vorlauf_soll_falls_back_to_sensor_when_missing_from_setpoints(self):
        """vorlauf_soll falls back to Sensoren.vorlauf_soll when not in setpoints."""
        s = Sensoren(vorlauf=45.0, vorlauf_soll=35.0)
        rec = TelemetryRecord.from_sensoren(s, "HEIZUNG", setpoints={})
        assert rec.vorlauf_soll == 35.0

    def test_model_dump_contains_setpoint_keys(self):
        """model_dump() includes all six setpoint keys (required for DB insert)."""
        s = _minimal_sensoren()
        sp = {"normal_soll": 22.0, "absenk_soll": 18.0, "ww_soll_legio": 70.0}
        rec = TelemetryRecord.from_sensoren(s, "HEIZUNG", setpoints=sp)
        d = rec.model_dump()
        for key in ("normal_soll", "absenk_soll", "raum_ist", "ww_soll_normal", "ww_soll_legio", "ww_ist"):
            assert key in d, f"model_dump() missing key: {key}"


# ---------------------------------------------------------------------------
# _TELEMETRY_COLUMNS whitelist
# ---------------------------------------------------------------------------


class TestTelemetryColumnsWhitelist:
    def test_all_six_setpoint_columns_in_whitelist(self):
        """_TELEMETRY_COLUMNS must contain all six new setpoint DB columns."""
        col_names = {col for col, _ in _TELEMETRY_COLUMNS}
        for expected in ("normal_soll", "absenk_soll", "raum_ist", "ww_soll_normal", "ww_soll_legio", "ww_ist"):
            assert expected in col_names, f"_TELEMETRY_COLUMNS missing: {expected}"

    def test_column_keys_match_record_dict_keys(self):
        """Every (col, key) pair in _TELEMETRY_COLUMNS must exist in a full TelemetryRecord dump."""
        sp = {
            "normal_soll": 22.0, "absenk_soll": 19.0, "raum_ist": 21.0,
            "ww_soll_normal": 50.0, "ww_soll_legio": 70.0, "ww_ist": 48.0,
        }
        rec = TelemetryRecord.from_sensoren(_minimal_sensoren(), "HEIZUNG", setpoints=sp)
        dump = rec.model_dump()
        for col, key in _TELEMETRY_COLUMNS:
            assert key in dump or key == "timestamp", (
                f"Record key '{key}' for DB column '{col}' not found in model_dump()"
            )


# ---------------------------------------------------------------------------
# PostgresStore — insert with setpoints
# ---------------------------------------------------------------------------


class TestPostgresInsertWithSetpoints:
    @pytest.mark.asyncio
    async def test_insert_telemetry_with_setpoints_calls_execute(self):
        """insert_telemetry forwards setpoint values to the DB execute call."""
        store, mock_conn = _make_connected_store()
        sp = {
            "normal_soll": 22.0, "absenk_soll": 19.0, "raum_ist": 21.0,
            "ww_soll_normal": 50.0, "ww_soll_legio": 70.0, "ww_ist": 48.0,
        }
        rec = TelemetryRecord.from_sensoren(_minimal_sensoren(), "HEIZUNG", setpoints=sp)
        result = await store.insert_telemetry(rec.model_dump())
        assert result is True
        mock_conn.execute.assert_called_once()
        # Verify setpoint values appear in the positional args to execute().
        args = mock_conn.execute.call_args[0]
        assert 22.0 in args  # normal_soll
        assert 70.0 in args  # ww_soll_legio

    @pytest.mark.asyncio
    async def test_insert_telemetry_with_null_setpoints_no_error(self):
        """insert_telemetry succeeds when all setpoint fields are None (NULL)."""
        store, mock_conn = _make_connected_store()
        rec = TelemetryRecord.from_sensoren(_minimal_sensoren(), "BEREIT", setpoints=None)
        result = await store.insert_telemetry(rec.model_dump())
        assert result is True
        mock_conn.execute.assert_called_once()


# ---------------------------------------------------------------------------
# Migration idempotency (SQL logic, not DB)
# ---------------------------------------------------------------------------


class TestMigrationIdempotency:
    """Verify that apply_schema handles repeated application without errors.

    We mock the DB execute to be a no-op; the test confirms that calling
    apply_schema twice succeeds and does not raise exceptions.
    """

    @pytest.mark.asyncio
    async def test_apply_schema_idempotent_via_mock(self):
        """apply_schema can be called repeatedly without failure."""
        store, mock_conn = _make_connected_store()
        idempotent_sql = (
            "ALTER TABLE public.telemetry\n"
            "    ADD COLUMN IF NOT EXISTS normal_soll REAL,\n"
            "    ADD COLUMN IF NOT EXISTS absenk_soll REAL,\n"
            "    ADD COLUMN IF NOT EXISTS raum_ist REAL,\n"
            "    ADD COLUMN IF NOT EXISTS ww_soll_normal REAL,\n"
            "    ADD COLUMN IF NOT EXISTS ww_soll_legio REAL,\n"
            "    ADD COLUMN IF NOT EXISTS ww_ist REAL;\n"
        )
        # First application
        result1 = await store.apply_schema(idempotent_sql)
        # Second application — same SQL, must not raise
        result2 = await store.apply_schema(idempotent_sql)
        assert result1 is True
        assert result2 is True
        assert mock_conn.execute.call_count == 2


# ---------------------------------------------------------------------------
# snapshot_loop integration
# ---------------------------------------------------------------------------


class TestSnapshotLoopSetpoints:
    @pytest.mark.asyncio
    async def test_snapshot_loop_passes_setpoints_to_insert(self):
        """snapshot_loop must include setpoints from app_state in the DB insert."""
        store, mock_conn = _make_connected_store()

        class FakeAppState:
            sensoren = _minimal_sensoren()
            wp_state = "HEIZUNG"
            postgres = store
            setpoints = {
                "normal_soll": 22.5,
                "absenk_soll": 19.0,
                "raum_ist": 21.0,
                "ww_soll_normal": 50.0,
                "ww_soll_legio": 70.0,
                "ww_ist": 48.5,
            }

        from wp_state_machine.automation.snapshot_logger import snapshot_loop

        task = asyncio.create_task(snapshot_loop(FakeAppState(), interval=0.05))
        try:
            await asyncio.sleep(0.12)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert mock_conn.execute.call_count >= 1
        args = mock_conn.execute.call_args[0]
        # Setpoint values must appear in the INSERT positional args
        assert 22.5 in args, "normal_soll not in insert args"
        assert 70.0 in args, "ww_soll_legio not in insert args"

    @pytest.mark.asyncio
    async def test_snapshot_loop_null_setpoints_no_error(self):
        """snapshot_loop succeeds when setpoints is empty (NULL for all six columns)."""
        store, mock_conn = _make_connected_store()

        class FakeAppState:
            sensoren = _minimal_sensoren()
            wp_state = "BEREIT"
            postgres = store
            setpoints: dict = {}

        from wp_state_machine.automation.snapshot_logger import snapshot_loop

        task = asyncio.create_task(snapshot_loop(FakeAppState(), interval=0.05))
        try:
            await asyncio.sleep(0.12)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert mock_conn.execute.call_count >= 1

    @pytest.mark.asyncio
    async def test_snapshot_loop_missing_setpoints_attr_no_error(self):
        """snapshot_loop handles app_state without setpoints attribute gracefully."""
        store, mock_conn = _make_connected_store()

        class FakeAppState:
            sensoren = _minimal_sensoren()
            wp_state = "STANDBY"
            postgres = store
            # no setpoints attribute

        from wp_state_machine.automation.snapshot_logger import snapshot_loop

        task = asyncio.create_task(snapshot_loop(FakeAppState(), interval=0.05))
        try:
            await asyncio.sleep(0.12)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert mock_conn.execute.call_count >= 1
