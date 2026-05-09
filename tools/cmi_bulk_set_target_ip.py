#!/usr/bin/env python3
"""
CMI Bulk Set Target IP — aendert die Ziel-IP aller aktiven CoE-Outputs.

Hintergrund: Die TA-CMI hat pro CoE-Output (E1..E64 analog, E-1..E-64 digital)
ein eigenes Form mit IP-Feld. Beim Umzug der CoE-Empfaengerseite muessen
alle aktiven Outputs einzeln umgestellt werden.

Format: GET settings_output-E.cgi?cmioutput=ID liefert das Detail-HTML mit den
aktuellen Werten. POST settings_output.cgi mit den gleichen Feldern + neuer
outeip aendert das Ziel.

Sicherheit:
- Default --dry-run (nur lesen + simulieren)
- --apply muss explizit gesetzt werden
- --only ID erlaubt Test auf einem einzelnen Output
- Rate-Limit: 1.5 sek zwischen Requests (CMI-Budget 1/sek)
- Reverse mit --target 192.168.178.19 jederzeit moeglich
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from typing import Optional

CMI_HOST = "192.168.178.45"
CMI_USER = "admin"
CMI_PASS = "admin"
RATE_LIMIT_SLEEP = 1.5  # CMI-Budget: 1 req/sek

# Aktiv genutzte Outputs (laut Listen-Page mit Bezeichnung)
ACTIVE_ANALOG = [f"E{i}" for i in range(1, 17)]
ACTIVE_DIGITAL = [f"E-{i}" for i in range(1, 17)]
ALL_ACTIVE = ACTIVE_ANALOG + ACTIVE_DIGITAL

FIELD_NAMES = [
    "outebez",
    "outein",
    "outeval",
    "outeip",
    "outedev",
    "outeag",
    "outebedd",
    "outebeda",
    "outeblock",
    "outeint",
]


def auth_header() -> dict[str, str]:
    creds = base64.b64encode(f"{CMI_USER}:{CMI_PASS}".encode()).decode()
    return {"Authorization": f"Basic {creds}"}


def fetch_output(cmioutput: str) -> Optional[dict[str, str]]:
    """Liest aktuelle Form-Werte einer E-Output-Page."""
    url = f"http://{CMI_HOST}/settings_output-E.cgi?cmioutput={cmioutput}"
    req = urllib.request.Request(url, headers=auth_header())
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("iso-8859-1")
    except Exception as exc:
        print(f"  ERROR fetch {cmioutput}: {exc}")
        return None

    if "TOO MANY REQUESTS" in html.upper():
        print("  RATE-LIMIT erreicht — bitte 60s warten")
        return None

    fields: dict[str, str] = {}
    for fld in FIELD_NAMES:
        if fld == "outein":
            # outein ist ein <select>, gesuchter Wert hat selected
            m = re.search(
                rf'<select[^>]*name="{fld}"[^>]*>(.*?)</select>',
                html,
                re.DOTALL,
            )
            if m:
                inner = m.group(1)
                sel = re.search(
                    r'<option\s+value="([^"]+)"\s*selected="selected"',
                    inner,
                )
                if sel:
                    fields[fld] = sel.group(1)
                else:
                    fields[fld] = "0"
        elif fld == "outeval":
            m = re.search(
                rf'<select[^>]*name="{fld}"[^>]*>(.*?)</select>',
                html,
                re.DOTALL,
            )
            if m:
                inner = m.group(1)
                sel = re.search(
                    r'<option\s+value="([^"]+)"\s*selected="selected"',
                    inner,
                )
                fields[fld] = sel.group(1) if sel else "0"
        elif fld == "outebedd":
            m = re.search(
                rf'<select[^>]*name="{fld}"[^>]*>(.*?)</select>',
                html,
                re.DOTALL,
            )
            if m:
                inner = m.group(1)
                sel = re.search(
                    r'<option\s+value="([^"]+)"\s*selected="selected"',
                    inner,
                )
                fields[fld] = sel.group(1) if sel else "0"
        else:
            # Normale input fields
            m = re.search(
                rf'<input[^>]*name="{fld}"[^>]*value="([^"]*)"',
                html,
            )
            if m:
                fields[fld] = m.group(1)

    return fields


def post_output(cmioutput: str, fields: dict[str, str]) -> bool:
    """POST aktualisierte Werte. Gibt True bei HTTP 200 zurueck."""
    url = f"http://{CMI_HOST}/settings_output.cgi"
    data_dict = {"cmioutput": cmioutput, **fields, "save": "Save"}
    # ISO-8859-1 Encoding fuer Umlaute
    data = urllib.parse.urlencode(data_dict, encoding="iso-8859-1").encode("iso-8859-1")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            **auth_header(),
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as exc:
        print(f"  ERROR post {cmioutput}: {exc}")
        return False


def process(target_ip: str, only: Optional[str], apply: bool) -> int:
    outputs = [only] if only else ALL_ACTIVE
    results: list[dict] = []
    n_changed = 0
    n_skipped = 0
    n_failed = 0

    for cmioutput in outputs:
        print(f"\n--- {cmioutput} ---")
        before = fetch_output(cmioutput)
        time.sleep(RATE_LIMIT_SLEEP)
        if before is None:
            n_failed += 1
            results.append({"output": cmioutput, "status": "fetch_failed"})
            continue

        bez = before.get("outebez", "?")
        cur_ip = before.get("outeip", "?")
        print(f"  Bezeichnung: {bez}")
        print(f"  Aktuelle IP: {cur_ip}")

        if cur_ip == target_ip:
            print(f"  → schon {target_ip}, skip")
            n_skipped += 1
            results.append({"output": cmioutput, "status": "already_set", "ip": cur_ip})
            continue

        if not apply:
            print(f"  [DRY-RUN] wuerde aendern: {cur_ip} → {target_ip}")
            results.append(
                {
                    "output": cmioutput,
                    "status": "would_change",
                    "from": cur_ip,
                    "to": target_ip,
                    "fields_before": before,
                }
            )
            continue

        new_fields = {**before, "outeip": target_ip}
        ok = post_output(cmioutput, new_fields)
        time.sleep(RATE_LIMIT_SLEEP)
        if not ok:
            print("  POST FAILED")
            n_failed += 1
            results.append({"output": cmioutput, "status": "post_failed"})
            continue

        # Verify
        after = fetch_output(cmioutput)
        time.sleep(RATE_LIMIT_SLEEP)
        if after and after.get("outeip") == target_ip:
            print(f"  ✓ geaendert: {cur_ip} → {target_ip}")
            n_changed += 1
            results.append(
                {
                    "output": cmioutput,
                    "status": "changed",
                    "from": cur_ip,
                    "to": target_ip,
                }
            )
        else:
            after_ip = after.get("outeip", "?") if after else "?"
            print(f"  ✗ Verifikation fehlgeschlagen: nach POST steht {after_ip}")
            n_failed += 1
            results.append(
                {
                    "output": cmioutput,
                    "status": "verify_failed",
                    "expected": target_ip,
                    "actual": after_ip,
                }
            )

    print()
    print(f"Summary: changed={n_changed}  skipped={n_skipped}  failed={n_failed}")

    out_path = "tools/cmi_bulk_result.json"
    with open(out_path, "w") as f:
        json.dump(
            {"target_ip": target_ip, "applied": apply, "results": results},
            f,
            indent=2,
        )
    print(f"Bericht: {out_path}")

    return 0 if n_failed == 0 else 1


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--target", default="192.168.178.3", help="Ziel-IP (default: Mac)")
    p.add_argument("--only", help="Nur einen Output (z.B. E1)")
    p.add_argument("--apply", action="store_true", help="Echt aendern (sonst nur DRY-RUN)")
    args = p.parse_args()

    print(f"Target IP: {args.target}")
    print(f"Apply: {args.apply}")
    print(f"Outputs: {[args.only] if args.only else f'alle 32 ({ALL_ACTIVE[0]}..{ALL_ACTIVE[-1]})'}")
    print()
    return process(args.target, args.only, args.apply)


if __name__ == "__main__":
    sys.exit(main())
