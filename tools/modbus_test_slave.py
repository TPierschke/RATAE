#!/usr/bin/env python3
"""
Modbus-TCP-Slave-Server fuer CMI-Tests (pymodbus 3.8 kompatibel).

HINWEIS: Standalone-Debug-Tool. Das produktive Modul liegt unter:
  src/wp_state_machine/ingest/modbus_slave.py

Vor Verwendung: lsof -i :5020 pruefen, ggf. pkill -f modbus_test_slave.py

Lauscht auf Port 5020, Slave-ID 1.
Loggt jeden Schreibvorgang vom CMI mit Timestamp + Wert.

Nutzung: python3 tools/modbus_test_slave.py
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSlaveContext,
)
from pymodbus.server import StartAsyncTcpServer

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
log = logging.getLogger("modbus-slave")

PORT = 5020


class LoggingDataBlock(ModbusSequentialDataBlock):
    """DataBlock der jeden Write loggt."""

    def __init__(self, name: str, address: int, values):
        super().__init__(address, values)
        self.name = name

    def setValues(self, address, values):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        if isinstance(values, list) and len(values) == 1:
            v = values[0]
            v_signed = v if v < 32768 else v - 65536
            log.info(
                f"[{ts}] {self.name} addr={address} raw_uint16={v} signed={v_signed} factor10={v_signed/10:.1f}"
            )
        elif isinstance(values, list):
            log.info(f"[{ts}] {self.name} addr={address} multi-write n={len(values)} values={values}")
        else:
            log.info(f"[{ts}] {self.name} addr={address} single-bool={values}")
        super().setValues(address, values)


def make_context() -> ModbusServerContext:
    holding = LoggingDataBlock("HR", 0, [0] * 64)
    coils = LoggingDataBlock("CO", 0, [0] * 64)
    discrete = ModbusSequentialDataBlock(0, [0] * 64)
    inputs = ModbusSequentialDataBlock(0, [0] * 64)
    slave = ModbusSlaveContext(di=discrete, co=coils, hr=holding, ir=inputs)
    return ModbusServerContext(slaves={1: slave}, single=False)


async def main():
    log.info(f"Modbus-TCP-Slave startet auf 0.0.0.0:{PORT}, Slave-ID 1")
    log.info("Wartet auf Schreibvorgaenge vom CMI...")
    await StartAsyncTcpServer(context=make_context(), address=("0.0.0.0", PORT))


if __name__ == "__main__":
    asyncio.run(main())
