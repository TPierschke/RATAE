#!/usr/bin/env python3
"""
Bulk-Setup der 16 Digital-Modbus-Outputs am CMI.

Mappt E-1..E-16 auf M-1..M-16 → Mac-Slave Coils 0..15
Function: FC05 (write single coil)
"""
from __future__ import annotations

import base64
import sys
import time
import urllib.parse
import urllib.request

CMI_HOST = "192.168.178.45"
TARGET_IP = "192.168.178.3"
TARGET_DEV = 1
RATE_LIMIT = 1.5

#
# 2026-05-09: Mapping rolled back to sequential 1:1 with UVR CAN-output order.
# Earlier reorg attempt mistook 'C-N' for "network output N" -- 'C-N' actually
# references the CMI digital CAN-input N, which mirrors the UVR's CAN-output
# sequence:
#   C-1..C-5  = S10..S14 (digital inputs from UVR)
#   C-6..C-15 = A1..A10 (digital outputs from UVR)
#   C-16      = empty (reserved)
# Heizstab labels: A8 = Heizstab1 (Heizung), A9 = Heizstab2 (Warmwasser).
#
MAPPING = {
    1:  ("C-1",  "Phasenwaechter"),   # S10
    2:  ("C-2",  "I_Verdichter"),     # S11
    3:  ("C-3",  "ND_Schalter1"),     # S12
    4:  ("C-4",  "HD_Schalter"),      # S13
    5:  ("C-5",  "ND_Schalter2"),     # S14
    6:  ("C-6",  "Pumpe-Hzkr"),       # A1
    7:  ("C-7",  "Ladepumpe"),        # A2
    8:  ("C-8",  "Verdichter"),       # A3 (O_Verdichter)
    9:  ("C-9",  "MV R0407 FL1"),     # A4
    10: ("C-10", "Alarm ext"),        # A5
    11: ("C-11", "MV R0407 Nach2"),   # A6
    12: ("C-12", "Ventil-WW"),        # A7
    13: ("C-13", "Heizstab HZ"),      # A8 Heizstab1 (HZ) -- corrected
    14: ("C-14", "Heizstab WW"),      # A9 Heizstab2 (WW) -- corrected
    15: ("C-15", "Pumpe-Zirku"),      # A10
    16: ("C-16", "Reserve"),          # spare slot
}


def auth() -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(b"admin:admin").decode()}


def post(m_idx: int, can_in: str, bez: str) -> bool:
    cmioutput = f"M-{m_idx}"
    coil = m_idx - 1  # 0-based

    data = urllib.parse.urlencode({
        "cmioutput": cmioutput,
        "outmbez": bez,
        "outmin": can_in,
        "outmval": "0",
        "outmip": TARGET_IP,
        "outmdev": str(TARGET_DEV),
        "outmfkt": "05",         # FC05 write single coil
        "outmag": str(coil),
        "outmbedd": "0",
        "outmbeda": "0",
        "outmblock": "10",
        "outmint": "5",
        "save": "Save",
    }, encoding="iso-8859-1").encode("iso-8859-1")

    req = urllib.request.Request(
        f"http://{CMI_HOST}/settings_output.cgi",
        data=data,
        headers={**auth(), "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as exc:
        print(f"  ERROR M-{m_idx}: {exc}")
        return False


def main() -> int:
    print(f"Konfiguriere {len(MAPPING)} digitale Modbus-Outputs am CMI {CMI_HOST}")
    print(f"Ziel: {TARGET_IP} Slave-ID {TARGET_DEV}, Coil 0..15, FC05")
    print()
    n_ok, n_fail = 0, 0
    for i, (can_in, bez) in MAPPING.items():
        print(f"M-{i:2d}  in={can_in:<5} coil={i-1:2d}  bez='{bez}'", end="  ")
        ok = post(i, can_in, bez)
        time.sleep(RATE_LIMIT)
        print("OK" if ok else "FAIL")
        if ok: n_ok += 1
        else: n_fail += 1
    print()
    print(f"Summary: ok={n_ok}  fail={n_fail}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
