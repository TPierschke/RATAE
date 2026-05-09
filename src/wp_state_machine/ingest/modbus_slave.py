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

#
# WICHTIG: CMI-Holding-Register-Adressen sind 1-BASED am Wire.
# outmag=N im CMI-Webinterface landet am Wire auf addr=N+1.
# Plus: CMI sendet Temperaturen als 1/100 °C (raw=2920 fuer 29.2 °C),
# also factor=0.01 statt 0.1.
# Coils dagegen sind 0-based (outmag=N → addr=N), siehe MODBUS_COIL_MAP.
#
MODBUS_REGISTER_MAP: dict[int, tuple[str, str, float]] = {
    1:  ("aussen",                  "int16",  0.01),
    2:  ("vorlauf",                 "int16",  0.01),
    3:  ("ruecklauf",               "int16",  0.01),
    4:  ("warmwasser",              "int16",  0.01),
    # 5 = ungenutzt (M5 leer)
    6:  ("traum1",                  "int16",  0.01),
    7:  ("heissgas",                "int16",  0.01),
    8:  ("fluessigkeit",            "int16",  0.01),
    9:  ("saugleitung",             "int16",  0.01),
    10: ("betr_std_verdichter",     "uint32", 1.0),  # 2 Regs: 10+11
    11: ("schaltungen_verdichter",  "uint32", 1.0),  # 2 Regs: 11+12
    12: ("betr_std_heizstab_fb",    "uint32", 1.0),  # 2 Regs: 12+13
    13: ("betr_std_heizstab_ww",    "uint32", 1.0),  # 2 Regs: 13+14
    14: ("message_fb",              "uint16", 1.0),
    15: ("message_ww",              "uint16", 1.0),
    16: ("vorlauf_soll",            "int16",  0.01),
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
#
# WICHTIG: CMI-Coil-Adressen sind 1-BASED am Wire (analog zu Holding-Register).
# outmag=N im CMI-Webinterface landet auf Wire-Adresse N+1.
# Verifiziert 2026-05-07 anhand laufender Anlage:
#   addr=8 raw=1 = o_verdichter (Verdichter laeuft)
#   addr=10 raw=0 = alarm_ext (kein Alarm)
#
#
# 2026-05-09 (final): Layout aligned with new CMI config 'one of one' user spec.
# Sequence follows UVR CAN-output order from CMI Network-Outputs page 3E005826:
#   Wire 1..5  -> S10..S14 (digital inputs Phasen/Verdichter-Freigabe/ND/HD/ND2)
#   Wire 6     -> Meldung 8 Heizung
#   Wire 7..9  -> A1..A3 (Pumpe-Hzkr, Ladepumpe, O_Verdichter)
#   Wire 10    -> A5 Alarm ext
#   Wire 11    -> A4 MV R0407 FL1
#   Wire 12    -> A6 MV R0407 Nach2
#   Wire 13    -> A7 Ventil-WW
#   Wire 14    -> A8 Heizstab1 (HZ)
#   Wire 15    -> A9 Heizstab2 (WW)
#   Wire 16    -> A10 Pumpe-Zirku
#
MODBUS_COIL_MAP: dict[int, str] = {
    1:  "phasenwaecht",       # S10
    2:  "i_verdichter",       # S11
    3:  "nd_schalter1",       # S12
    4:  "hd_schalter",        # S13
    5:  "nd_schalter2",       # S14
    6:  "meldung_heizung",    # Meldung 8 (Heizung)
    7:  "pumpe_hzkr",         # A1
    8:  "ladepumpe",          # A2
    9:  "o_verdichter",       # A3 (real run status)
    10: "alarm_ext",          # A5  (note: A5 before A4 in UVR CAN-out order)
    11: "mvr0407_fl1",        # A4
    12: "mvr0407_nach2",      # A6
    13: "ventil_ww",          # A7
    14: "heizstab_hz",        # A8 = Heizstab1 (Heizung)
    15: "heizstab_ww",        # A9 = Heizstab2 (Warmwasser)
    16: "zirk_pumpe",         # A10 (sensor name; mapped to 'pumpe_zirku' field)
}

# ---------------------------------------------------------------------------
# Mapping Modbus-Sensor-Name → AppState.Sensoren-Feld
# ---------------------------------------------------------------------------
SENSOR_FIELD_MAP: dict[str, str] = {
    "aussen":                  "aussen",
    "vorlauf":                 "vorlauf",
    "ruecklauf":               "ruecklauf",
    "warmwasser":              "warmwasser",
    "heissgas":                "heissgas",
    "fluessigkeit":            "fluessigkeit",
    "saugleitung":             "saugleitung",
    "traum1":                  "traum1",
    "vorlauf_soll":            "vorlauf_soll",
    "betr_std_verdichter":     "betr_std_verdichter",
    "schaltungen_verdichter":  "schaltungen_verdichter",
    "betr_std_heizstab_fb":    "betr_std_heizstab_fb",
    "betr_std_heizstab_ww":    "betr_std_heizstab_ww",
    "message_fb":              "message_fb",
    "message_ww":              "message_ww",
}

COIL_SENSOR_FIELD_MAP: dict[str, str] = {
    # Inputs (S10..S14)
    "phasenwaecht":    "phasenwaechter",
    "i_verdichter":    "verdichter_freigabe",  # S11 phase enable — always 1 when power on
    "nd_schalter1":    "nd_schalter1",
    "hd_schalter":     "hd_schalter",
    "nd_schalter2":    "nd_schalter2",
    # Messages
    "meldung_heizung": "meldung_heizung",      # Meldung 8 (Heizung)
    # Outputs A1..A10 (real actor states)
    "pumpe_hzkr":      "pumpe_hzkr",           # A1
    "ladepumpe":       "ladepumpe",            # A2
    "o_verdichter":    "verdichter",           # A3 real run status
    "alarm_ext":       "alarm",                # A5
    "mvr0407_fl1":     "mvr0407_fl1",          # A4
    "mvr0407_nach2":   "mvr0407_nach2",        # A6
    "ventil_ww":       "ventil_ww",            # A7
    "heizstab_hz":     "heizstab_hz",          # A8 Heizstab1 (Heizung)
    "heizstab_ww":     "heizstab_ww",          # A9 Heizstab2 (Warmwasser)
    "zirk_pumpe":      "pumpe_zirku",          # A10
}

# Sensoren-Felder, fuer die Modbus die Primaerquelle ist.
# Web-Scraper darf diese nur schreiben, wenn Modbus laenger als
# MODBUS_FRESHNESS_SECONDS keinen Update mehr geliefert hat.
MODBUS_OWNED_FIELDS: frozenset[str] = frozenset(
    set(SENSOR_FIELD_MAP.values()) | set(COIL_SENSOR_FIELD_MAP.values())
)
MODBUS_FRESHNESS_SECONDS: int = 300

# Modbus ist Primaerquelle. Auf False setzen um nur zu loggen
# (Diagnose-Modus, falls CMI-Konfig wieder kippt).
MODBUS_DROP_VALUES: bool = False


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
        # Kick async update (fire-and-forget im laufenden event-loop).
        # Strukturiertes Logging passiert in _async_update() — dort wissen
        # wir auch, ob applied=YES/NO (Drop-Mode-abhaengig).
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

        applied = "NO" if MODBUS_DROP_VALUES else "YES"

        if self.is_coil:
            # Coil: values kann bool oder list sein
            if isinstance(values, list):
                vlist = values
            else:
                vlist = [values]
            for i, v in enumerate(vlist):
                addr_i = address + i
                bool_v = bool(v)
                result = decode_coil(addr_i, bool_v)
                sensor_name = result[0] if result else MODBUS_COIL_MAP.get(addr_i, "unknown")
                log.info(
                    "Modbus-RAW addr=%d sensor=%s raw=%d signed=%d decoded=%s applied=%s",
                    addr_i, sensor_name, int(bool_v), int(bool_v),
                    result[1] if result else None,
                    applied,
                )
                if result and app_state is not None and not MODBUS_DROP_VALUES:
                    coil_name, coil_val = result
                    await app_state.update_coil_from_modbus(coil_name, coil_val)
        else:
            # Holding-Register
            if not isinstance(values, list):
                values = [values]
            entry = MODBUS_REGISTER_MAP.get(address)
            sensor_name = entry[0] if entry else "unknown"
            raw_first = values[0] if values else 0
            signed_first = raw_first if raw_first < 32768 else raw_first - 65536
            result = decode_register(address, values, self._offsets)
            decoded_val = result[1] if result else None
            log.info(
                "Modbus-RAW addr=%d sensor=%s raw=%d signed=%d decoded=%s applied=%s",
                address, sensor_name, raw_first, signed_first, decoded_val, applied,
            )
            if result and app_state is not None and not MODBUS_DROP_VALUES:
                s_name, s_val = result
                await app_state.update_from_modbus(s_name, s_val)
            elif not result and len(values) == 1:
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
