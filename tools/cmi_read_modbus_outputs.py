#!/usr/bin/env python3
"""
Liest die aktuelle Konfig der Modbus-Outputs am CMI aus (read-only).
Schreibt einen Markdown-Bericht nach docs/CMI-MODBUS-CONFIG-IST.md.
"""
from __future__ import annotations

import base64
import re
import sys
import time
import urllib.request

CMI_HOST = "192.168.178.45"
RATE_LIMIT = 0.8


def auth_header() -> dict[str, str]:
    creds = base64.b64encode(b"admin:admin").decode()
    return {"Authorization": f"Basic {creds}"}


def fetch(cmioutput: str) -> str:
    url = f"http://{CMI_HOST}/settings_output-M.cgi?cmioutput={cmioutput}"
    req = urllib.request.Request(url, headers=auth_header())
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.read().decode("iso-8859-1", errors="replace")


def get_input(field_id: str, html: str) -> str | None:
    m = re.search(rf'id="{field_id}"[^>]*value="([^"]*)"', html)
    return m.group(1) if m else None


def get_select(name: str, html: str) -> str | None:
    block = re.search(rf'name="{name}"[^>]*>(.*?)</select>', html, re.DOTALL)
    if not block:
        return None
    sel = re.search(r'value="([^"]*)"\s*selected', block.group(1))
    return sel.group(1) if sel else None


def get_actval(html: str) -> str | None:
    m = re.search(r"id='outaktval'>([^<]*)<", html)
    return m.group(1) if m else None


def parse(slot: str) -> dict:
    html = fetch(slot)
    return {
        "slot": slot,
        "bez": get_input("outmbez", html),
        "source": get_select("outmin", html),
        "ip": get_input("outmip", html),
        "dev": get_input("outmdev", html),
        "fkt": get_select("outmfkt", html),
        "addr": get_input("outmag", html),
        "dtyp": get_select("outmdtyp", html),
        "byteo": get_select("outmbyteo", html),
        "factor": get_input("outms", html),
        "actval": get_actval(html),
    }


FKT_LBL = {"00": "-", "05": "FC05 single coil", "06": "FC06 single reg", "0F": "FC15 multi coil", "10": "FC16 multi regs"}
DTYP_LBL = {"0": "i8", "1": "u8", "2": "i16", "3": "u16", "4": "i32", "5": "u32", "6": "f32"}


def main() -> int:
    print(f"Lese CMI Modbus-Outputs von {CMI_HOST}\n")
    rows: list[dict] = []
    for i in range(1, 17):
        slot = f"M{i}"
        try:
            row = parse(slot)
            rows.append(row)
            print(f"  {slot:5s} bez='{row['bez'] or '':20s}' src={row['source']:>5} addr={row['addr']:>3} f={row['factor']} actval={row['actval']}")
        except Exception as exc:
            print(f"  {slot}: ERROR {exc}")
        time.sleep(RATE_LIMIT)
    print()
    digital: list[dict] = []
    for i in range(1, 17):
        slot = f"M-{i}"
        try:
            row = parse(slot)
            digital.append(row)
            print(f"  {slot:5s} bez='{row['bez'] or '':20s}' src={row['source']:>5} addr={row['addr']:>3} f={row['factor']} actval={row['actval']}")
        except Exception as exc:
            print(f"  {slot}: ERROR {exc}")
        time.sleep(RATE_LIMIT)

    out_path = "/Users/thp/source/repos/wp-state-machine/docs/CMI-MODBUS-CONFIG-IST.md"
    lines = [
        "# CMI Modbus-Output IST-Konfiguration",
        "",
        f"Quelle: `http://{CMI_HOST}/settings_output-M.cgi` — read-only ausgelesen.",
        "",
        "## Analog (M1..M16) — Holding-Register",
        "",
        "| Slot | Bezeichnung | Source | Adr | FC | DType | Faktor | actval |",
        "|------|------------|--------|----|----|-------|--------|--------|",
    ]
    for r in rows:
        lines.append(
            f"| {r['slot']} | {r['bez'] or ''} | {r['source']} | {r['addr']} | "
            f"{FKT_LBL.get(r['fkt'], r['fkt'])} | {DTYP_LBL.get(r['dtyp'], r['dtyp'])} | {r['factor']} | {r['actval']} |"
        )
    lines += ["", "## Digital (M-1..M-16) — Coils", "",
              "| Slot | Bezeichnung | Source | Adr | FC | actval |",
              "|------|------------|--------|----|----|--------|"]
    for r in digital:
        lines.append(
            f"| {r['slot']} | {r['bez'] or ''} | {r['source']} | {r['addr']} | "
            f"{FKT_LBL.get(r['fkt'], r['fkt'])} | {r['actval']} |"
        )
    open(out_path, "w").write("\n".join(lines) + "\n")
    print(f"\nReport geschrieben nach: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
