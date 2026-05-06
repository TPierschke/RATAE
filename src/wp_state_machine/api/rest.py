"""
api/rest.py — FastAPI REST-Endpunkte.

Alle Schreib-Endpunkte sind durch safety.py whitelist-gesichert.
Im DRY_RUN-Modus werden Schreib-Calls geloggt aber nicht ausgefuehrt.

Endpoints:
  GET  /              Web-UI
  GET  /health        Status aller Sub-Module
  GET  /state         Aktueller WP-State + Sensoren
  GET  /telemetry     Letzte Telemetrie-Daten
  GET  /functions/{id}  Funktion-Detail (F:1, F:9)
  POST /functions/F1/betriebsart   Betriebsart setzen (DRY_RUN)
  POST /functions/F1/normalsoll    Normal-Soll setzen (DRY_RUN)
  POST /functions/F9/start         WW-Boost starten (DRY_RUN)
  GET  /stream        Server-Sent-Events fuer Live-Updates
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Optional

from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

_STATIC_DIR = Path(__file__).parents[1] / "web" / "static"

from wp_state_machine.core.models import (
    Betriebsart,
    HealthStatus,
    Sensoren,
    SetAbsenksollRequest,
    SetBetriebsartRequest,
    SetNormalsollRequest,
    WPState,
    WriteResult,
)
from wp_state_machine.safety import check_write

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App-State (wird bei Startup initialisiert)
# ---------------------------------------------------------------------------


class AppState:
    """Globaler App-State. Wird in tests via Dependency-Injection ersetzt."""

    def __init__(self) -> None:
        self.sensoren: Sensoren = Sensoren()
        self.wp_state: str = WPState.UNKNOWN
        self.dry_run: bool = True
        self.last_update: Optional[datetime] = None
        self.postgres: Any = None  # PostgresStore
        self.mqtt_ok: bool = False
        self.telegram_ok: bool = False
        self.cmi_reachable: Optional[bool] = None
        self._lock = asyncio.Lock()

    async def update_sensoren(self, sensoren: Sensoren) -> None:
        async with self._lock:
            self.sensoren = sensoren
            self.wp_state = sensoren.derive_state()
            self.last_update = datetime.now(timezone.utc)

    async def update_from_modbus(self, sensor_name: str, value: float) -> None:
        """
        Aktualisiert einen einzelnen Sensorwert aus Modbus-Holding-Register.

        Modbus hat Vorrang (primaere Datenquelle) — wird direkt in sensoren
        geschrieben ohne Ueberschreiben aller anderen Felder.
        State-Ableitung wird neu berechnet.
        Thread-safe via asyncio.Lock.
        """
        from wp_state_machine.ingest.modbus_slave import SENSOR_FIELD_MAP
        field = SENSOR_FIELD_MAP.get(sensor_name)
        if field is None:
            # Kein direktes Sensoren-Feld (Counter, Soll-Werte etc.) — nur loggen
            log.debug("Modbus sensor_name=%s value=%s: kein Sensoren-Feld, ignoriere", sensor_name, value)
            return
        async with self._lock:
            # Pydantic-Modell ist immutable — neues Objekt via model_copy
            updated = self.sensoren.model_copy(
                update={field: value, "source": "modbus", "timestamp": datetime.now(timezone.utc)}
            )
            self.sensoren = updated
            self.wp_state = updated.derive_state()
            self.last_update = datetime.now(timezone.utc)
        log.debug("Modbus update: %s=%s -> WP_STATE=%s", field, value, self.wp_state)

    async def update_coil_from_modbus(self, coil_name: str, value: bool) -> None:
        """
        Aktualisiert einen einzelnen Digital-Wert aus Modbus-Coil.

        Thread-safe via asyncio.Lock.
        """
        from wp_state_machine.ingest.modbus_slave import COIL_SENSOR_FIELD_MAP
        field = COIL_SENSOR_FIELD_MAP.get(coil_name)
        if field is None:
            log.debug("Modbus coil_name=%s: kein Sensoren-Feld, ignoriere", coil_name)
            return
        async with self._lock:
            updated = self.sensoren.model_copy(
                update={field: value, "source": "modbus", "timestamp": datetime.now(timezone.utc)}
            )
            self.sensoren = updated
            self.wp_state = updated.derive_state()
            self.last_update = datetime.now(timezone.utc)
        log.debug("Modbus coil: %s=%s -> WP_STATE=%s", field, value, self.wp_state)


# Singleton fuer den laufenden Server
_app_state = AppState()


def get_app_state() -> AppState:
    return _app_state


# ---------------------------------------------------------------------------
# FastAPI-App
# ---------------------------------------------------------------------------


def create_app(state: Optional[AppState] = None) -> FastAPI:
    """
    Erstellt FastAPI-Instanz. state=None nutzt globalen Singleton.
    Tests koennen eigenen AppState injizieren.
    """
    _state = state or _app_state

    app = FastAPI(
        title="WP State Machine",
        description="Zentrale Steuerung Waermepumpe via CMI",
        version="0.1",
    )

    # Statische Web-Assets
    if _STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/")
    async def root():
        """Liefert Web-UI."""
        from fastapi.responses import HTMLResponse
        index = _STATIC_DIR / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return HTMLResponse(
            "<h1>WP State Machine</h1><p>Web-UI nicht gefunden. "
            f"Erwarteter Pfad: {_STATIC_DIR}</p>",
            status_code=503,
        )

    # ---------------------------------------------------------------------------
    # Health
    # ---------------------------------------------------------------------------

    @app.get("/health", response_model=HealthStatus)
    async def health() -> HealthStatus:
        """Status aller Sub-Module."""
        from wp_state_machine.safety import get_whitelist_info

        has_recent_update = (
            _state.last_update is not None
            and (datetime.now(timezone.utc) - _state.last_update).total_seconds() < 120
        )

        ok = has_recent_update or _state.wp_state != WPState.UNKNOWN

        from wp_state_machine.ingest.modbus_slave import modbus_health

        return HealthStatus(
            ok=ok,
            dry_run=_state.dry_run,
            cmi_reachable=_state.cmi_reachable,
            postgres_ok=_state.postgres.is_connected if _state.postgres else None,
            mqtt_ok=_state.mqtt_ok if _state.mqtt_ok else None,
            telegram_ok=_state.telegram_ok if _state.telegram_ok else None,
            last_telemetry=_state.last_update,
            wp_state=_state.wp_state,
            modules={
                "safety_whitelist_count": str(len(get_whitelist_info())),
                "dry_run": str(_state.dry_run),
                "modbus_last_update": modbus_health.to_dict().get("last_update") or "never",
                "modbus_source_ip": modbus_health.to_dict().get("last_source_ip") or "none",
                "modbus_registers": str(modbus_health.registers_received),
                "modbus_coils": str(modbus_health.coils_received),
            },
        )

    # ---------------------------------------------------------------------------
    # State + Telemetry
    # ---------------------------------------------------------------------------

    @app.get("/state")
    async def get_state() -> dict[str, Any]:
        """Aktueller WP-State und alle Sensor-Werte."""
        return {
            "state": _state.wp_state,
            "dry_run": _state.dry_run,
            "last_update": _state.last_update.isoformat() if _state.last_update else None,
            "sensoren": _state.sensoren.model_dump(),
        }

    @app.get("/telemetry")
    async def get_telemetry() -> dict[str, Any]:
        """Aktuelle Telemetrie (Sensor-Snapshot)."""
        s = _state.sensoren
        return {
            "timestamp": s.timestamp.isoformat(),
            "vorlauf": s.vorlauf,
            "ruecklauf": s.ruecklauf,
            "warmwasser": s.warmwasser,
            "aussen": s.aussen,
            "heissgas": s.heissgas,
            "verdichter": s.verdichter,
            "ventil_ww": s.ventil_ww,
            "heizstab_hz": s.heizstab_hz,
            "heizstab_ww": s.heizstab_ww,
            "alarm": s.alarm,
            "betriebsart": int(s.betriebsart) if s.betriebsart else None,
            "wp_state": _state.wp_state,
        }

    @app.get("/functions/{function_id}")
    async def get_function(function_id: str) -> dict[str, Any]:
        """Detail einer Funktion (F1, F9)."""
        fn = function_id.upper().lstrip("F")
        if fn == "1":
            return {
                "function": "F:1",
                "name": "FBHEIZ",
                "betriebsart": int(_state.sensoren.betriebsart)
                if _state.sensoren.betriebsart
                else None,
                "betriebsart_name": _state.sensoren.betriebsart.name
                if _state.sensoren.betriebsart
                else None,
                "vorlauf_ist": _state.sensoren.vorlauf,
                "aussen": _state.sensoren.aussen,
            }
        elif fn == "9":
            return {
                "function": "F:9",
                "name": "WW_ANF.2",
                "warmwasser_ist": _state.sensoren.warmwasser,
                "verdichter": _state.sensoren.verdichter,
                "ventil_ww": _state.sensoren.ventil_ww,
            }
        raise HTTPException(status_code=404, detail=f"Funktion {function_id} unbekannt")

    # ---------------------------------------------------------------------------
    # Schreib-Endpunkte (alle DRY_RUN gesichert)
    # ---------------------------------------------------------------------------

    @app.post("/functions/F1/betriebsart", response_model=WriteResult)
    async def set_betriebsart(req: SetBetriebsartRequest) -> WriteResult:
        """
        Setzt Betriebsart F:1 FBHEIZ.
        Im DRY_RUN: Whitelist-Check + Audit-Log, kein echter CMI-Call.
        """
        safety_result = check_write("3E9001301C", req.betriebsart)

        if _state.postgres:
            await _state.postgres.insert_function_audit(
                address="3E9001301C",
                value=float(req.betriebsart),
                whitelist_ok=safety_result.allowed,
                dry_run=_state.dry_run,
                cmi_called=False,
                cmi_response=None,
                success=safety_result.allowed and _state.dry_run,
                reason=safety_result.reason,
                caller="api/rest",
            )

        if not safety_result.allowed:
            return WriteResult(
                success=False,
                dry_run=_state.dry_run,
                address="3E9001301C",
                value=req.betriebsart,
                reason=safety_result.reason,
            )

        if _state.dry_run:
            log.info("DRY_RUN: set_betriebsart(%d) — kein echter CMI-Call", req.betriebsart)
            return WriteResult(
                success=True,
                dry_run=True,
                address="3E9001301C",
                value=req.betriebsart,
                reason=f"DRY_RUN: Betriebsart {req.betriebsart} waere gesetzt worden",
            )

        # LIVE (nur wenn DRY_RUN=False explizit gesetzt)
        raise HTTPException(status_code=503, detail="LIVE-Modus noch nicht implementiert — DRY_RUN=True setzen")

    @app.post("/functions/F1/normalsoll", response_model=WriteResult)
    async def set_normalsoll(req: SetNormalsollRequest) -> WriteResult:
        """Setzt Normal-Soll-Temperatur F:1 FBHEIZ."""
        safety_result = check_write("3EB001300C", req.temp)

        if not safety_result.allowed:
            return WriteResult(
                success=False,
                dry_run=_state.dry_run,
                address="3EB001300C",
                value=req.temp,
                reason=safety_result.reason,
            )

        if _state.dry_run:
            return WriteResult(
                success=True,
                dry_run=True,
                address="3EB001300C",
                value=req.temp,
                reason=f"DRY_RUN: Normal-Soll {req.temp}°C waere gesetzt worden",
            )

        raise HTTPException(status_code=503, detail="LIVE nicht implementiert")

    @app.post("/functions/F9/start", response_model=WriteResult)
    async def start_ww_boost() -> WriteResult:
        """
        Startet WW-Bereitung via F:9 WW_ANF.2.
        Verdichter-WW-Boost mit eingebauter Heizstab-Eskalation.
        Kein manueller Stop noetig — WP stoppt bei 70°C selbst.
        """
        safety_result = check_write("3E80093125", 1)

        if _state.postgres:
            await _state.postgres.insert_function_audit(
                address="3E80093125",
                value=1.0,
                whitelist_ok=safety_result.allowed,
                dry_run=_state.dry_run,
                cmi_called=False,
                cmi_response=None,
                success=safety_result.allowed and _state.dry_run,
                reason=safety_result.reason,
                caller="api/rest",
            )

        if not safety_result.allowed:
            return WriteResult(
                success=False,
                dry_run=_state.dry_run,
                address="3E80093125",
                value=1,
                reason=safety_result.reason,
            )

        if _state.dry_run:
            log.info("DRY_RUN: WW-Boost starten — kein echter CMI-Call")
            return WriteResult(
                success=True,
                dry_run=True,
                address="3E80093125",
                value=1,
                reason="DRY_RUN: WW-Boost waere gestartet worden (F:9 WW_ANF.2 STARTEN=1)",
            )

        raise HTTPException(status_code=503, detail="LIVE nicht implementiert")

    # ---------------------------------------------------------------------------
    # Server-Sent-Events fuer Live-Updates
    # ---------------------------------------------------------------------------

    @app.get("/stream")
    async def stream_events() -> StreamingResponse:
        """
        Server-Sent-Events: sendet alle 3s aktuellen State.
        Clients: EventSource('http://.../stream')
        """

        async def event_generator() -> AsyncGenerator[str, None]:
            while True:
                data = {
                    "state": _state.wp_state,
                    "dry_run": _state.dry_run,
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "vorlauf": _state.sensoren.vorlauf,
                    "aussen": _state.sensoren.aussen,
                    "warmwasser": _state.sensoren.warmwasser,
                    "verdichter": _state.sensoren.verdichter,
                    "alarm": _state.sensoren.alarm,
                }
                yield f"data: {json.dumps(data)}\n\n"
                await asyncio.sleep(3)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app
