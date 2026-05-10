"""Integration smoke tests for the Modbus-to-AppState-to-/state flow."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from wp_state_machine.api.rest import AppState, create_app
from wp_state_machine.core.models import WPState
from wp_state_machine.ingest.modbus_slave import COIL_SENSOR_FIELD_MAP, SENSOR_FIELD_MAP


def _modbus_sensor_name(field_name: str, preferred_name: str | None = None) -> str:
    # Prefer the documented name when available, otherwise resolve the current mapping.
    if preferred_name and preferred_name in SENSOR_FIELD_MAP:
        return preferred_name
    return next(name for name, mapped_field in SENSOR_FIELD_MAP.items() if mapped_field == field_name)


def _modbus_coil_name(field_name: str, preferred_name: str | None = None) -> str:
    # Prefer the documented name when available, otherwise resolve the current mapping.
    if preferred_name and preferred_name in COIL_SENSOR_FIELD_MAP:
        return preferred_name
    return next(name for name, mapped_field in COIL_SENSOR_FIELD_MAP.items() if mapped_field == field_name)


def _state_value(data: dict) -> str:
    # Support both the current API field name and the older documented variant.
    return data.get("wp_state", data.get("state"))


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


class TestModbusToState:
    @pytest.mark.asyncio
    async def test_temperature_sensor_propagates_to_state(self, app_state: AppState, client: AsyncClient):
        await app_state.update_from_modbus(_modbus_sensor_name("aussen", "T_Aussen"), 5.2)

        response = await client.get("/state")

        assert response.status_code == 200
        data = response.json()
        assert data["sensoren"]["aussen"] == pytest.approx(5.2)

    @pytest.mark.asyncio
    async def test_verdichter_with_ww_ventil_yields_warmwasser(self, app_state: AppState, client: AsyncClient):
        await app_state.update_coil_from_modbus(_modbus_coil_name("verdichter", "verdichter"), True)
        await app_state.update_coil_from_modbus(_modbus_coil_name("ventil_ww", "ventil_ww"), True)

        response = await client.get("/state")

        assert response.status_code == 200
        data = response.json()
        assert _state_value(data) == WPState.WARMWASSER

    @pytest.mark.asyncio
    async def test_heizstab_ww_without_verdichter_yields_legionellenschutz(
        self, app_state: AppState, client: AsyncClient
    ):
        await app_state.update_coil_from_modbus(_modbus_coil_name("heizstab_ww", "heizstab_ww"), True)

        response = await client.get("/state")

        assert response.status_code == 200
        data = response.json()
        assert _state_value(data) == WPState.LEGIONELLENSCHUTZ

    @pytest.mark.asyncio
    async def test_verdichter_without_ww_ventil_yields_heizung(self, app_state: AppState, client: AsyncClient):
        await app_state.update_coil_from_modbus(_modbus_coil_name("verdichter", "verdichter"), True)
        await app_state.update_coil_from_modbus(_modbus_coil_name("ventil_ww", "ventil_ww"), False)

        response = await client.get("/state")

        assert response.status_code == 200
        data = response.json()
        assert _state_value(data) == WPState.HEIZUNG
