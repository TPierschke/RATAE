"""
Unit-Tests fuer ingest/modbus_slave.py.

KEIN echter Modbus-Server — alle Tests arbeiten mit den pure-Funktionen
decode_register() und decode_coil() sowie einem Mock-AppState.
pymodbus-Server wird NICHT gestartet.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wp_state_machine.ingest.modbus_slave import (
    MODBUS_COIL_MAP,
    MODBUS_REGISTER_MAP,
    COIL_SENSOR_FIELD_MAP,
    SENSOR_FIELD_MAP,
    ModbusHealth,
    decode_coil,
    decode_register,
)


# ---------------------------------------------------------------------------
# Hilfsmittel
# ---------------------------------------------------------------------------


class MockAppState:
    """Minimaler Mock fuer AppState — ohne echte Locks/DB."""

    def __init__(self):
        self.sensoren_updates: list[tuple[str, float]] = []
        self.coil_updates: list[tuple[str, bool]] = []
        self._lock = asyncio.Lock()

    async def update_from_modbus(self, sensor_name: str, value: float) -> None:
        self.sensoren_updates.append((sensor_name, value))

    async def update_coil_from_modbus(self, coil_name: str, value: bool) -> None:
        self.coil_updates.append((coil_name, value))


# ---------------------------------------------------------------------------
# decode_register() — int16
# ---------------------------------------------------------------------------


class TestDecodeRegisterInt16:
    # CMI-Wire ist 1-based (outmag=N landet auf addr=N+1).
    # Temperaturen werden als 1/100 °C gesendet (raw=2920 fuer 29.2 °C),
    # Decoder-Faktor 0.01.

    def test_aussen_positiv(self):
        """Register 1 = Aussentemp, 10 grad -> raw 1000."""
        result = decode_register(1, [1000])
        assert result is not None
        name, value = result
        assert name == "aussen"
        assert abs(value - 10.0) < 0.01

    def test_aussen_negativ(self):
        """Minustemperaturen: raw > 32767 = negativ signed16."""
        # -5.0 Grad = -500 raw = 65536 - 500 = 65036
        result = decode_register(1, [65036])
        assert result is not None
        name, value = result
        assert name == "aussen"
        assert abs(value - (-5.0)) < 0.01

    def test_vorlauf(self):
        """Register 2 = Vorlauf, 35.5 grad -> raw 3550."""
        result = decode_register(2, [3550])
        assert result is not None
        name, value = result
        assert name == "vorlauf"
        assert abs(value - 35.5) < 0.01

    def test_ruecklauf(self):
        result = decode_register(3, [2800])
        assert result is not None
        assert result[0] == "ruecklauf"
        assert abs(result[1] - 28.0) < 0.01

    def test_warmwasser(self):
        result = decode_register(4, [5500])
        assert result is not None
        assert result[0] == "warmwasser"
        assert abs(result[1] - 55.0) < 0.01

    def test_heissgas(self):
        result = decode_register(7, [7500])
        assert result is not None
        assert result[0] == "heissgas"
        assert abs(result[1] - 75.0) < 0.01

    def test_fluessigkeit(self):
        result = decode_register(8, [1000])
        assert result is not None
        assert result[0] == "fluessigkeit"
        assert abs(result[1] - 10.0) < 0.01

    def test_saugleitung(self):
        result = decode_register(9, [500])
        assert result is not None
        assert result[0] == "saugleitung"
        assert abs(result[1] - 5.0) < 0.01

    def test_vorlauf_soll(self):
        """Register 16 = VorlaufSoll."""
        result = decode_register(16, [3200])
        assert result is not None
        assert result[0] == "vorlauf_soll"
        assert abs(result[1] - 32.0) < 0.01

    def test_signed16_boundary_plus(self):
        """32767 = max positive signed16."""
        result = decode_register(1, [32767])
        assert result is not None
        assert abs(result[1] - 327.67) < 0.01

    def test_signed16_boundary_minus(self):
        """32768 = erste negative Zahl (= -32768)."""
        result = decode_register(1, [32768])
        assert result is not None
        assert abs(result[1] - (-327.68)) < 0.01

    def test_zero_raw(self):
        result = decode_register(1, [0])
        assert result is not None
        assert result[1] == 0.0

    def test_unknown_register_returns_none(self):
        result = decode_register(5, [100])  # Register 5 = ungenutzt (M5 leer)
        assert result is None

    def test_register_63_returns_none(self):
        result = decode_register(63, [100])
        assert result is None

    def test_empty_values_returns_none(self):
        result = decode_register(1, [])
        assert result is None


# ---------------------------------------------------------------------------
# decode_register() — uint16
# ---------------------------------------------------------------------------


class TestDecodeRegisterUint16:
    def test_message_fb(self):
        """Register 14 = MessageFB, uint16, kein Faktor."""
        result = decode_register(14, [42])
        assert result is not None
        name, value = result
        assert name == "message_fb"
        assert value == 42.0

    def test_message_ww(self):
        result = decode_register(15, [7])
        assert result is not None
        assert result[0] == "message_ww"
        assert result[1] == 7.0

    def test_message_max(self):
        result = decode_register(14, [65535])
        assert result is not None
        assert result[1] == 65535.0


# ---------------------------------------------------------------------------
# decode_register() — uint32 multi-write
# ---------------------------------------------------------------------------


class TestDecodeRegisterUint32:
    def test_betr_std_verdichter_basic(self):
        """Register 10 = BetrStdVerdichter, uint32, 2 Regs (10+11)."""
        # 1000 Stunden = high=0, low=1000
        result = decode_register(10, [0, 1000])
        assert result is not None
        name, value = result
        assert name == "betr_std_verdichter"
        assert value == 1000.0

    def test_betr_std_large_value(self):
        """uint32 mit hohem Wert: high=1, low=0 = 65536."""
        result = decode_register(10, [1, 0])
        assert result is not None
        assert result[1] == 65536.0

    def test_schaltungen_verdichter(self):
        result = decode_register(11, [0, 500])
        assert result is not None
        assert result[0] == "schaltungen_verdichter"
        assert result[1] == 500.0

    def test_betr_std_heizstab_fb(self):
        result = decode_register(12, [0, 200])
        assert result is not None
        assert result[0] == "betr_std_heizstab_fb"
        assert result[1] == 200.0

    def test_betr_std_heizstab_ww(self):
        result = decode_register(13, [0, 150])
        assert result is not None
        assert result[0] == "betr_std_heizstab_ww"
        assert result[1] == 150.0

    def test_uint32_be_encoding(self):
        """Big-endian: high_word = obere 16 bit, low_word = untere 16 bit."""
        # Wert: 0x00010000 = 65536
        result = decode_register(10, [0x0001, 0x0000])
        assert result is not None
        assert result[1] == 65536.0

    def test_uint32_max_uint16_per_register(self):
        """0xFFFF0000 | 0x0000FFFF = 4294967295 (uint32 max)."""
        result = decode_register(10, [0xFFFF, 0xFFFF])
        assert result is not None
        assert result[1] == 4294967295.0

    def test_uint32_only_one_register_returns_none(self):
        """Inkomplettes uint32 (nur 1 Register) → None."""
        result = decode_register(10, [100])
        assert result is None


# ---------------------------------------------------------------------------
# decode_register() — Sensor-Offsets
# ---------------------------------------------------------------------------


class TestDecodeRegisterOffsets:
    def test_offset_positiv(self):
        """Positiver Offset wird addiert."""
        result = decode_register(1, [1000], offsets={"aussen": 1.5})
        assert result is not None
        assert abs(result[1] - 11.5) < 0.01  # 10.0 + 1.5

    def test_offset_negativ(self):
        """Negativer Offset (Kalibrierung nach unten)."""
        result = decode_register(2, [3550], offsets={"vorlauf": -4.0})
        assert result is not None
        assert abs(result[1] - 31.5) < 0.01  # 35.5 - 4.0

    def test_offset_zero(self):
        """Offset 0.0 = kein Effekt."""
        result = decode_register(1, [1000], offsets={"aussen": 0.0})
        assert result is not None
        assert abs(result[1] - 10.0) < 0.01

    def test_offset_ohne_eintrag(self):
        """Kein Eintrag im Offsets-Dict = kein Offset."""
        result = decode_register(1, [1000], offsets={"vorlauf": 1.0})
        assert result is not None
        assert abs(result[1] - 10.0) < 0.01  # kein aussen-Offset

    def test_offsets_none_equivalent_zu_leer(self):
        """offsets=None = kein Offset."""
        r1 = decode_register(1, [1000], offsets=None)
        r2 = decode_register(1, [1000], offsets={})
        assert r1 == r2


# ---------------------------------------------------------------------------
# decode_coil()
# ---------------------------------------------------------------------------


class TestDecodeCoil:
    # Coils 1-based am Wire. 2026-05-09 final: 1..5=S10..S14, 6=Meldung,
    # 7..9=A1..A3, 10=A5, 11=A4, 12=A6, 13=A7, 14=A8(HZ), 15=A9(WW), 16=A10.

    def test_verdichter_ein(self):
        """Coil 9 = o_verdichter (A3)."""
        result = decode_coil(9, True)
        assert result is not None
        assert result[0] == "o_verdichter"
        assert result[1] is True

    def test_verdichter_aus(self):
        result = decode_coil(9, False)
        assert result is not None
        assert result[1] is False

    def test_ventil_ww(self):
        """Coil 13 = ventil_ww (A7)."""
        result = decode_coil(13, True)
        assert result is not None
        assert result[0] == "ventil_ww"

    def test_heizstab_ww(self):
        """Coil 15 = heizstab_ww (A9 = Heizstab2 Warmwasser)."""
        result = decode_coil(15, True)
        assert result is not None
        assert result[0] == "heizstab_ww"

    def test_heizstab_hz(self):
        """Coil 14 = heizstab_hz (A8 = Heizstab1 Heizung)."""
        result = decode_coil(14, False)
        assert result is not None
        assert result[0] == "heizstab_hz"
        assert result[1] is False

    def test_zirk_pumpe(self):
        """Coil 16 = zirk_pumpe (A10)."""
        result = decode_coil(16, True)
        assert result is not None
        assert result[0] == "zirk_pumpe"

    def test_phasenwaecht(self):
        """Coil 1 = phasenwaecht (S10)."""
        result = decode_coil(1, True)
        assert result is not None
        assert result[0] == "phasenwaecht"

    def test_alarm_ext(self):
        """Coil 10 = alarm_ext (A5)."""
        result = decode_coil(10, True)
        assert result is not None
        assert result[0] == "alarm_ext"

    def test_unknown_coil_returns_none(self):
        result = decode_coil(0, True)  # 0 ist nicht mehr gemapped (1-based)
        assert result is None

    def test_all_coils_mapped(self):
        """Alle 16 belegten Coils 1..16 decodierbar."""
        for addr in range(1, 17):
            result = decode_coil(addr, True)
            assert result is not None, f"Coil {addr} nicht decodierbar"


# ---------------------------------------------------------------------------
# Register-Map-Vollstaendigkeits-Tests
# ---------------------------------------------------------------------------


class TestRegisterMapIntegrity:
    def test_register_map_hat_eintraege(self):
        assert len(MODBUS_REGISTER_MAP) > 0

    def test_coil_map_hat_16_eintraege(self):
        assert len(MODBUS_COIL_MAP) == 16

    def test_coil_adressen_1_bis_16(self):
        # Coils 1..16 belegt (1-based am Wire) seit 2026-05-09 final-mapping
        assert set(MODBUS_COIL_MAP.keys()) == set(range(1, 17))

    def test_register_adressen_keine_duplikate(self):
        addrs = list(MODBUS_REGISTER_MAP.keys())
        assert len(addrs) == len(set(addrs))

    def test_alle_dtypes_valid(self):
        valid = {"int16", "uint16", "uint32"}
        for addr, (name, dtype, factor) in MODBUS_REGISTER_MAP.items():
            assert dtype in valid, f"Register {addr} hat unguelitgen dtype: {dtype}"

    def test_alle_faktoren_positiv(self):
        for addr, (name, dtype, factor) in MODBUS_REGISTER_MAP.items():
            assert factor > 0, f"Register {addr} hat Faktor <= 0"


# ---------------------------------------------------------------------------
# ModbusHealth
# ---------------------------------------------------------------------------


class TestModbusHealth:
    @pytest.mark.asyncio
    async def test_initial_state(self):
        h = ModbusHealth()
        assert h.last_update is None
        assert h.last_source_ip is None
        assert h.registers_received == 0
        assert h.coils_received == 0

    @pytest.mark.asyncio
    async def test_record_register_write(self):
        h = ModbusHealth()
        await h.record_write("192.168.178.45", is_coil=False)
        assert h.last_source_ip == "192.168.178.45"
        assert h.registers_received == 1
        assert h.coils_received == 0
        assert h.last_update is not None

    @pytest.mark.asyncio
    async def test_record_coil_write(self):
        h = ModbusHealth()
        await h.record_write("192.168.178.45", is_coil=True)
        assert h.coils_received == 1
        assert h.registers_received == 0

    @pytest.mark.asyncio
    async def test_to_dict_keys(self):
        h = ModbusHealth()
        d = h.to_dict()
        assert "last_update" in d
        assert "last_source_ip" in d
        assert "registers_received" in d
        assert "coils_received" in d

    @pytest.mark.asyncio
    async def test_to_dict_after_update(self):
        h = ModbusHealth()
        await h.record_write("10.0.0.1", is_coil=False)
        d = h.to_dict()
        assert d["last_source_ip"] == "10.0.0.1"
        assert d["last_update"] is not None
        assert d["registers_received"] == 1


# ---------------------------------------------------------------------------
# State-Update via Mock-AppState
# ---------------------------------------------------------------------------


class TestStateUpdateViaMockAppState:
    @pytest.mark.asyncio
    async def test_temperature_update_flows_to_appstate(self):
        """Simuliert den Weg: decode_register → update_from_modbus."""
        state = MockAppState()
        result = decode_register(1, [2250])  # 22.5 Grad (factor 0.01)
        assert result is not None
        name, value = result
        await state.update_from_modbus(name, value)
        assert ("aussen", 22.5) in state.sensoren_updates

    @pytest.mark.asyncio
    async def test_coil_update_flows_to_appstate(self):
        """Simuliert den Weg: decode_coil → update_coil_from_modbus."""
        state = MockAppState()
        result = decode_coil(13, True)  # ventil_ww (A7, final 2026-05-09 layout)
        assert result is not None
        coil_name, coil_val = result
        await state.update_coil_from_modbus(coil_name, coil_val)
        assert ("ventil_ww", True) in state.coil_updates

    @pytest.mark.asyncio
    async def test_multiple_registers_sequential(self):
        """Mehrere Register-Updates hintereinander."""
        state = MockAppState()
        registers = [
            (1, [2250]),  # aussen = 22.5
            (2, [3550]),  # vorlauf = 35.5
            (3, [2800]),  # ruecklauf = 28.0
            (4, [5200]),  # warmwasser = 52.0
        ]
        for addr, vals in registers:
            result = decode_register(addr, vals)
            if result:
                await state.update_from_modbus(*result)
        assert len(state.sensoren_updates) == 4

    @pytest.mark.asyncio
    async def test_counter_in_sensor_field_map(self):
        """Counter-Register (betr_std_verdichter) sind seit v0.1.5 im Sensoren-Modell."""
        result = decode_register(10, [0, 1500])
        assert result is not None
        name, value = result
        assert name == "betr_std_verdichter"
        assert value == 1500.0
        assert name in SENSOR_FIELD_MAP

    @pytest.mark.asyncio
    async def test_coil_alarm_updates_appstate(self):
        state = MockAppState()
        result = decode_coil(10, True)  # alarm_ext (A5, sequential layout)
        assert result is not None
        await state.update_coil_from_modbus(*result)
        assert ("alarm_ext", True) in state.coil_updates
