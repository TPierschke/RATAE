#!/usr/bin/env python3
"""
Bulk-Setup der 16 Analog-Modbus-Outputs am CMI.

Mappt E1..E16 (CoE-Bezeichnungen) auf M1..M16 (Modbus-Outputs):
  CMI-Eingang Ci  →  M-Output Mi  →  Mac-Slave Register i-1

Jeder Output: FC16 (write multiple), 16-bit signed, BE, Faktor 10.
Register 0..15 (1-based am CMI = i, am Slave 0-based = i-1 ... aber
pymodbus nutzt 1-basierten Address-Space, also Register 1..16).
"""
from __future__ import annotations

import base64
import sys
import time
import urllib.parse
import urllib.request

CMI_HOST = "192.168.178.45"
TARGET_IP = "192.168.178.3"  # Mac
TARGET_DEV = 1               # Slave-ID
RATE_LIMIT = 1.5

# E_i → (CAN-Eingang, Bezeichnung, Datentyp, Faktor)
# Datentyp: 2=signed16, 3=unsigned16, 4=signed32, 5=unsigned32, 6=float32
MAPPING = {
    1:  ("C1",  "Aussentemp",          2, 10),
    2:  ("C2",  "Vorlauf",              2, 10),
    3:  ("C3",  "Ruecklauf",            2, 10),
    4:  ("C4",  "Warmwasser",           2, 10),
    5:  ("0",   "",                     2, 10),  # ungenutzt
    6:  ("C6",  "TRaum1",               2, 10),
    7:  ("C7",  "Heissgas",             2, 10),
    8:  ("C8",  "Fluessigkeit",         2, 10),
    9:  ("C9",  "Saugleitung",          2, 10),
    10: ("C10", "BetrStdVerdichter",    5, 1),  # uint32 fuer Counter
    11: ("C11", "SchaltungenVerdichter",5, 1),
    12: ("C12", "BetrStdHeizstabFB",    5, 1),
    13: ("C13", "BetrStdHeizstabWW",    5, 1),
    14: ("C14", "MessageFB",            3, 1),  # uint16 Status
    15: ("C15", "MessageWW",            3, 1),
    16: ("C16", "VorlaufSoll",          2, 10),
}


def auth_header() -> dict[str, str]:
    creds = base64.b64encode(b"admin:admin").decode()
    return {"Authorization": f"Basic {creds}"}


def post_modbus_output(m_idx: int, can_in: str, bez: str, dtyp: int, factor: int) -> bool:
    """POST settings_output.cgi fuer M-Output."""
    cmioutput = f"M{m_idx}"
    register = m_idx - 1  # 0-based am Slave
    if not bez or can_in == "0":
        # leer lassen
        return True

    data = urllib.parse.urlencode({
        "cmioutput": cmioutput,
        "outmbez": bez,
        "outmin": can_in,
        "outmval": "0",
        "outmip": TARGET_IP,
        "outmdev": str(TARGET_DEV),
        "outmfkt": "10",         # FC16 write multiple
        "outmag": str(register),
        "outmdtyp": str(dtyp),
        "outmbyteo": "0",        # Big-endian
        "outms": str(factor),
        "outmbedd": "0",         # If change > yes
        "outmbeda": "0.5",
        "outmblock": "10",
        "outmint": "5",
        "save": "Save",
    }, encoding="iso-8859-1").encode("iso-8859-1")

    req = urllib.request.Request(
        f"http://{CMI_HOST}/settings_output.cgi",
        data=data,
        headers={**auth_header(), "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as exc:
        print(f"  ERROR M{m_idx}: {exc}")
        return False


def main() -> int:
    print(f"Konfiguriere {len(MAPPING)} Modbus-Outputs am CMI {CMI_HOST}")
    print(f"Ziel: {TARGET_IP} Slave-ID {TARGET_DEV}, Register 0..15")
    print()
    n_ok, n_fail, n_skip = 0, 0, 0
    for i, (can_in, bez, dtyp, factor) in MAPPING.items():
        if not bez:
            print(f"M{i:2d}  (skipped: leer)")
            n_skip += 1
            continue
        print(f"M{i:2d}  in={can_in:<4} reg={i-1:2d}  dtyp={dtyp} factor={factor}  bez='{bez}'", end="  ")
        ok = post_modbus_output(i, can_in, bez, dtyp, factor)
        time.sleep(RATE_LIMIT)
        if ok:
            print("OK")
            n_ok += 1
        else:
            print("FAIL")
            n_fail += 1
    print()
    print(f"Summary: ok={n_ok}  fail={n_fail}  skipped={n_skip}")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
