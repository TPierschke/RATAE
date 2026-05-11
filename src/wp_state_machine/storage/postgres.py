"""
storage/postgres.py — asyncpg-basierter Postgres-Zugriff.

Alle DB-Operationen asynchron. Schema in schema.sql.
Verbindungs-URL aus Config.postgres_url.

Phase 1: Schema-Migration via einfaches SQL-Apply (kein Alembic).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger(__name__)

try:
    import asyncpg  # type: ignore[import]

    _ASYNCPG_AVAILABLE = True
except ImportError:
    _ASYNCPG_AVAILABLE = False
    log.warning("asyncpg nicht installiert — Postgres-Zugriff deaktiviert")


# (db_column_name, record_dict_key) — order MUST match telemetry table in schema.sql.
# Column names are a hard-coded whitelist; record keys come from TelemetryRecord.model_dump().
_TELEMETRY_COLUMNS: tuple[tuple[str, str], ...] = (
    ("ts", "timestamp"),
    ("vorlauf", "vorlauf"),
    ("ruecklauf", "ruecklauf"),
    ("warmwasser", "warmwasser"),
    ("aussen", "aussen"),
    ("heissgas", "heissgas"),
    ("fluessigkeit", "fluessigkeit"),
    ("saugleitung", "saugleitung"),
    ("phasenwaechter", "phasenwaechter"),
    ("verdichter_freigabe", "verdichter_freigabe"),
    ("nd_schalter1", "nd_schalter1"),
    ("hd_schalter", "hd_schalter"),
    ("nd_schalter2", "nd_schalter2"),
    ("pumpe_hzkr", "pumpe_hzkr"),
    ("ladepumpe", "ladepumpe"),
    ("verdichter", "verdichter"),
    ("mvr0407_fl1", "mvr0407_fl1"),
    ("alarm", "alarm"),
    ("mvr0407_nach2", "mvr0407_nach2"),
    ("ventil_ww", "ventil_ww"),
    ("heizstab_hz", "heizstab_hz"),
    ("heizstab_ww", "heizstab_ww"),
    ("pumpe_zirku", "pumpe_zirku"),
    ("meldung_heizung", "meldung_heizung"),
    ("betriebsart", "betriebsart"),
    ("wp_state", "wp_state"),
    ("betr_std_verdichter", "betr_std_verdichter"),
    ("schaltungen_verdichter", "schaltungen_verdichter"),
    ("betr_std_heizstab_fb", "betr_std_heizstab_fb"),
    ("betr_std_heizstab_ww", "betr_std_heizstab_ww"),
    ("message_fb", "message_fb"),
    ("message_ww", "message_ww"),
    ("vorlauf_soll", "vorlauf_soll"),
    ("traum1", "traum1"),
    ("normal_soll", "normal_soll"),
    ("absenk_soll", "absenk_soll"),
    ("raum_ist", "raum_ist"),
    ("ww_soll_normal", "ww_soll_normal"),
    ("ww_soll_legio", "ww_soll_legio"),
    ("ww_ist", "ww_ist"),
)

_TELEMETRY_INSERT_SQL = (
    "INSERT INTO telemetry ("
    + ", ".join(col for col, _ in _TELEMETRY_COLUMNS)
    + ") VALUES ("
    + ", ".join(f"${i}" for i in range(1, len(_TELEMETRY_COLUMNS) + 1))
    + ")"
)


class PostgresStore:
    """
    Async Postgres-Store fuer WP State Machine.

    Verwendung:
        store = PostgresStore(url="postgresql://...")
        await store.connect()
        await store.insert_telemetry(record)
        await store.close()
    """

    def __init__(self, url: str) -> None:
        self.url = url
        self._pool: Any = None
        self._connected = False

    async def connect(self) -> bool:
        """Verbindet mit Postgres. Gibt True bei Erfolg."""
        if not _ASYNCPG_AVAILABLE:
            log.error("asyncpg nicht verfuegbar — Postgres deaktiviert")
            return False
        try:
            self._pool = await asyncpg.create_pool(self.url, min_size=1, max_size=5)
            self._connected = True
            log.info("PostgresStore verbunden mit %s", self._sanitize_url(self.url))
            return True
        except Exception as exc:
            log.error("Postgres-Verbindungsfehler: %s", exc)
            self._connected = False
            return False

    async def close(self) -> None:
        """Schliesst den Connection-Pool."""
        if self._pool:
            await self._pool.close()
            self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected and self._pool is not None

    async def apply_schema(self, schema_sql: str) -> bool:
        """Fuehrt Schema-SQL aus (idempotent via IF NOT EXISTS)."""
        if not self.is_connected:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(schema_sql)
            log.info("Schema angewendet")
            return True
        except Exception as exc:
            log.error("Schema-Apply-Fehler: %s", exc)
            return False

    # ---------------------------------------------------------------------------
    # Telemetrie
    # ---------------------------------------------------------------------------

    async def insert_telemetry(self, record: dict[str, Any]) -> bool:
        """Schreibt einen Telemetrie-Datensatz."""
        if not self.is_connected:
            log.debug("insert_telemetry: nicht verbunden, skip")
            return False
        try:
            values = [
                record.get(key) if key != "timestamp"
                else record.get(key) or datetime.now(timezone.utc)
                for _, key in _TELEMETRY_COLUMNS
            ]
            async with self._pool.acquire() as conn:
                await conn.execute(_TELEMETRY_INSERT_SQL, *values)
            return True
        except Exception as exc:
            log.error("insert_telemetry Fehler: %s", exc)
            return False

    # ---------------------------------------------------------------------------
    # State History
    # ---------------------------------------------------------------------------

    async def insert_state_change(
        self,
        old_state: Optional[str],
        new_state: str,
        betriebsart: Optional[int] = None,
        vorlauf: Optional[float] = None,
        aussen: Optional[float] = None,
        details: Optional[dict] = None,
    ) -> bool:
        if not self.is_connected:
            return False
        try:
            import json

            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO state_history (old_state, new_state, betriebsart, vorlauf, aussen, details)
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    old_state,
                    new_state,
                    betriebsart,
                    vorlauf,
                    aussen,
                    json.dumps(details or {}),
                )
            return True
        except Exception as exc:
            log.error("insert_state_change Fehler: %s", exc)
            return False

    # ---------------------------------------------------------------------------
    # Function Audits
    # ---------------------------------------------------------------------------

    async def insert_function_audit(
        self,
        address: str,
        value: Optional[float],
        whitelist_ok: bool,
        dry_run: bool,
        cmi_called: bool,
        cmi_response: Optional[str],
        success: bool,
        reason: str,
        caller: str = "api",
    ) -> bool:
        if not self.is_connected:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO function_audits
                        (address, value, whitelist_ok, dry_run, cmi_called,
                         cmi_response, success, reason, caller)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    """,
                    address,
                    value,
                    whitelist_ok,
                    dry_run,
                    cmi_called,
                    cmi_response,
                    success,
                    reason,
                    caller,
                )
            return True
        except Exception as exc:
            log.error("insert_function_audit Fehler: %s", exc)
            return False

    # ---------------------------------------------------------------------------
    # Alarms
    # ---------------------------------------------------------------------------

    async def insert_alarm(
        self, active: bool, telegram_fwd: bool = False, details: str = ""
    ) -> bool:
        if not self.is_connected:
            return False
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO alarms (active, telegram_fwd, details) VALUES ($1,$2,$3)",
                    active,
                    telegram_fwd,
                    details,
                )
            return True
        except Exception as exc:
            log.error("insert_alarm Fehler: %s", exc)
            return False

    # ---------------------------------------------------------------------------
    # Heartbeat
    # ---------------------------------------------------------------------------

    async def insert_heartbeat(self, module: str = "main", details: Optional[dict] = None) -> bool:
        if not self.is_connected:
            return False
        try:
            import json

            async with self._pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO heartbeats (module, details) VALUES ($1,$2)",
                    module,
                    json.dumps(details or {}),
                )
            return True
        except Exception as exc:
            log.error("insert_heartbeat Fehler: %s", exc)
            return False

    # ---------------------------------------------------------------------------
    # Queries
    # ---------------------------------------------------------------------------

    async def get_last_telemetry(self) -> Optional[dict[str, Any]]:
        """Gibt letzten Telemetrie-Datensatz zurueck."""
        if not self.is_connected:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT * FROM telemetry ORDER BY ts DESC LIMIT 1"
                )
            if row:
                return dict(row)
            return None
        except Exception as exc:
            log.error("get_last_telemetry Fehler: %s", exc)
            return None

    async def get_last_heartbeat(self) -> Optional[datetime]:
        """Gibt Timestamp des letzten Heartbeats zurueck."""
        if not self.is_connected:
            return None
        try:
            async with self._pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT ts FROM heartbeats ORDER BY ts DESC LIMIT 1"
                )
            if row:
                return row["ts"]
            return None
        except Exception as exc:
            log.error("get_last_heartbeat Fehler: %s", exc)
            return None

    # ---------------------------------------------------------------------------
    # Intern
    # ---------------------------------------------------------------------------

    @staticmethod
    def _sanitize_url(url: str) -> str:
        """Entfernt Password aus URL fuer Logging."""
        import re

        return re.sub(r":([^@/]+)@", ":***@", url)
