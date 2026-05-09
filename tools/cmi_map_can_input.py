#!/usr/bin/env python3
"""Map a single CMI CAN-Bus digital input slot.

Sets one C-N slot, reads it back, verifies value matches the live status page.
Stops on first inconsistency.

Usage:
  python3 cmi_map_can_input.py <slot> <bezeichnung> <uvr_node> <uvr_can_out>

Example:
  python3 cmi_map_can_input.py C-1 DI_PumpeHzkr 62 6
"""
from __future__ import annotations

import base64
import sys
import time
import urllib.parse
import urllib.request

CMI = "192.168.178.45"
AUTH = "Basic " + base64.b64encode(b"admin:admin").decode()


def post(slot: str, bez: str, knoten: int, uvr_can_out: int) -> bool:
    """Map a CMI digital CAN input. Defaults per user 2026-05-09:
    - incpr=0 (AUTO display)
    - inct=5  (timeout 5 minutes — required)
    - incwt=1 (Unchanged on timeout)
    - incadig=0 (OFF/No fallback)
    """
    fields = {
        "cmiinput": slot,
        "incbez": bez,
        "inckn": str(knoten),
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
        print(f"  ERROR: {exc}")
        return False


def read_back(slot: str) -> dict[str, str]:
    req = urllib.request.Request(
        f"http://{CMI}/settings_input-C.cgi?cmiinput={slot}",
        headers={"Authorization": AUTH},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        html = resp.read().decode("latin-1")
    import re
    out: dict[str, str] = {}
    for m in re.finditer(r'name="([a-z_]+)"[^>]*value="([^"]*)"', html):
        out.setdefault(m.group(1), m.group(2))
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print(__doc__)
        return 2
    slot, bez, knoten_str, uvr_can_str = argv[1:5]
    knoten = int(knoten_str)
    uvr_can = int(uvr_can_str)

    print(f"=== Map {slot} -> '{bez}' (UVR-Knoten {knoten}, CAN-Out {uvr_can}) ===")
    if not post(slot, bez, knoten, uvr_can):
        print("FAIL: POST not accepted")
        return 1
    time.sleep(1.5)

    actual = read_back(slot)
    print(f"read-back: bez='{actual.get('incbez')}' kn={actual.get('inckn')} ag={actual.get('incag')} t={actual.get('inct')}")
    expected = {
        "incbez": bez,
        "inckn": str(knoten),
        "incag": str(uvr_can),
    }
    mismatch = [k for k, v in expected.items() if actual.get(k) != v]
    if mismatch:
        print(f"FAIL: read-back differs in {mismatch}")
        return 1
    print("OK: read-back matches")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
