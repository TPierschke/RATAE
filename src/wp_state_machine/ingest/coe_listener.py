"""
ingest/coe_listener.py — CoE UDP-Listener Skelett (Phase 1).

CoE (Control over Ethernet) ist UDP-basiert auf Port 5441.
Der UVR16x2 pusht Output-Bits aktiv. Ehrliche Quelle (kein Polling).

Phase-1-Status: Skelett. UDP-Socket-Binding an .10 (Debian 12, Port 5441).
Auf Mac entwickeln, nach .10 deployen.

Packet-Format (vereinfacht, TA UVR-Protokoll):
  Byte 0: Node-Nummer (0x3E = 62)
  Byte 1: Paket-Typ (0x80 = Analog, 0x81 = Digital)
  Byte 2-3: Kanal
  Byte 4-7: Wert (float32 LE fuer Analog, uint8 fuer Digital)

Hinweis: Tests duerfen NIEMALS einen echten UDP-Socket oeffnen!
         Mock-Pakete aus tests/fixtures/coe_packets.json nutzen.
"""

from __future__ import annotations

import asyncio
import logging
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

log = logging.getLogger(__name__)

# CoE-Konfiguration
DEFAULT_PORT = 5441
DEFAULT_HOST = "0.0.0.0"

# Output-Mapping (Kanal → Sensor-Feld)
# Basierend auf FHEM COE_Node_coe_61 Konfiguration
COE_DIGITAL_OUTPUT_MAP: dict[int, str] = {
    1: "pumpe_hzkr_ein",   # A1
    2: "ladepumpe_ein",    # A2
    3: "verdichter",       # A3
    5: "alarm",            # A5
    7: "ventil_ww",        # A7
    8: "heizstab_hz",      # A8
    9: "heizstab_ww",      # A9
    10: "pumpe_zirku",     # A10
}

COE_ANALOG_OUTPUT_MAP: dict[int, str] = {
    1: "pumpe_hzkr",   # A1 analog (0-100%)
    2: "ladepumpe",    # A2 analog
}


@dataclass
class CoePacket:
    """Geparstes CoE-UDP-Paket."""

    raw: bytes
    node: int
    packet_type: int
    channel: int
    value_raw: int | float
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_digital(self) -> bool:
        return self.packet_type == 0x81

    @property
    def is_analog(self) -> bool:
        return self.packet_type == 0x80

    def as_bool(self) -> bool:
        """Digital-Wert als bool."""
        return bool(self.value_raw)

    def as_float(self) -> float:
        """Analog-Wert als float."""
        return float(self.value_raw)


def parse_coe_packet(data: bytes) -> Optional[CoePacket]:
    """
    Parst ein rohe CoE-UDP-Paket.

    Gibt CoePacket oder None bei ungueltigem Format zurueck.
    Kein Netzwerk-Zugriff!
    """
    if len(data) < 4:
        log.debug("CoE-Paket zu kurz: %d bytes", len(data))
        return None

    try:
        node = data[0]
        packet_type = data[1]
        channel = data[2]

        if packet_type == 0x81 and len(data) >= 4:
            # Digital: Byte 3 = Wert
            value = int(data[3])
        elif packet_type == 0x80 and len(data) >= 8:
            # Analog: Bytes 4-7 float32 LE
            value = struct.unpack_from("<f", data, 4)[0]
        else:
            log.debug("Unbekannter CoE-Paket-Typ: 0x%02x", packet_type)
            return None

        return CoePacket(raw=data, node=node, packet_type=packet_type, channel=channel, value_raw=value)
    except (struct.error, IndexError) as exc:
        log.warning("CoE-Paket-Parse-Fehler: %s", exc)
        return None


def map_coe_to_sensors(packet: CoePacket) -> dict[str, bool | float]:
    """
    Mappt ein CoePacket auf Sensor-Felder.

    Gibt dict mit Feldname → Wert zurueck (leer wenn kein Mapping).
    """
    result: dict[str, bool | float] = {}

    if packet.is_digital:
        field_name = COE_DIGITAL_OUTPUT_MAP.get(packet.channel)
        if field_name:
            result[field_name] = packet.as_bool()
    elif packet.is_analog:
        field_name = COE_ANALOG_OUTPUT_MAP.get(packet.channel)
        if field_name:
            result[field_name] = packet.as_float()

    return result


# ---------------------------------------------------------------------------
# Async UDP-Listener (Skelett fuer .10 Deploy)
# ---------------------------------------------------------------------------


class CoeUdpProtocol(asyncio.DatagramProtocol):
    """asyncio UDP-Protokoll-Handler fuer CoE-Pakete."""

    def __init__(self, callback: Callable[[dict[str, bool | float]], None]) -> None:
        self.callback = callback
        self._packets_received = 0

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self._packets_received += 1
        log.debug("CoE UDP von %s: %d bytes", addr, len(data))

        packet = parse_coe_packet(data)
        if packet is None:
            return

        sensors = map_coe_to_sensors(packet)
        if sensors:
            self.callback(sensors)

    def error_received(self, exc: Exception) -> None:
        log.error("CoE UDP Fehler: %s", exc)


async def start_coe_listener(
    callback: Callable[[dict[str, bool | float]], None],
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
) -> asyncio.DatagramTransport:
    """
    Startet CoE UDP-Listener.

    callback wird mit Sensor-Dict aufgerufen wenn CoE-Paket ankommt.
    Gibt Transport zurueck (zum Schliessen: transport.close()).

    ACHTUNG: In Tests NIEMALS aufrufen! Nur im echten Daemon auf .10.
    """
    loop = asyncio.get_event_loop()
    transport, _ = await loop.create_datagram_endpoint(
        lambda: CoeUdpProtocol(callback),
        local_addr=(host, port),
    )
    log.info("CoE UDP-Listener gestartet auf %s:%d", host, port)
    return transport
