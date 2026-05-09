"""Integration tests for scraper convergence after Modbus revival."""

from __future__ import annotations

from datetime import datetime, timezone

import aiohttp
import pytest
from httpx import ASGITransport, AsyncClient

from wp_state_machine.__main__ import scrape_once
from wp_state_machine.api.rest import AppState, create_app
from wp_state_machine.ingest import web_scraper


class _RecordingPostgres:
    """Minimal stub that records insert_telemetry calls."""

    def __init__(self):
        self.inserts = []
        self.is_connected = True

    async def insert_telemetry(self, record):
        self.inserts.append(record)
        return True


class _StubConfig:
    cmi_timeout = 0.1
    cmi_min_request_interval = 0

    def cmi_auth(self) -> tuple[str, str]:
        return ("user", "pass")

    def cmi_menupage_url(self, page: str) -> str:
        return f"http://test/menupage.cgi?page={page}"


class _FakeResponse:
    def __init__(self, text: str, status: int = 200):
        self._text = text
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self) -> str:
        return self._text


class _FakeClientSession:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def get(self, url: str):
        if "page=3E005806" in url:
            return _FakeResponse("<html>outputs</html>")
        if "page=3E01581E" in url:
            return _FakeResponse("<html>functions</html>")
        raise AssertionError(f"Unexpected URL: {url}")


@pytest.fixture
def app_state() -> AppState:
    state = AppState()
    state.dry_run = True
    return state


@pytest.fixture
def app(app_state):
    return create_app(state=app_state)


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _install_scrape_mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(aiohttp, "ClientSession", _FakeClientSession)
    monkeypatch.setattr(web_scraper, "parse_outputs_page", lambda html: {"verdichter": False})
    monkeypatch.setattr(web_scraper, "parse_functions_overview", lambda html: {"aussen": 5.2})
    monkeypatch.setattr(
        web_scraper,
        "merge_scrape_results",
        lambda outputs, functions: {**functions, **outputs},
    )


@pytest.mark.asyncio
async def test_scrape_inserts_when_modbus_stale(app_state: AppState, monkeypatch: pytest.MonkeyPatch):
    _install_scrape_mocks(monkeypatch)
    app_state.postgres = _RecordingPostgres()

    await scrape_once(_StubConfig(), app_state)

    assert len(app_state.postgres.inserts) == 1


@pytest.mark.asyncio
async def test_scrape_skips_insert_when_modbus_fresh(app_state: AppState, monkeypatch: pytest.MonkeyPatch):
    _install_scrape_mocks(monkeypatch)
    app_state.postgres = _RecordingPostgres()
    app_state.last_modbus_update = datetime.now(timezone.utc)

    await scrape_once(_StubConfig(), app_state)

    assert len(app_state.postgres.inserts) == 0
