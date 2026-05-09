#!/usr/bin/env python3
"""CMI Factory Clear - empty all output/input slots back to default.

Targets:
  - Modbus outputs: M1..M16 (analog) + M-1..M-16 (digital)
  - CoE outputs:    E1..E16 (analog) + E-1..E-16 (digital)
  - CAN-Bus inputs: C1..C16 (analog) + C-1..C-16 (digital)

Each slot becomes: empty label, no source, IP 0.0.0.0, function 0.
Pauses 1.2s between POSTs to stay under the CMI rate-limit.

Run: python3 tools/cmi_factory_clear.py [outputs|inputs|all]
"""
from __future__ import annotations

import base64
import sys
import time
import urllib.parse
import urllib.request

CMI = "192.168.178.45"
AUTH = "Basic " + base64.b64encode(b"admin:admin").decode()
PAUSE = 1.2


def _post(url: str, fields: dict[str, str]) -> tuple[bool, int | None]:
    data = urllib.parse.urlencode(fields, encoding="iso-8859-1").encode("iso-8859-1")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": AUTH,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200, resp.status
    except Exception as exc:
        print(f"  HTTP error: {exc}")
        return False, None


def clear_modbus_output(slot_id: str) -> bool:
    """Modbus output: M1..M16 analog, M-1..M-16 digital."""
    fields = {
        "cmioutput": slot_id,
        "outmbez": "",
        "outmin": "0",
        "outmval": "0",
        "outmip": "0.0.0.0",
        "outmdev": "0",
        "outmfkt": "0",
        "outmag": "0",
        "outmbedd": "0",
        "outmbeda": "0",
        "outmblock": "0",
        "outmint": "0",
        "save": "Save",
    }
    ok, _ = _post(f"http://{CMI}/settings_output.cgi", fields)
    return ok


def clear_coe_output(slot_id: str) -> bool:
    """CoE output: E1..E16 analog, E-1..E-16 digital. Different field names."""
    fields = {
        "cmioutput": slot_id,
        "outebez": "",
        "outein": "0",
        "outeip": "0.0.0.0",
        "outedev": "0",
        "outeag": "0",
        "outebeda": "0",
        "outeblock": "0",
        "outeint": "0",
        "save": "Save",
    }
    ok, _ = _post(f"http://{CMI}/settings_output-E.cgi", fields)
    return ok


def clear_can_input(slot_id: str) -> bool:
    """CAN-Bus input: C1..C16 analog, C-1..C-16 digital."""
    fields = {
        "cmiinput": slot_id,
        "incbez": "",
        "inckn": "0",
        "incag": "0",
        "inct": "0",
        "inca": "0",
        "save": "Save",
    }
    ok, _ = _post(f"http://{CMI}/settings_input-C.cgi", fields)
    return ok


def run_modbus_outputs() -> tuple[int, int]:
    ok = fail = 0
    for n in range(1, 17):
        for slot in (f"M{n}", f"M-{n}"):
            success = clear_modbus_output(slot)
            print(f"  modbus-out {slot:>5}  {'OK' if success else 'FAIL'}")
            ok += 1 if success else 0
            fail += 0 if success else 1
            time.sleep(PAUSE)
    return ok, fail


def run_coe_outputs() -> tuple[int, int]:
    ok = fail = 0
    for n in range(1, 17):
        for slot in (f"E{n}", f"E-{n}"):
            success = clear_coe_output(slot)
            print(f"  coe-out    {slot:>5}  {'OK' if success else 'FAIL'}")
            ok += 1 if success else 0
            fail += 0 if success else 1
            time.sleep(PAUSE)
    return ok, fail


def run_can_inputs() -> tuple[int, int]:
    ok = fail = 0
    for n in range(1, 17):
        for slot in (f"C{n}", f"C-{n}"):
            success = clear_can_input(slot)
            print(f"  can-in     {slot:>5}  {'OK' if success else 'FAIL'}")
            ok += 1 if success else 0
            fail += 0 if success else 1
            time.sleep(PAUSE)
    return ok, fail


def run_outputs() -> tuple[int, int]:
    a, b = run_modbus_outputs()
    c, d = run_coe_outputs()
    return a + c, b + d


def run_inputs() -> tuple[int, int]:
    return run_can_inputs()


def main(argv: list[str]) -> int:
    target = argv[1] if len(argv) > 1 else "all"

    total_ok = total_fail = 0
    if target in ("outputs", "all"):
        print(f"=== Clearing outputs (Modbus + CoE) on {CMI} ===")
        ok, fail = run_outputs()
        total_ok += ok
        total_fail += fail
    if target in ("inputs", "all"):
        print(f"=== Clearing inputs (CAN-Bus) on {CMI} ===")
        ok, fail = run_inputs()
        total_ok += ok
        total_fail += fail

    print(f"\nSummary: ok={total_ok} fail={total_fail}")
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
