#!/usr/bin/env python3
"""Bulk setup of CMI CAN-Bus digital inputs C-1..C-16.

Mirrors the UVR's CAN-Bus output order 1:1.
Each slot is POSTed, then read back to verify; stops on first mismatch.

UVR-CAN-Output -> CMI-CAN-Input mapping (verified from old CMI config):
   1 = Phasenwaecht (S10)
   2 = I_Verdichter (S11)
   3 = ND_Schalter1 (S12)
   4 = HD_Schalter  (S13)
   5 = ND_Schalter2 (S14)
   6 = Meldung 8: Heizung
   7 = Ausgang 1: Pumpe-Hzkr
   8 = Ausgang 2: Ladepumpe
   9 = Ausgang 3: Verdichter
  10 = Ausgang 5: Alarm ext           (note: A5 before A4)
  11 = Ausgang 4: MV R0407 FL1
  12 = Ausgang 6: MV R0407 Nach2
  13 = Ausgang 7: Ventil-WW
  14 = Ausgang 8: Heizstab1 (= Heizstab HZ)
  15 = Ausgang 9: Heizstab2 (= Heizstab WW)
  16 = Ausgang 10: Pumpe-Zirku
"""
from __future__ import annotations

import base64
import re
import sys
import time
import urllib.parse
import urllib.request

CMI = "192.168.178.45"
AUTH = "Basic " + base64.b64encode(b"admin:admin").decode()
UVR_NODE = 62
PAUSE = 1.5

# slot -> (bezeichnung, uvr_can_out)
MAPPING: dict[int, tuple[str, int]] = {
    1:  ("DI_Phasenwaecht",   1),
    2:  ("DI_I_Verdichter",   2),
    3:  ("DI_ND_Schalter1",   3),
    4:  ("DI_HD_Schalter",    4),
    5:  ("DI_ND_Schalter2",   5),
    6:  ("DI_Meld_Heizung",   6),
    7:  ("DI_Pumpe_Hzkr",     7),
    8:  ("DI_Ladepumpe",      8),
    9:  ("DI_Verdichter",     9),
    10: ("DI_Alarm_Ext",     10),
    11: ("DI_MVR0407_FL1",   11),
    12: ("DI_MVR0407_Nach2", 12),
    13: ("DI_Ventil_WW",     13),
    14: ("DI_Heizstab_HZ",   14),
    15: ("DI_Heizstab_WW",   15),
    16: ("DI_Pumpe_Zirku",   16),
}


def post(slot: int, bez: str, uvr_can_out: int) -> bool:
    fields = {
        "cmiinput": f"C-{slot}",
        "incbez": bez,
        "inckn": str(UVR_NODE),
        "incag": str(uvr_can_out),
        "inct": "5",
        "inca": "0",
        "incpr": "0",
        "incwt": "1",
        "incadig": "0",
        "save": "Save",
    }
    data = urllib.parse.urlencode(fields, encoding="iso-8859-1").encode("iso-8859-1")
    req = urllib.request.Request(
        f"http://{CMI}/settings_input-C.cgi",
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


def read_back(slot: int) -> dict[str, str]:
    req = urllib.request.Request(
        f"http://{CMI}/settings_input-C.cgi?cmiinput=C-{slot}",
        headers={"Authorization": AUTH},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        html = resp.read().decode("latin-1")
    out: dict[str, str] = {}
    for m in re.finditer(r'name="([a-z_]+)"[^>]*value="([^"]*)"', html):
        out.setdefault(m.group(1), m.group(2))
    return out


def main() -> int:
    fails = 0
    for slot, (bez, uvr) in MAPPING.items():
        ok = post(slot, bez, uvr)
        if not ok:
            print(f"C-{slot:>2}: POST FAIL")
            fails += 1
            continue
        time.sleep(0.7)
        rb = read_back(slot)
        match = (
            rb.get("incbez") == bez
            and rb.get("inckn") == str(UVR_NODE)
            and rb.get("incag") == str(uvr)
            and rb.get("inct") == "5"
        )
        if match:
            print(f"C-{slot:>2}: '{bez}' kn={UVR_NODE} ag={uvr} t=5  OK")
        else:
            print(f"C-{slot:>2}: read-back mismatch -> {rb}")
            fails += 1
        time.sleep(PAUSE - 0.7)

    print(f"\nSummary: {len(MAPPING) - fails}/{len(MAPPING)} OK")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
