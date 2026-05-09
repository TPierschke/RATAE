#!/usr/bin/env python3
"""Bulk setup of CMI CoE outputs E-1..E-16 (digital) + E1..E16 (analog).

Identical layout as Modbus: 1:1 mapping to corresponding CMI CAN inputs.
Target: nucthp (192.168.178.10), CAN-node 55.

CoE is UDP multicast — used here for FHEM consumption on nucthp.
"""
from __future__ import annotations

import base64
import sys
import time
import urllib.parse
import urllib.request

CMI = "192.168.178.45"
TARGET_IP = "192.168.178.10"   # nucthp
TARGET_NODE = 55               # CAN-node id of CoE listener
AUTH = "Basic " + base64.b64encode(b"admin:admin").decode()
PAUSE = 1.5

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

ANALOG_MAPPING: dict[int, tuple[str | None, str]] = {
    1:  ("C1",  "AI_T_Aussen"),
    2:  ("C2",  "AI_T_Puffer_o"),
    3:  ("C3",  "AI_T_Heizkr_RL"),
    4:  ("C4",  "AI_T_WW_Speich"),
    5:  ("C5",  "AI_NW_Stat_21"),
    6:  ("C6",  "AI_Traum_SOLL"),
    7:  ("C7",  "AI_T_Heissgas"),
    8:  ("C8",  "AI_T_Fluessig"),
    9:  ("C9",  "AI_T_Saugltg"),
    10: ("C10", "AI_BetrStd_Verd"),
    11: ("C11", "AI_Schaltz_Verd"),
    12: ("C12", "AI_FBH_PumpStatus"),
    13: (None,  ""),
    14: ("C14", "AI_Meld_Heizung"),
    15: ("C15", "AI_Meld_WW"),
    16: ("C16", "AI_VL_Solltemp"),
}


def post_digital(slot: int, source: str, bez: str) -> bool:
    fields = {
        "cmioutput": f"E-{slot}",
        "outebez": bez,
        "outein": source,
        "outeip": TARGET_IP,
        "outedev": str(TARGET_NODE),
        "outeag": str(slot - 1),
        "outebeda": "0",
        "outeblock": "10",
        "outeint": "5",
        "save": "Save",
    }
    return _post(fields)


def post_analog(slot: int, source: str, bez: str) -> bool:
    fields = {
        "cmioutput": f"E{slot}",
        "outebez": bez,
        "outein": source,
        "outeip": TARGET_IP,
        "outedev": str(TARGET_NODE),
        "outeag": str(slot - 1),
        "outebeda": "0.5",
        "outeblock": "10",
        "outeint": "5",
        "save": "Save",
    }
    return _post(fields)


def _post(fields: dict[str, str]) -> bool:
    data = urllib.parse.urlencode(fields, encoding="iso-8859-1").encode("iso-8859-1")
    req = urllib.request.Request(
        f"http://{CMI}/settings_output-E.cgi",
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
    print("=== CoE Digital outputs (E-1..E-16) ===")
    for slot, (src, bez) in DIGITAL_MAPPING.items():
        ok = post_digital(slot, src, bez)
        print(f"  E-{slot:>2}: src={src:<6} bez='{bez}'  {'OK' if ok else 'FAIL'}")
        if not ok:
            fails += 1
        time.sleep(PAUSE)

    print("\n=== CoE Analog outputs (E1..E16) ===")
    for slot, (src, bez) in ANALOG_MAPPING.items():
        if src is None:
            print(f"  E{slot:>2}: (skip)")
            continue
        ok = post_analog(slot, src, bez)
        print(f"  E{slot:>2}:  src={src:<5} bez='{bez}'  {'OK' if ok else 'FAIL'}")
        if not ok:
            fails += 1
        time.sleep(PAUSE)

    digital = len(DIGITAL_MAPPING)
    analog = sum(1 for v in ANALOG_MAPPING.values() if v[0] is not None)
    total = digital + analog
    print(f"\nSummary: {total - fails}/{total} OK  (target {TARGET_IP} node {TARGET_NODE})")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
