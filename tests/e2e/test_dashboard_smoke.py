"""End-to-end smoke tests for the WP State Machine dashboard.

Starts the real FastAPI app on a free port (no Postgres, no Modbus) and
loads it in a headless Chromium. Verifies the dashboard renders without
JavaScript errors and the /api/version payload is reachable from the
browser context.
"""

from __future__ import annotations

import json

import pytest


def test_dashboard_serves_index(page, wpsm_server):
    response = page.goto(wpsm_server + "/")
    assert response is not None
    assert response.status == 200, f"GET / returned {response.status}"
    # The static index.html should produce a non-empty document.
    assert page.content().strip() != ""


def test_api_version_reachable_from_browser_context(page, wpsm_server):
    page.goto(wpsm_server + "/")
    # Trigger fetch from inside the page so we exercise the same path the
    # frontend uses, not an out-of-band HTTP call.
    payload = page.evaluate(
        """async () => {
            const r = await fetch('/api/version');
            return { status: r.status, body: await r.json() };
        }"""
    )
    assert payload["status"] == 200
    body = payload["body"]
    assert "backend" in body
    assert "frontend" in body
    assert "build" in body


def test_dashboard_has_no_console_errors(page, wpsm_server):
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.on(
        "console",
        lambda msg: errors.append(msg.text) if msg.type == "error" else None,
    )

    page.goto(wpsm_server + "/", wait_until="domcontentloaded")
    # Give the dashboard a short window for initial fetches to land before
    # asserting. networkidle would block forever because the SSE stream stays
    # open by design.
    page.wait_for_timeout(1500)

    assert errors == [], f"Browser logged errors: {json.dumps(errors, indent=2)}"
