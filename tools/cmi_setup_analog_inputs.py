#!/usr/bin/env python3
"""Bulk setup of CMI CAN-Bus analog inputs C1..C16.

Mirrors the UVR's CAN-Bus analog output order from user's spec 2026-05-09:

  UVR-CAN-Out -> Source                                -> CMI-CAN-Input C-N
   1 = Eingang 1: Temp.Aussen                           AI_T_Aussen
   2 = Eingang 2: TPuffer.o                             AI_T_Puffer_o
   3 = Eingang 3: THeizkr.RL                            AI_T_Heizkr_RL
   4 = Eingang 4: TWW.Speich.                           AI_T_WW_Speich
   5 = NW-Status 21: ANALOG 5                           AI_NW_Stat_21
   6 = FBHEIZ. 4: Traum.SOLL.eff                        AI_Traum_SOLL
   7 = Eingang 7: Heissgas                              AI_T_Heissgas
   8 = Eingang 8: Fluessigkeit                          AI_T_Fluessig
   9 = Eingang 9: Saugleitung                           AI_T_Saugltg
  10 = BETRSTDZ.1 1: Zaehlerstand (Verd. Betr-Std)      AI_BetrStd_Verd
  11 = IMPULSZ.1 1: Zaehlerstand (Verd. Schaltzyklen)   AI_Schaltz_Verd
  12 = FBHEIZ. 2: Status Pumpe                          AI_FBH_PumpStatus
  13 = (empty in user's spec)                           SKIPPED
  14 = Meldung 8: Heizung                               AI_Meld_Heizung
  15 = Meldung 7: Warmwasser                            AI_Meld_WW
  16 = FBHEIZ. 1: VL.Solltemp                           AI_VL_Solltemp
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

# slot -> (bezeichnung, uvr_can_out) -- None bezeichnung = skip
MAPPING: dict[int, tuple[str | None, int]] = {
    1:  ("AI_T_Aussen",       1),
    2:  ("AI_T_Puffer_o",     2),
    3:  ("AI_T_Heizkr_RL",    3),
    4:  ("AI_T_WW_Speich",    4),
    5:  ("AI_NW_Stat_21",     5),
    6:  ("AI_Traum_SOLL",     6),
    7:  ("AI_T_Heissgas",     7),
    8:  ("AI_T_Fluessig",     8),
    9:  ("AI_T_Saugltg",      9),
    10: ("AI_BetrStd_Verd",  10),
    11: ("AI_Schaltz_Verd",  11),
    12: ("AI_FBH_PumpStatus",12),
    13: (None,                0),  # explicitly empty per user spec
    14: ("AI_Meld_Heizung",  14),
    15: ("AI_Meld_WW",       15),
    16: ("AI_VL_Solltemp",   16),
}


def post(slot: int, bez: str, uvr_can_out: int) -> bool:
    fields = {
        "cmiinput": f"C{slot}",
        "incbez": bez,
        "inckn": str(UVR_NODE),
        "incag": str(uvr_can_out),
        "inct": "5",
        "inca": "0",
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
        f"http://{CMI}/settings_input-C.cgi?cmiinput=C{slot}",
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
        if bez is None:
            print(f"C{slot:>2}: (skip - reserved/empty)")
            continue
        ok = post(slot, bez, uvr)
        if not ok:
            print(f"C{slot:>2}: POST FAIL")
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
            print(f"C{slot:>2}: '{bez}' kn={UVR_NODE} ag={uvr} t=5  OK")
        else:
            print(f"C{slot:>2}: read-back mismatch -> {rb}")
            fails += 1
        time.sleep(PAUSE - 0.7)

    total = sum(1 for v in MAPPING.values() if v[0] is not None)
    print(f"\nSummary: {total - fails}/{total} OK")
    return 0 if fails == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
