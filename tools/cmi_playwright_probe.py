#!/usr/bin/env python3
"""
cmi_playwright_probe.py — Liest CMI CoE-Output-Konfigurationen via Playwright.

Hintergrund: Die CMI-Web-UI (192.168.178.45) rendert Output-Details per jQuery-AJAX
(cmi142.js). Der Detail-Endpunkt fuer E-Outputs ist `settings_output-E.cgi`.
curl bekommt beim SPA-Shell nur ein Skelett — dieses Skript laedt den Fragment-
Endpunkt direkt und parst den fertigen DOM.

LESE-ONLY: Kein Schreibzugriff ans CMI.
Rate-Limit: 5s zwischen Requests, bei HTTP 429 -> 60s Pause + Abbruch.

Ausgabe: tools/cmi_e_outputs.json

Erkannte Architektur (aus cmi142.js):
  Hash-URL #settings_output.cgi?cmioutput=E1 laedt Skelett-Seite,
  dann jQuery.load('settings_output-E.cgi','cmioutput=E1') fuer Detail.
  => Wir laden settings_output-E.cgi direkt (kein Playwright-Overhead noetig,
     aber das Skript nutzt trotzdem Playwright fuer zukuenftige SPA-Targets).
"""

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# --- Konfiguration ---
CMI_BASE = "http://192.168.178.45"
CMI_USER = "admin"
CMI_PASS = "admin"

# CoE Ethernet-Output-Detail-Endpunkt (ermittelt aus cmi142.js loadcmioutputs())
DETAIL_CGI = f"{CMI_BASE}/settings_output-E.cgi"

# Zu lesende Outputs: (Label, cmioutput-Param)
PROBE_TARGETS = [
    ("E1",   "E1"),    # CoE Analog-Output 1 (Aussentemperatur)
    ("E-1",  "E-1"),   # CoE Digital-Output 1 (Phasenwaechter)
    ("E-13", "E-13"),  # CoE Digital-Output 13 (HeizstabWW)
]

REQUEST_DELAY_S = 5        # Sekunden zwischen Requests (CMI Rate-Limit Respekt)
RATE_LIMIT_PAUSE_S = 60    # 60s Pause bei HTTP 429

OUTPUT_FILE = Path(__file__).parent / "cmi_e_outputs.json"

# Regex
IPV4_RE = re.compile(r"\b(\d{1,3}(?:\.\d{1,3}){3})\b")


def parse_e_output(html: str, label: str) -> dict:
    """
    Parst den HTML-Fieldset einer settings_output-E.cgi Antwort.
    Extrahiert: Bezeichnung, IP, Knotennummer, Netzwerkausgang,
    Eingang (Bus+Nr+Name), Uebertragungsbedingungen, Istwert.
    """
    soup = BeautifulSoup(html, "html.parser")

    def val(selector, attr="value"):
        el = soup.select_one(selector)
        if el is None:
            return None
        if attr == "text":
            return el.get_text(strip=True)
        return el.get(attr, "").strip()

    def selected_option(select_id):
        """Gibt value und Text der selected Option zurueck."""
        sel = soup.select_one(f"select#{select_id} option[selected]")
        if sel is None:
            return None, None
        return sel.get("value", ""), sel.get_text(strip=True)

    designation = val("input#outebez")
    ip = val("input#outeip")
    node_nr = val("input#outedev")
    network_output = val("input#outeag")

    # Bus-Selektor (outinb) und Eingang (outin)
    bus_val, bus_text = selected_option("outinb")
    input_val, input_text = selected_option("outin")

    # Uebertragungsbedingung
    cond_val, cond_text = selected_option("outebedd")
    change_threshold = val("input#outebeda")
    blocking_time = val("input#outeblock")
    interval_min = val("input#outeint")

    # Istwert
    actual_value = val("span#outaktval", attr="text")

    # Alle IPs im gesamten HTML
    ips_found = sorted(set(IPV4_RE.findall(html)))

    return {
        "label": label,
        "designation": designation,
        "ip": ip,
        "node_nr": int(node_nr) if node_nr and node_nr.lstrip("-").isdigit() else node_nr,
        "network_output": int(network_output) if network_output and network_output.isdigit() else network_output,
        "input": {
            "bus_value": bus_val,
            "bus_label": bus_text,
            "input_value": input_val,
            "input_label": input_text,
        },
        "transmission": {
            "on_change": cond_val == "0",
            "change_text": cond_text,
            "threshold": change_threshold,
            "blocking_time_sec": int(blocking_time) if blocking_time and blocking_time.isdigit() else blocking_time,
            "interval_min": int(interval_min) if interval_min and interval_min.isdigit() else interval_min,
        },
        "actual_value": actual_value,
        "ips_in_response": ips_found,
    }


def probe_with_playwright(page, label: str, cmioutput: str) -> dict:
    """
    Laedt settings_output-E.cgi?cmioutput=<X> via Playwright und parst das Ergebnis.
    Playwright wird verwendet (statt simplem curl/requests) damit spaetere SPA-Targets
    (bei denen JS-Rendering noetig ist) dasselbe Muster nutzen koennen.
    """
    url = f"{DETAIL_CGI}?cmioutput={cmioutput}"
    print(f"  -> {label}: {url}")

    result = {
        "label": label,
        "cmioutput": cmioutput,
        "url": url,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "pending",
        "http_status": None,
        "raw_html_length": 0,
        "parsed": None,
        "error": None,
    }

    http_status_seen = []

    def on_response(resp):
        if DETAIL_CGI.split("//")[1] in resp.url:
            http_status_seen.append(resp.status)

    page.on("response", on_response)

    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=15_000)
        if resp:
            result["http_status"] = resp.status
            if resp.status == 429:
                result["status"] = "rate_limited"
                result["error"] = f"HTTP 429 — {RATE_LIMIT_PAUSE_S}s Pause"
                print(f"     RATE LIMIT 429 — warte {RATE_LIMIT_PAUSE_S}s")
                time.sleep(RATE_LIMIT_PAUSE_S)
                return result
            if resp.status >= 400:
                result["status"] = "http_error"
                result["error"] = f"HTTP {resp.status}"
                return result

        # Kurz warten damit Inline-JS (cmioutputs etc.) laufen kann
        # Bei diesem Endpunkt ist kein weiteres AJAX noetig — das Fieldset ist sofort da
        html = page.inner_html("body")
        result["raw_html_length"] = len(html)

        if not html.strip():
            result["status"] = "empty_response"
            result["error"] = "Leere Antwort"
            return result

        parsed = parse_e_output(html, label)
        result["parsed"] = parsed
        result["status"] = "ok"

        print(
            f"     OK | bezeichnung={parsed['designation']!r} "
            f"ip={parsed['ip']} node={parsed['node_nr']} "
            f"nw-output={parsed['network_output']} "
            f"actual={parsed['actual_value']!r}"
        )

    except PlaywrightTimeoutError as e:
        result["status"] = "timeout"
        result["error"] = str(e)[:200]
        print(f"     TIMEOUT: {result['error']}")
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)[:300]
        print(f"     ERROR: {result['error']}")
    finally:
        page.remove_listener("response", on_response)

    return result


def main():
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"CMI Playwright Probe — {ts}")
    print(f"Ziel: {CMI_BASE} (auth: {CMI_USER}:***)")
    print(f"Endpunkt: {DETAIL_CGI}")
    print(f"Targets: {[t[0] for t in PROBE_TARGETS]}")
    print()

    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            http_credentials={"username": CMI_USER, "password": CMI_PASS},
            ignore_https_errors=True,
        )
        page = context.new_page()

        for i, (label, cmioutput) in enumerate(PROBE_TARGETS):
            if i > 0:
                print(f"  (warte {REQUEST_DELAY_S}s zwischen Requests — CMI Rate-Limit)")
                time.sleep(REQUEST_DELAY_S)

            result = probe_with_playwright(page, label, cmioutput)
            results.append(result)

            # Bei Rate-Limit nicht weiter hammern
            if result["status"] == "rate_limited":
                print("  Rate-Limit erreicht — breche ab.")
                for rl, rc in PROBE_TARGETS[i + 1:]:
                    results.append({
                        "label": rl,
                        "cmioutput": rc,
                        "url": f"{DETAIL_CGI}?cmioutput={rc}",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "status": "skipped_after_rate_limit",
                        "http_status": None,
                        "raw_html_length": 0,
                        "parsed": None,
                        "error": "Uebersprungen wegen Rate-Limit",
                    })
                break

        context.close()
        browser.close()

    # Zusammenfassung
    all_ips: set[str] = set()
    all_nodes: set[int] = set()
    for r in results:
        p_data = r.get("parsed") or {}
        if p_data.get("ip"):
            all_ips.add(p_data["ip"])
        if p_data.get("node_nr") is not None:
            all_nodes.add(p_data["node_nr"])
        all_ips.update(p_data.get("ips_in_response", []))

    output = {
        "probe_run": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "playwright_version": "1.59.0",
            "cmi_base": CMI_BASE,
            "detail_endpoint": DETAIL_CGI,
            "targets_total": len(PROBE_TARGETS),
            "targets_ok": sum(1 for r in results if r["status"] == "ok"),
            "targets_failed": sum(
                1 for r in results if r["status"] not in ("ok",)
            ),
            "all_ips_seen": sorted(all_ips),
            "all_nodes_seen": sorted(all_nodes),
        },
        "results": results,
    }

    OUTPUT_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    print()
    print(f"Ergebnis: {OUTPUT_FILE}")
    print(f"OK: {output['probe_run']['targets_ok']} / {output['probe_run']['targets_total']}")
    if all_ips:
        print(f"IPs: {sorted(all_ips)}")
    if all_nodes:
        print(f"Knoten: {sorted(all_nodes)}")


if __name__ == "__main__":
    main()
