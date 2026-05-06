"""Unit-Tests fuer ingest/coe_listener.py.

KEIN echter UDP-Socket! Tests arbeiten mit Mock-Paketen aus coe_packets.json.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from wp_state_machine.ingest.coe_listener import (
    CoePacket,
    map_coe_to_sensors,
    parse_coe_packet,
)

FIXTURES_DIR = Path(__file__).parents[1] / "fixtures"


class TestParseCoePacket:
    def test_parse_digital_ein(self):
        """Digital-Paket: Verdichter EIN."""
        data = bytes.fromhex("3E810301")
        pkt = parse_coe_packet(data)
        assert pkt is not None
        assert pkt.node == 0x3E
        assert pkt.is_digital is True
        assert pkt.channel == 3
        assert pkt.as_bool() is True

    def test_parse_digital_aus(self):
        data = bytes.fromhex("3E810300")
        pkt = parse_coe_packet(data)
        assert pkt is not None
        assert pkt.as_bool() is False

    def test_parse_alarm_ein(self):
        data = bytes.fromhex("3E810501")
        pkt = parse_coe_packet(data)
        assert pkt is not None
        assert pkt.channel == 5
        assert pkt.as_bool() is True

    def test_parse_too_short_returns_none(self):
        assert parse_coe_packet(b"\x3E") is None

    def test_parse_empty_returns_none(self):
        assert parse_coe_packet(b"") is None

    def test_parse_ventil_ww(self):
        data = bytes.fromhex("3E810701")
        pkt = parse_coe_packet(data)
        assert pkt is not None
        assert pkt.channel == 7

    def test_parse_heizstab_dangerous(self):
        """Heizstab A8 — parsbar, aber Sensor-Feld heizstab_hz."""
        data = bytes.fromhex("3E810801")
        pkt = parse_coe_packet(data)
        assert pkt is not None
        assert pkt.channel == 8

    def test_timestamp_present(self):
        data = bytes.fromhex("3E810301")
        pkt = parse_coe_packet(data)
        assert pkt is not None
        assert pkt.timestamp is not None


class TestMapCoeToSensors:
    def test_verdichter_ein(self):
        data = bytes.fromhex("3E810301")
        pkt = parse_coe_packet(data)
        result = map_coe_to_sensors(pkt)
        assert result.get("verdichter") is True

    def test_verdichter_aus(self):
        data = bytes.fromhex("3E810300")
        pkt = parse_coe_packet(data)
        result = map_coe_to_sensors(pkt)
        assert result.get("verdichter") is False

    def test_alarm_ein(self):
        data = bytes.fromhex("3E810501")
        pkt = parse_coe_packet(data)
        result = map_coe_to_sensors(pkt)
        assert result.get("alarm") is True

    def test_ventil_ww(self):
        data = bytes.fromhex("3E810701")
        pkt = parse_coe_packet(data)
        result = map_coe_to_sensors(pkt)
        assert result.get("ventil_ww") is True

    def test_heizstab_hz(self):
        data = bytes.fromhex("3E810801")
        pkt = parse_coe_packet(data)
        result = map_coe_to_sensors(pkt)
        assert result.get("heizstab_hz") is True

    def test_heizstab_ww(self):
        data = bytes.fromhex("3E810901")
        pkt = parse_coe_packet(data)
        result = map_coe_to_sensors(pkt)
        assert result.get("heizstab_ww") is True

    def test_unknown_channel_returns_empty(self):
        """Unbekannter Kanal ergibt leeres dict."""
        data = bytes.fromhex("3E810F00")  # Channel 15 nicht gemappt
        pkt = parse_coe_packet(data)
        result = map_coe_to_sensors(pkt)
        assert result == {}

    def test_pumpe_zirku_aus(self):
        data = bytes.fromhex("3E810A00")  # 0x0A = 10 = A10
        pkt = parse_coe_packet(data)
        result = map_coe_to_sensors(pkt)
        assert result.get("pumpe_zirku") is False


class TestCoeFixtures:
    """Tests basierend auf coe_packets.json Fixtures."""

    @pytest.fixture
    def packets(self) -> list[dict]:
        fp = FIXTURES_DIR / "coe_packets.json"
        return json.loads(fp.read_text())

    def test_all_fixture_packets_parseable(self, packets: list[dict]):
        for entry in packets:
            data = bytes.fromhex(entry["hex"])
            pkt = parse_coe_packet(data)
            assert pkt is not None, f"Paket nicht parsebar: {entry['description']}"

    def test_fixture_expected_values(self, packets: list[dict]):
        for entry in packets:
            data = bytes.fromhex(entry["hex"])
            pkt = parse_coe_packet(data)
            result = map_coe_to_sensors(pkt)
            field = entry["expected_field"]
            expected = entry["expected_value"]
            assert result.get(field) == expected, (
                f"{entry['description']}: {field}={result.get(field)} != {expected}"
            )
