# E2E Tests (Playwright)

End-to-end smoke tests that boot the real WP State Machine in a subprocess
and drive a headless Chromium against the dashboard.

## Voraussetzungen

```bash
python3 -c "import playwright"     # muss OK liefern
python3 -m playwright install chromium    # einmalig, ~92 MB
```

Postgres und Modbus werden im Test-Lauf abgeschaltet — kein DB- oder
CMI-Zugriff noetig.

## Ausfuehren

Default `pytest`-Lauf ignoriert `tests/e2e/` (siehe `pyproject.toml`),
weil die E2E-Suite einen Server-Subprocess startet und damit die
asyncio-Fixtures der Unit/Integration-Suite stoeren wuerde.

E2E separat starten:

```bash
PYTHONPATH=src python3 -m pytest tests/e2e -v
```

Erwartet: 3 Tests gruen in 4–5 Sekunden.

## Erweitern

Das Pattern: jede Datei in `tests/e2e/` nutzt die Fixtures `wpsm_server`
(Server-URL, session-scope) und `page` (frisches Chromium-Tab pro Test).
Plain `playwright.sync_api` — kein `pytest-playwright` noetig (PEP 668
verhindert pip-install ohne venv auf homebrew-Python).
