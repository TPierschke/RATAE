#!/usr/bin/env python3
"""End-to-end verification of CMI mapping consistency.

Reads all 96 slots (CAN-Inputs + Modbus-Outputs + CoE-Outputs) and prints a
table per slot showing whether the chain is consistent:

  CAN-Input C-N   -> source UVR-Knoten KK / CAN-Out AG, label, live value
  Modbus-Out M-N  -> outmin source, label, address (outmag), target IP/dev
  CoE-Out E-N     -> outein source, label, address (outeag), target IP/dev

Marks rows where source/address mismatch the slot index.
"""
from __future__ import annotations

import base64
import re
import sys
import urllib.request

CMI = "192.168.178.45"
AUTH = "Basic " + base64.b64encode(b"admin:admin").decode()


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"Authorization": AUTH})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read().decode("latin-1")


def fields(html: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in re.finditer(r'name="([a-z_]+)"[^>]*value="([^"]*)"', html):
        out.setdefault(m.group(1), m.group(2))
    return out


def actual_value(html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"&#?\w+;", "", text)
    text = re.sub(r"\s+", " ", text)
    m = re.search(r"Actual value:\s*([^<\n]{1,40})", text)
    return m.group(1).strip() if m else "-"


def check_can_input(slot: str) -> dict:
    f = fields(fetch(f"http://{CMI}/settings_input-C.cgi?cmiinput={slot}"))
    return {
        "label": f.get("incbez", ""),
        "kn":    f.get("inckn", "0"),
        "ag":    f.get("incag", "0"),
        "live":  actual_value(fetch(f"http://{CMI}/settings_input-C.cgi?cmiinput={slot}")),
    }


def check_modbus(slot: str) -> dict:
    h = fetch(f"http://{CMI}/settings_output-M.cgi?cmioutput={slot}")
    f = fields(h)
    src = ""
    m = re.search(r'<select[^>]*name="outmin"[^>]*>(.*?)</select>', h, re.S)
    if m:
        sel = re.search(r'<option value="([^"]*)"[^>]*selected', m.group(1))
        src = sel.group(1) if sel else "0"
    return {
        "label": f.get("outmbez", ""),
        "src":   src,
        "ag":    f.get("outmag", "0"),
        "ip":    f.get("outmip", ""),
        "dev":   f.get("outmdev", "0"),
    }


def check_coe(slot: str) -> dict:
    h = fetch(f"http://{CMI}/settings_output-E.cgi?cmioutput={slot}")
    f = fields(h)
    src = ""
    m = re.search(r'<select[^>]*name="outein"[^>]*>(.*?)</select>', h, re.S)
    if m:
        sel = re.search(r'<option value="([^"]*)"[^>]*selected', m.group(1))
        src = sel.group(1) if sel else "0"
    return {
        "label": f.get("outebez", ""),
        "src":   src,
        "ag":    f.get("outeag", "0"),
        "ip":    f.get("outeip", ""),
        "dev":   f.get("outedev", "0"),
    }


def report_chain(slot_n: int, kind: str) -> None:
    """kind: 'digital' (C-N, M-N, E-N) or 'analog' (CN, MN, EN)"""
    if kind == "digital":
        c, m, e = f"C-{slot_n}", f"M-{slot_n}", f"E-{slot_n}"
    else:
        c, m, e = f"C{slot_n}", f"M{slot_n}", f"E{slot_n}"

    ci = check_can_input(c)
    mi = check_modbus(m)
    ei = check_coe(e)

    expected_ag = str(slot_n - 1)
    src_match_m = mi["src"] == c
    src_match_e = ei["src"] == c
    ag_match_m  = mi["ag"] == expected_ag
    ag_match_e  = ei["ag"] == expected_ag

    line_status = "OK" if (src_match_m and src_match_e and ag_match_m and ag_match_e) else "MISMATCH"
    print(f"--- Slot {slot_n:>2} ({kind}) {line_status} ---")
    print(f"  C: '{ci['label']}' kn={ci['kn']} ag={ci['ag']} live={ci['live']}")
    print(f"  M: '{mi['label']}' src={mi['src']} ag={mi['ag']} ip={mi['ip']} dev={mi['dev']}"
          + ("" if (src_match_m and ag_match_m) else f"  <-- src/ag erwartet={c}/{expected_ag}"))
    print(f"  E: '{ei['label']}' src={ei['src']} ag={ei['ag']} ip={ei['ip']} dev={ei['dev']}"
          + ("" if (src_match_e and ag_match_e) else f"  <-- src/ag erwartet={c}/{expected_ag}"))


def main() -> int:
    print("=== DIGITAL Chain (C-N -> M-N -> E-N), N=1..16 ===\n")
    for n in range(1, 17):
        report_chain(n, "digital")
    print("\n=== ANALOG Chain (CN -> MN -> EN), N=1..16 ===\n")
    for n in range(1, 17):
        if n == 13:
            print(f"--- Slot 13 (analog) SKIP (reserved/empty) ---\n")
            continue
        report_chain(n, "analog")
    return 0


if __name__ == "__main__":
    sys.exit(main())
