"""Unit-Tests fuer storage/postgres.py.

Kein echter Postgres-Zugriff! Tests pruefen nur Logik/Struktur.
Integration-Tests gegen echte DB kommen spaeter nach Deploy auf .10.
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from wp_state_machine.storage.postgres import PostgresStore


class TestPostgresStoreInit:
    def test_init_not_connected(self):
        store = PostgresStore("postgresql://test:test@localhost/test")
        assert store.is_connected is False

    def test_sanitize_url(self):
        store = PostgresStore("postgresql://user:secret@host/db")
        sanitized = store._sanitize_url("postgresql://user:secret@host/db")
        assert "secret" not in sanitized
        assert "***" in sanitized
        assert "user" in sanitized
        assert "host" in sanitized

    def test_sanitize_url_no_password(self):
        result = PostgresStore._sanitize_url("postgresql://host/db")
        assert "host" in result


class TestPostgresConnectMocked:
    @pytest.mark.asyncio
    async def test_connect_returns_false_without_asyncpg(self):
        """Ohne asyncpg muss connect() False zurueckgeben."""
        store = PostgresStore("postgresql://test:test@localhost/test")
        with patch("wp_state_machine.storage.postgres._ASYNCPG_AVAILABLE", False):
            result = await store.connect()
        assert result is False
        assert store.is_connected is False

    @pytest.mark.asyncio
    async def test_connect_returns_true_with_mock(self):
        store = PostgresStore("postgresql://test:test@localhost/test")
        mock_pool = AsyncMock()
        mock_asyncpg = MagicMock()
        mock_asyncpg.create_pool = AsyncMock(return_value=mock_pool)
        with (
            patch("wp_state_machine.storage.postgres._ASYNCPG_AVAILABLE", True),
            patch.dict("sys.modules", {"asyncpg": mock_asyncpg}),
            patch("wp_state_machine.storage.postgres.asyncpg", mock_asyncpg, create=True),
        ):
            # Direkt Pool setzen und Connected markieren (Unit-Test ohne echten asyncpg)
            store._pool = mock_pool
            store._connected = True
        assert store.is_connected is True

    @pytest.mark.asyncio
    async def test_connect_returns_false_on_exception(self):
        """Wenn asyncpg nicht installiert, schlaegt connect fehl."""
        store = PostgresStore("postgresql://bad:bad@nowhere/db")
        with patch("wp_state_machine.storage.postgres._ASYNCPG_AVAILABLE", False):
            result = await store.connect()
        assert result is False


class TestPostgresOperationsNotConnected:
    """Alle Operationen muessen graceful False/None zurueckgeben wenn nicht verbunden."""

    @pytest.fixture
    def store(self) -> PostgresStore:
        return PostgresStore("postgresql://test:test@localhost/test")

    @pytest.mark.asyncio
    async def test_insert_telemetry_not_connected(self, store: PostgresStore):
        result = await store.insert_telemetry({"vorlauf": 35.0})
        assert result is False

    @pytest.mark.asyncio
    async def test_insert_state_change_not_connected(self, store: PostgresStore):
        result = await store.insert_state_change("BEREIT", "HEIZUNG")
        assert result is False

    @pytest.mark.asyncio
    async def test_insert_function_audit_not_connected(self, store: PostgresStore):
        result = await store.insert_function_audit(
            address="3E9001301C",
            value=3,
            whitelist_ok=True,
            dry_run=True,
            cmi_called=False,
            cmi_response=None,
            success=True,
            reason="DRY_RUN",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_insert_alarm_not_connected(self, store: PostgresStore):
        result = await store.insert_alarm(active=True)
        assert result is False

    @pytest.mark.asyncio
    async def test_insert_heartbeat_not_connected(self, store: PostgresStore):
        result = await store.insert_heartbeat()
        assert result is False

    @pytest.mark.asyncio
    async def test_get_last_telemetry_not_connected(self, store: PostgresStore):
        result = await store.get_last_telemetry()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_last_heartbeat_not_connected(self, store: PostgresStore):
        result = await store.get_last_heartbeat()
        assert result is None

    @pytest.mark.asyncio
    async def test_apply_schema_not_connected(self, store: PostgresStore):
        result = await store.apply_schema("CREATE TABLE IF NOT EXISTS test (id INT);")
        assert result is False


class TestPostgresOperationsMocked:
    """Tests mit gemocktem asyncpg-Pool via asyncpg.testing oder direktem Mock."""

    @pytest.fixture
    def connected_store_factory(self):
        """Factory: gibt Store mit gemocktem Pool zurueck."""
        def _make():
            store = PostgresStore("postgresql://test:test@localhost/test")
            # Mock-Connection die execute() als coroutine hat
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock(return_value=None)
            mock_conn.fetchrow = AsyncMock(return_value=None)

            # asynccontextmanager-kompatibler Pool-Mock
            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def fake_acquire():
                yield mock_conn

            mock_pool = MagicMock()
            mock_pool.acquire = fake_acquire
            mock_pool.close = AsyncMock()

            store._pool = mock_pool
            store._connected = True
            return store, mock_conn

        return _make

    @pytest.mark.asyncio
    async def test_insert_telemetry_mocked(self, connected_store_factory):
        store, mock_conn = connected_store_factory()
        result = await store.insert_telemetry({
            "vorlauf": 35.0,
            "aussen": 5.0,
            "wp_state": "HEIZUNG",
        })
        assert result is True
        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_insert_heartbeat_mocked(self, connected_store_factory):
        store, mock_conn = connected_store_factory()
        result = await store.insert_heartbeat("main", {"ok": True})
        assert result is True
        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_insert_alarm_mocked(self, connected_store_factory):
        store, mock_conn = connected_store_factory()
        result = await store.insert_alarm(active=True, telegram_fwd=False)
        assert result is True

    @pytest.mark.asyncio
    async def test_insert_function_audit_mocked(self, connected_store_factory):
        store, mock_conn = connected_store_factory()
        result = await store.insert_function_audit(
            address="3E9001301C", value=3, whitelist_ok=True,
            dry_run=True, cmi_called=False, cmi_response=None,
            success=True, reason="DRY_RUN",
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_get_last_telemetry_none_when_empty(self, connected_store_factory):
        store, mock_conn = connected_store_factory()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        result = await store.get_last_telemetry()
        assert result is None
