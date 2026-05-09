#!/usr/bin/env python3
"""Bulk setup of CMI Modbus outputs M-1..M-16 (digital) + M1..M16 (analog).

1:1 mapping to corresponding CMI CAN inputs (C-N / CN). Wire address = N (1-based)
via outmag=N-1.

Target: state-machine slave 192.168.178.3:5020, Slave-ID 1.

Digital: FC05 (write single coil), source = C-N
Analog:  FC16 (write multiple registers), source = CN, signed16 with factor 10
         (CMI raw is 1/100 °C with intra-CMI scaling x10 -> wire raw = uvr_value*100)
         Counter slots (10, 11): uint32, factor 1
         Status/Meldung slots (12, 14, 15): uint16, factor 1
"""
from __future__ import annotations

import base64
import re
import sys
import time
import urllib.parse
import urllib.request

CMI = "192.168.178.45"
SLAVE_IP = "192.168.178.3"
SLAVE_DEV = 1
AUTH = "Basic " + base64.b64encode(b"admin:admin").decode()
PAUSE = 1.5

# (slot, source, label) for digital outputs (FC05, single coil)
DIGITAL_MAPPING: dict[int, tuple[str, str]] = {
    1:  ("C-1",  "DI_Phasenwaecht"),
    2:  ("C-2",  "DI_I_Verdichter"),
    3:  ("C-3",  "DI_ND_Schalter1"),
    4:  ("C-4",  "DI_HD_Schalter"),
    5:  ("C-5",  "DI_ND_Schalter2"),
    6:  ("C-6",  "DI_Meld_Heizung"),
    7:  ("C-7",  "DI_Pumpe_Hzkr"),
    8:  ("C-8",  "DI_Ladepumpe"),
    9:  ("C-9",  "DI_Verdichter"),
    10: ("C-10", "DI_Alarm_Ext"),
    11: ("C-11", "DI_MVR0407_FL1"),
    12: ("C-12", "DI_MVR0407_Nach2"),
    13: ("C-13", "DI_Ventil_WW"),
    14: ("C-14", "DI_Heizstab_HZ"),
    15: ("C-15", "DI_Heizstab_WW"),
    16: ("C-16", "DI_Pumpe_Zirku"),
}

# Analog: (slot, source, label, datatype, factor)
# datatype: 2=signed16, 5=uint32
ANALOG_MAPPING: dict[int, tuple[str | None, str, int, int]] = {
    1:  ("C1",  "AI_T_Aussen",       2, 10),
    2:  ("C2",  "AI_T_Puffer_o",     2, 10),
    3:  ("C3",  "AI_T_Heizkr_RL",    2, 10),
    4:  ("C4",  "AI_T_WW_Speich",    2, 10),
    5:  ("C5",  "AI_NW_Stat_21",     2, 10),
    6:  ("C6",  "AI_Traum_SOLL",     2, 10),
    7:  ("C7",  "AI_T_Heissgas",     2, 10),
    8:  ("C8",  "AI_T_Fluessig",     2, 10),
    9:  ("C9",  "AI_T_Saugltg",      2, 10),
    10: ("C10", "AI_BetrStd_Verd",   5, 1),
    11: ("C11", "AI_Schaltz_Verd",   5, 1),
    12: ("C12", "AI_FBH_PumpStatus", 2, 1),
    13: (None,  "",                  2, 10),  # skip
    14: ("C14", "AI_Meld_Heizung",   2, 1),
    15: ("C15", "AI_Meld_WW",        2, 1),
    16: ("C16", "AI_VL_Solltemp",    2, 10),
}


def post_digital(slot: int, source: str, bez: str) -> bool:
    fields = {
        "cmioutput": f"M-{slot}",
        "outmbez": bez,
        "outmin": source,
        "outmval": "0",
        "outmip": SLAVE_IP,
        "outmdev": str(SLAVE_DEV),
        "outmfkt": "05",
        "outmag": str(slot - 1),
        "outmbedd": "0",
        "outmbeda": "0",
        "outmblock": "10",
        "outmint": "5",
        "save": "Save",
    }
    return _post(fields)


def post_analog(slot: int, source: str, bez: str, dtyp: int, factor: int) -> bool:
    # CMI form expects outmfkt='10' for FC16 (write multiple registers).
    # Decimal-style was rejected silently.
    fields = {
        "cmioutput": f"M{slot}",
        "outmbez": bez,
        "outmin": source,
        "outmval": "0",
        "outmip": SLAVE_IP,
        "outmdev": str(SLAVE_DEV),
        "outmfkt": "10",
        "outmag": str(slot - 1),
        "outmdtyp": str(dtyp),
        "outmbyteo": "0",
        "outms": str(factor),
        "outmbedd": "0",
        "outmbeda": "0.5",
        "outmblock": "10",
        "outmint": "5",
        "save": "Save",
    }
    return _post(fields)


def _post(fields: dict[str, str]) -> bool:
    data = urllib.parse.urlencode(fields, encoding="iso-8859-1").encode("iso-8859-1")
    req = urllib.request.Request(
        f"http://{CMI}/settings_output.cgi",
        data=data,
        headers={
            "Authorization": AUTH,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as exc:
        print(f"  HTTP error: {exc}")
        return False


def main() -> int:
    fails = 0
    print(f"=== Digital outputs (M-1..M-16, FC05) ===")
    for slot, (src, bez) in DIGITAL_MAPPING.items():
        ok = post_digital(slot, src, bez)
        print(f"  M-{slot:>2}: src={src:<6} bez='{bez}'  {'OK' if ok else 'FAIL'}")
        if not ok:
            fails += 1
        time.sleep(PAUSE)

    print(f"\n=== Analog outputs (M1..M16, FC16) ===")
    for slot, (src, bez, dtyp, factor) in ANALOG_MAPPING.items():
        if src is None:
            print(f"  M{slot:>2}: (skip)")
            continue
        ok = post_analog(slot, src, bez, dtyp, factor)
        print(f"  M{slot:>2}:  src={src:<5} bez='{bez}' dtyp={dtyp} f={factor}  {'OK' if ok else 'FAIL'}")
        if not ok:
            fails += 1
        time.sleep(PAUSE)

    digital_count = len(DIGITAL_MAPPING)
    analog_count = sum(1 for v in ANALOG_MAPPING.values() if v[0] is not None)
    total = digital_count + analog_count
    print(f"\nSummary: {total - fails}/{total} OK")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
