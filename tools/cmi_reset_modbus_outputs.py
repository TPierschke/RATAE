#!/usr/bin/env python3
"""
CMI Modbus-Output-Reset: Setzt alle M1..M16 (analog) und M-1..M-16 (digital)
auf outmin=0 (kein Source) und faktor=0. Damit verschwindet die alte
"Geister-Konfig" die parallel zur sichtbaren UI-Konfig existiert.

Anschliessend laeuft cmi_bulk_modbus_setup_v2.py fuer die saubere Neukonfig.
"""
from __future__ import annotations

import base64
import sys
import time
import urllib.parse
import urllib.request

CMI_HOST = "192.168.178.45"
RATE_LIMIT = 1.2


def auth_header() -> dict[str, str]:
    creds = base64.b64encode(b"admin:admin").decode()
    return {"Authorization": f"Basic {creds}"}


def reset_slot(slot: str) -> bool:
    """Setzt outmin=0 und factor=1 fuer den gegebenen Slot."""
    is_digital = slot.startswith("M-")
    data = {
        "cmioutput": slot,
        "outmbez":   "",
        "outmin":    "0",          # KEIN Source — leerer Output
        "outmval":   "0",
        "outmip":    "",
        "outmdev":   "0",
        "outmfkt":   "00" if is_digital else "00",  # Function = "-"
        "outmag":    "0",
        "outmdtyp":  "2",
        "outmbyteo": "0",
        "outms":     "1",
        "outmbedd":  "0",
        "outmbeda":  "0.5",
        "outmblock": "10",
        "outmint":   "300",
        "save":      "Save",
    }
    body = urllib.parse.urlencode(data, encoding="iso-8859-1").encode("iso-8859-1")
    req = urllib.request.Request(
        f"http://{CMI_HOST}/settings_output.cgi",
        data=body,
        headers={**auth_header(), "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as exc:
        print(f"  ERROR {slot}: {exc}")
        return False


def main() -> int:
    print(f"Reset Modbus-Outputs am CMI {CMI_HOST}")
    print("Loescht outmin (Source) auf 0 fuer M1..M16 und M-1..M-16.")
    print()
    n_ok, n_fail = 0, 0
    for prefix in ["M", "M-"]:
        for i in range(1, 17):
            slot = f"{prefix}{i}"
            ok = reset_slot(slot)
            if ok:
                n_ok += 1
                print(f"  {slot:5s} reset OK")
            else:
                n_fail += 1
                print(f"  {slot:5s} reset FAILED")
            time.sleep(RATE_LIMIT)
    print()
    print(f"Reset abgeschlossen: {n_ok} OK, {n_fail} FAIL")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
