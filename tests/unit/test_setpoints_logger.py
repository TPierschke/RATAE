"""Unit-Tests fuer automation/setpoints_logger.py.

Testet den Setpoints-Loop: AppState wird korrekt aktualisiert mit
Funktions-Sollwerten (ww_soll_normal, ww_soll_legio).
"""

from __future__ import annotations

import asyncio
import pytest

from wp_state_machine.api.rest import AppState
from wp_state_machine.automation.setpoints_logger import setpoints_loop


class TestSetpointsLoop:
    @pytest.mark.asyncio
    async def test_setpoints_loop_initializes_appstate(self):
        """Setpoints-Loop setzt app_state.setpoints mit Defaults."""
        app_state = AppState()

        # Initial sollte setpoints leer sein
        assert app_state.setpoints == {}

        # Starte Loop mit kurz Interval (100ms) fuer schnelle Tests
        task = asyncio.create_task(setpoints_loop(app_state, interval=0.1))

        try:
            # Warte bis Loop mindestens einmal durchgelaufen hat
            await asyncio.sleep(0.2)

            # Jetzt sollte setpoints mit Defaults gefuellt sein
            assert app_state.setpoints is not None
            assert "ww_soll_normal" in app_state.setpoints
            assert "ww_soll_legio" in app_state.setpoints
            assert "vorlauf_soll_min" in app_state.setpoints

            # Defaults pruefen
            assert app_state.setpoints["ww_soll_normal"] == 50.0
            assert app_state.setpoints["ww_soll_legio"] == 70.0
            assert app_state.setpoints["vorlauf_soll_min"] == 20.0
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_setpoints_loop_updates_periodically(self):
        """Setpoints-Loop aktualisiert regelmaeßig."""
        app_state = AppState()

        task = asyncio.create_task(setpoints_loop(app_state, interval=0.1))

        try:
            # Erste Update
            await asyncio.sleep(0.15)
            first_setpoints = dict(app_state.setpoints)

            # Zweite Update
            await asyncio.sleep(0.15)
            second_setpoints = dict(app_state.setpoints)

            # Sollwerte sollten gleich sein (da statisch), aber beide sollten gefuellt sein
            assert first_setpoints == second_setpoints
            assert first_setpoints["ww_soll_normal"] == 50.0
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_setpoints_loop_handles_exception(self):
        """Setpoints-Loop haendelt Exceptions gracefully."""
        app_state = AppState()

        # Starte mit config=None (ist OK, wird in Loop verarbeitet)
        task = asyncio.create_task(setpoints_loop(app_state, config=None, interval=0.1))

        try:
            await asyncio.sleep(0.2)
            # Sollte trotz potentieller Fehler laufen und setpoints setzen
            assert app_state.setpoints is not None
            assert "ww_soll_normal" in app_state.setpoints
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
