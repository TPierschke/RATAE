"""Fixtures for the Playwright-based end-to-end tests.

The fixtures start the FastAPI app in a subprocess on a free port and yield
the base URL. Postgres is intentionally disabled via empty WPSM_POSTGRES_URL
so the e2e suite does not require a running database.

Skipped automatically if playwright is not importable or the browser binary
is missing.
"""

from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator

import pytest

playwright = pytest.importorskip("playwright.sync_api")  # noqa: E402
import urllib.error  # noqa: E402
import urllib.request  # noqa: E402


def _free_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_server(url: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, OSError):
            time.sleep(0.2)
    raise TimeoutError(f"Server at {url} did not become ready within {timeout}s")


@pytest.fixture(scope="session")
def wpsm_server() -> Iterator[str]:
    """Boots wp_state_machine on a free port. Yields base URL, then shuts down."""
    port = _free_port()
    env = {
        **os.environ,
        "WPSM_POSTGRES_URL": "",
        "WPSM_MODBUS_ENABLED": "false",
        "WPSM_HOST": "127.0.0.1",
        "WPSM_PORT": str(port),
        "WPSM_LOG_LEVEL": "WARNING",
    }
    proc = subprocess.Popen(
        [sys.executable, "-m", "wp_state_machine", "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        _wait_for_server(f"{base}/api/version", timeout=15.0)
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="session")
def browser():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture
def page(browser):
    context = browser.new_context()
    page = context.new_page()
    try:
        yield page
    finally:
        context.close()
