"""Unit-Tests fuer api/rest.py.

Kein echter CMI-Call, kein echter Postgres.
Verwendet httpx.AsyncClient gegen FastAPI TestClient.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from wp_state_machine.api.rest import AppState, create_app
from wp_state_machine.core.models import Betriebsart, Sensoren, WPState


@pytest.fixture
def app_state() -> AppState:
    """Frischer AppState fuer jeden Test."""
    state = AppState()
    state.dry_run = True
    return state


@pytest.fixture
def app(app_state: AppState):
    return create_app(state=app_state)


@pytest.fixture
async def client(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


class TestHealth:
    @pytest.mark.asyncio
    async def test_health_ok(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "ok" in data
        assert "dry_run" in data
        assert data["dry_run"] is True

    @pytest.mark.asyncio
    async def test_health_dry_run_true(self, client: AsyncClient):
        resp = await client.get("/health")
        assert resp.json()["dry_run"] is True


class TestState:
    @pytest.mark.asyncio
    async def test_state_returns_json(self, client: AsyncClient):
        resp = await client.get("/state")
        assert resp.status_code == 200
        data = resp.json()
        assert "state" in data
        assert "dry_run" in data

    @pytest.mark.asyncio
    async def test_state_initial_unknown(self, client: AsyncClient):
        resp = await client.get("/state")
        assert resp.json()["state"] == WPState.UNKNOWN

    @pytest.mark.asyncio
    async def test_state_after_update(self, app_state: AppState, client: AsyncClient):
        sensoren = Sensoren(verdichter=True, ventil_ww=False)
        await app_state.update_sensoren(sensoren)
        resp = await client.get("/state")
        assert resp.json()["state"] == WPState.HEIZUNG


class TestTelemetry:
    @pytest.mark.asyncio
    async def test_telemetry_returns_json(self, client: AsyncClient):
        resp = await client.get("/telemetry")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_telemetry_has_fields(self, client: AsyncClient):
        resp = await client.get("/telemetry")
        data = resp.json()
        for field in ["vorlauf", "aussen", "warmwasser", "verdichter", "alarm", "wp_state"]:
            assert field in data

    @pytest.mark.asyncio
    async def test_telemetry_with_data(self, app_state: AppState, client: AsyncClient):
        s = Sensoren(vorlauf=35.5, aussen=5.2, warmwasser=50.1)
        await app_state.update_sensoren(s)
        resp = await client.get("/telemetry")
        data = resp.json()
        assert data["vorlauf"] == pytest.approx(35.5)
        assert data["aussen"] == pytest.approx(5.2)


class TestFunctions:
    @pytest.mark.asyncio
    async def test_get_function_f1(self, client: AsyncClient):
        resp = await client.get("/functions/F1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["function"] == "F:1"
        assert data["name"] == "FBHEIZ"

    @pytest.mark.asyncio
    async def test_get_function_f9(self, client: AsyncClient):
        resp = await client.get("/functions/F9")
        assert resp.status_code == 200
        data = resp.json()
        assert data["function"] == "F:9"

    @pytest.mark.asyncio
    async def test_get_function_unknown(self, client: AsyncClient):
        resp = await client.get("/functions/F99")
        assert resp.status_code == 404


class TestSetBetriebsart:
    @pytest.mark.asyncio
    async def test_set_betriebsart_normal_dry_run(self, client: AsyncClient):
        resp = await client.post("/functions/F1/betriebsart", json={"betriebsart": 3})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["dry_run"] is True

    @pytest.mark.asyncio
    async def test_set_betriebsart_all_valid(self, client: AsyncClient):
        for ba in range(1, 8):
            resp = await client.post("/functions/F1/betriebsart", json={"betriebsart": ba})
            assert resp.status_code == 200
            assert resp.json()["success"] is True

    @pytest.mark.asyncio
    async def test_set_betriebsart_invalid_zero(self, client: AsyncClient):
        resp = await client.post("/functions/F1/betriebsart", json={"betriebsart": 0})
        assert resp.status_code == 422  # Pydantic validation error

    @pytest.mark.asyncio
    async def test_set_betriebsart_invalid_eight(self, client: AsyncClient):
        resp = await client.post("/functions/F1/betriebsart", json={"betriebsart": 8})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_set_betriebsart_returns_address(self, client: AsyncClient):
        resp = await client.post("/functions/F1/betriebsart", json={"betriebsart": 3})
        assert resp.json()["address"] == "3E9001301C"


class TestSetNormalsoll:
    @pytest.mark.asyncio
    async def test_set_normalsoll_valid(self, client: AsyncClient):
        resp = await client.post("/functions/F1/normalsoll", json={"temp": 21.0})
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    @pytest.mark.asyncio
    async def test_set_normalsoll_too_low_rejected(self, client: AsyncClient):
        resp = await client.post("/functions/F1/normalsoll", json={"temp": 5.0})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_set_normalsoll_too_high_rejected(self, client: AsyncClient):
        resp = await client.post("/functions/F1/normalsoll", json={"temp": 35.0})
        assert resp.status_code == 422


class TestWWStart:
    @pytest.mark.asyncio
    async def test_ww_start_dry_run(self, client: AsyncClient):
        resp = await client.post("/functions/F9/start")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["dry_run"] is True
        assert "3E80093125" in data["address"]

    @pytest.mark.asyncio
    async def test_ww_start_reason_contains_dry_run(self, client: AsyncClient):
        resp = await client.post("/functions/F9/start")
        assert "DRY_RUN" in resp.json()["reason"]
