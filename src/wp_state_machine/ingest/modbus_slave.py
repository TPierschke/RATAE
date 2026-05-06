"""
ingest/modbus_slave.py — Modbus-TCP-Slave fuer CMI-Ingest (primaere Datenquelle).

Das CMI (192.168.178.45) ist Modbus-Master und schreibt aktiv via Modbus-TCP
an diesen Slave auf Port 5020. Der Slave dekodiert Holding-Register (Analog)
und Coils (Digital) und schreibt sie in den globalen AppState.

Primaeritaet: Modbus hat Vorrang gegenueber Web-Scraper und JSON-Poller,
da die Daten direkt vom CMI gepusht werden und keine Latenz durch Polling haben.

Voraussetzung: pymodbus>=3.7,<3.9 (3.8.x API)

ACHTUNG in Tests: NIEMALS echten Server starten!
         decode_register() und decode_coil() sind pure Funktionen und direkt testbar.
"""

from __future__ import annotations

import asyncio
import logging
import struct
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSlaveContext,
)
from pymodbus.server import StartAsyncTcpServer

if TYPE_CHECKING:
    from wp_state_machine.api.rest import AppState
    from wp_state_machine.config import Config

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Register-Mapping: Holding-Register (Analog)
# ---------------------------------------------------------------------------
# Format: register_addr -> (sensor_name, dtype, factor)
#
# dtype:
#   "int16"  — 1 Register, signed, Wert * factor = Physikalischer Wert
#   "uint16" — 1 Register, unsigned, Wert * factor = Physikalischer Wert
#   "uint32" — 2 Register (BE), unsigned, Wert * factor = Physikalischer Wert
#              uint32-Eintraege: start_register -> Definition (high_word)
#              CMI schreibt FC16 mit 2 Registern = [high_word, low_word] big-endian
#
# CMI MAPPING (aus tools/cmi_bulk_modbus_setup.py):
#   M1  (C1)  → Register 0  signed16  factor=10  → aussen
#   M2  (C2)  → Register 1  signed16  factor=10  → vorlauf
#   M3  (C3)  → Register 2  signed16  factor=10  → ruecklauf
#   M4  (C4)  → Register 3  signed16  factor=10  → warmwasser
#   M5  (0)   → Register 4  (ungenutzt)
#   M6  (C6)  → Register 5  signed16  factor=10  → traum1
#   M7  (C7)  → Register 6  signed16  factor=10  → heissgas
#   M8  (C8)  → Register 7  signed16  factor=10  → fluessigkeit
#   M9  (C9)  → Register 8  signed16  factor=10  → saugleitung
#   M10 (C10) → Register 9  uint32    factor=1   → betr_std_verdichter (2 regs: 9+10)
#   M11 (C11) → Register 10 uint32    factor=1   → schaltungen_verdichter (2 regs: 10+11)
#   M12 (C12) → Register 11 uint32    factor=1   → betr_std_heizstab_fb (2 regs: 11+12)
#   M13 (C13) → Register 12 uint32    factor=1   → betr_std_heizstab_ww (2 regs: 12+13)
#   M14 (C14) → Register 13 uint16    factor=1   → message_fb
#   M15 (C15) → Register 14 uint16    factor=1   → message_ww
#   M16 (C16) → Register 15 signed16  factor=10  → vorlauf_soll

MODBUS_REGISTER_MAP: dict[int, tuple[str, str, float]] = {
    0:  ("aussen",                  "int16",  0.1),
    1:  ("vorlauf",                 "int16",  0.1),
    2:  ("ruecklauf",               "int16",  0.1),
    3:  ("warmwasser",              "int16",  0.1),
    # 4 = ungenutzt (M5 leer)
    5:  ("traum1",                  "int16",  0.1),
    6:  ("heissgas",                "int16",  0.1),
    7:  ("fluessigkeit",            "int16",  0.1),
    8:  ("saugleitung",             "int16",  0.1),
    9:  ("betr_std_verdichter",     "uint32", 1.0),  # 2 Regs: 9+10
    10: ("schaltungen_verdichter",  "uint32", 1.0),  # 2 Regs: 10+11
    11: ("betr_std_heizstab_fb",    "uint32", 1.0),  # 2 Regs: 11+12
    12: ("betr_std_heizstab_ww",    "uint32", 1.0),  # 2 Regs: 12+13
    13: ("message_fb",              "uint16", 1.0),
    14: ("message_ww",              "uint16", 1.0),
    15: ("vorlauf_soll",            "int16",  0.1),
}

# Register die den HIGH-WORD eines uint32 darstellen (start_addr)
UINT32_START_REGS: frozenset[int] = frozenset(
    addr for addr, (_, dtype, _f) in MODBUS_REGISTER_MAP.items() if dtype == "uint32"
)

# ---------------------------------------------------------------------------
# Coil-Mapping: Coils (Digital)
# ---------------------------------------------------------------------------
# Format: coil_addr -> sensor_name
# CMI schreibt FC05 (write single coil) fuer jeden Digital-Output.
# (aus tools/cmi_bulk_modbus_digital.py)
MODBUS_COIL_MAP: dict[int, str] = {
    0:  "phasenwaecht",
    1:  "i_verdichter",
    2:  "nd_schalter1",
    3:  "hd_schalter",
    4:  "nd_schalter2",
    5:  "pumpe_hzkr",
    6:  "ladepumpe",
    7:  "o_verdichter",
    8:  "mvr0407_fl1",
    9:  "alarm_ext",
    10: "mvr0407_nach2",
    11: "ventil_ww",
    12: "heizstab_ww",
    13: "heizstab_hz",
    14: "zirk_pumpe",
    15: "alert_fb",
}

# ---------------------------------------------------------------------------
# Mapping Modbus-Sensor-Name → AppState.Sensoren-Feld
# ---------------------------------------------------------------------------
SENSOR_FIELD_MAP: dict[str, str] = {
    "aussen":      "aussen",
    "vorlauf":     "vorlauf",
    "ruecklauf":   "ruecklauf",
    "warmwasser":  "warmwasser",
    "heissgas":    "heissgas",
    "fluessigkeit":"fluessigkeit",
    "saugleitung": "saugleitung",
    # traum1, vorlauf_soll, counters, messages: kein direktes Sensoren-Feld
}

COIL_SENSOR_FIELD_MAP: dict[str, str] = {
    "i_verdichter":  "verdichter",
    "ventil_ww":     "ventil_ww",
    "heizstab_ww":   "heizstab_ww",
    "heizstab_hz":   "heizstab_hz",
    "zirk_pumpe":    "pumpe_zirku",
    "alarm_ext":     "alarm",
    "phasenwaecht":  "phasenwaechter",
    "nd_schalter1":  "nd_schalter1",
    "hd_schalter":   "hd_schalter",
    "nd_schalter2":  "nd_schalter2",
    "o_verdichter":  "verdichter",     # physischer Verdichter-Ausgang
}


# ---------------------------------------------------------------------------
# Dekodierungs-Funktionen (pure, testbar ohne Server)
# ---------------------------------------------------------------------------

def decode_register(
    address: int,
    raw_values: list[int],
    offsets: dict[str, float] | None = None,
) -> tuple[str, float] | None:
    """
    Dekodiert Holding-Register-Schreibvorgang vom CMI.

    Args:
        address:    Register-Startadresse (0-based)
        raw_values: Liste der rohen uint16-Werte (1 oder 2 Elemente)
        offsets:    Sensor-Offset-Dict {sensor_name: float_offset}

    Returns:
        (sensor_name, physical_value) oder None wenn unbekannt/ungenutzt
    """
    offsets = offsets or {}

    # Bei multi-write (uint32): CMI schreibt immer 2 Register.
    # Wenn address der low-word eines uint32-Paares ist, ignorieren
    # (wird beim high-word-Eintrag zusammengefasst).
    # Aber da CMI FC16 immer beide zusammen schreibt, kommen beide auf einmal an.

    entry = MODBUS_REGISTER_MAP.get(address)
    if entry is None:
        return None

    name, dtype, factor = entry

    if dtype == "int16":
        if not raw_values:
            return None
        raw = raw_values[0]
        # signed16: Werte >= 32768 sind negativ
        signed = raw if raw < 32768 else raw - 65536
        value = signed * factor + offsets.get(name, 0.0)
        return (name, round(value, 2))

    elif dtype == "uint16":
        if not raw_values:
            return None
        raw = raw_values[0]
        value = raw * factor + offsets.get(name, 0.0)
        return (name, round(value, 2))

    elif dtype == "uint32":
        if len(raw_values) < 2:
            # Nur High-Word angekommen — inkomplettes Paket, warten
            log.debug("uint32 addr=%d: nur 1 Register angekommen, ignoriere", address)
            return None
        # Big-endian: high_word zuerst
        high = raw_values[0]
        low = raw_values[1]
        value_raw = (high << 16) | low
        value = value_raw * factor + offsets.get(name, 0.0)
        return (name, round(value, 2))

    return None


def decode_coil(address: int, value: bool) -> tuple[str, bool] | None:
    """
    Dekodiert Coil-Schreibvorgang vom CMI.

    Args:
        address: Coil-Adresse (0-based)
        value:   True/False

    Returns:
        (sensor_name, bool_value) oder None wenn unbekannt
    """
    name = MODBUS_COIL_MAP.get(address)
    if name is None:
        return None
    return (name, value)


# ---------------------------------------------------------------------------
# Health-State
# ---------------------------------------------------------------------------

class ModbusHealth:
    """Self-Health-Daten fuer /health-Endpoint."""

    def __init__(self) -> None:
        self.last_update: Optional[datetime] = None
        self.last_source_ip: Optional[str] = None
        self.registers_received: int = 0
        self.coils_received: int = 0
        self._lock = asyncio.Lock()

    async def record_write(self, source_ip: str, is_coil: bool = False) -> None:
        async with self._lock:
            self.last_update = datetime.now(timezone.utc)
            self.last_source_ip = source_ip
            if is_coil:
                self.coils_received += 1
            else:
                self.registers_received += 1

    def to_dict(self) -> dict:
        return {
            "last_update": self.last_update.isoformat() if self.last_update else None,
            "last_source_ip": self.last_source_ip,
            "registers_received": self.registers_received,
            "coils_received": self.coils_received,
        }


# Global health singleton — fuer /health-Endpoint
modbus_health = ModbusHealth()


# ---------------------------------------------------------------------------
# Pymodbus DataBlock mit AppState-Callback
# ---------------------------------------------------------------------------

class _StateUpdatingDataBlock(ModbusSequentialDataBlock):
    """
    DataBlock der bei jedem Schreibvorgang den AppState aktualisiert.

    Wird vom pymodbus-Server im asyncio-Kontext aufgerufen.
    Der AppState-Update ist thread-safe via asyncio.Lock (in AppState).
    """

    def __init__(
        self,
        name: str,
        start: int,
        values: list[int],
        *,
        is_coil: bool,
        state_ref: list,  # [AppState] — mutable ref, spaet gebunden
        offsets: dict[str, float],
        source_ip_ref: list,  # [str | None]
    ) -> None:
        super().__init__(start, values)
        self.name = name
        self.is_coil = is_coil
        self._state_ref = state_ref
        self._offsets = offsets
        self._source_ip_ref = source_ip_ref

    def setValues(self, address: int, values) -> None:
        super().setValues(address, values)
        # Kick async update (fire-and-forget im laufenden event-loop)
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(
                    self._async_update(address, values)
                )
        except RuntimeError:
            pass  # Kein laufender Loop (z.B. in Tests ohne Loop)

    async def _async_update(self, address: int, values) -> None:
        app_state = self._state_ref[0] if self._state_ref else None
        source_ip = self._source_ip_ref[0] if self._source_ip_ref else "unknown"

        await modbus_health.record_write(source_ip or "unknown", is_coil=self.is_coil)

        if app_state is None:
            return

        if self.is_coil:
            # Coil: values kann bool oder list sein
            if isinstance(values, list):
                for i, v in enumerate(values):
                    result = decode_coil(address + i, bool(v))
                    if result:
                        coil_name, coil_val = result
                        await app_state.update_coil_from_modbus(coil_name, coil_val)
            else:
                result = decode_coil(address, bool(values))
                if result:
                    coil_name, coil_val = result
                    await app_state.update_coil_from_modbus(coil_name, coil_val)
        else:
            # Holding-Register
            if not isinstance(values, list):
                values = [values]
            result = decode_register(address, values, self._offsets)
            if result:
                sensor_name, sensor_val = result
                await app_state.update_from_modbus(sensor_name, sensor_val)
            elif len(values) == 1:
                log.debug("HR addr=%d: kein Mapping", address)


def _make_context(
    state_ref: list,
    offsets: dict[str, float],
    source_ip_ref: list,
) -> ModbusServerContext:
    """Erstellt Modbus-Server-Context mit State-Updating DataBlocks."""
    holding = _StateUpdatingDataBlock(
        "HR", 0, [0] * 64,
        is_coil=False,
        state_ref=state_ref,
        offsets=offsets,
        source_ip_ref=source_ip_ref,
    )
    coils = _StateUpdatingDataBlock(
        "CO", 0, [0] * 64,
        is_coil=True,
        state_ref=state_ref,
        offsets=offsets,
        source_ip_ref=source_ip_ref,
    )
    discrete = ModbusSequentialDataBlock(0, [0] * 64)
    inputs = ModbusSequentialDataBlock(0, [0] * 64)
    slave = ModbusSlaveContext(di=discrete, co=coils, hr=holding, ir=inputs)
    return ModbusServerContext(slaves={1: slave}, single=False)


# ---------------------------------------------------------------------------
# Public run()-Coroutine
# ---------------------------------------------------------------------------

async def run(state: "AppState", config: "Config") -> None:
    """
    Startet den Modbus-TCP-Slave-Server.

    Wird als asyncio.create_task() in __main__.py gestartet.
    Blockiert bis der Server gestoppt wird (CancelledError bei Shutdown).

    Args:
        state:  Globaler AppState (wird bei jedem Write aktualisiert)
        config: Config-Objekt (modbus_port, modbus_slave_id, sensor_offsets)
    """
    port = getattr(config, "modbus_port", 5020)
    slave_id = getattr(config, "modbus_slave_id", 1)
    offsets = getattr(config, "sensor_offsets", {})

    # Mutable refs fuer spaete Bindung (pymodbus erstellt DataBlocks vor run())
    state_ref: list = [state]
    source_ip_ref: list = [None]

    context = _make_context(state_ref, offsets, source_ip_ref)

    log.info(
        "Modbus-Slave startet auf 0.0.0.0:%d, Slave-ID %d", port, slave_id
    )
    try:
        await StartAsyncTcpServer(
            context=context,
            address=("0.0.0.0", port),
        )
    except asyncio.CancelledError:
        log.info("Modbus-Slave gestoppt (CancelledError)")
        raise
    except OSError as exc:
        log.error("Modbus-Slave Port %d belegt oder nicht bindbar: %s", port, exc)
        raise
