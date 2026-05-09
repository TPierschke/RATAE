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
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

_STATIC_DIR = Path(__file__).parents[1] / "web" / "static"

from wp_state_machine import __version__ as _BACKEND_VERSION
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


def _read_frontend_version() -> str:
    """Reads frontend semver from web/static/version.json. 'unknown' on error."""
    try:
        with (_STATIC_DIR / "version.json").open(encoding="utf-8") as f:
            return str(json.load(f).get("frontend", "unknown"))
    except (OSError, json.JSONDecodeError):
        return "unknown"


_FRONTEND_VERSION = _read_frontend_version()

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App-State (wird bei Startup initialisiert)
# ---------------------------------------------------------------------------


_AVAILABLE_THEMES = ("live", "c", "d", "e", "f", "g", "h", "i", "j", "k")


class ThemeRequest(BaseModel):
    theme: str


class AppState:
    """Globaler App-State. Wird in tests via Dependency-Injection ersetzt."""

    theme: str = "live"
    theme_path: Path

    def __init__(self) -> None:
        self.sensoren: Sensoren = Sensoren()
        self.wp_state: str = WPState.UNKNOWN
        self.dry_run: bool = True
        self.last_update: Optional[datetime] = None
        self.last_modbus_update: Optional[datetime] = None
        self.postgres: Any = None  # PostgresStore
        self.mqtt_ok: bool = False
        self.telegram_ok: bool = False
        self.cmi_reachable: Optional[bool] = None
        self.config: Any = None  # Config (gesetzt beim Startup)
        self.startup_time: Optional[str] = None  # ISO8601 UTC, gesetzt in __main__.main()
        self.setpoints: dict[str, Any] = {}  # Function setpoints (ww_soll_normal, raum_ist, etc.)
        self.setpoints_last_update: Optional[datetime] = None  # Timestamp of last setpoints update
        self.setpoints_path = Path("~/.config/wp-state-machine/setpoints.json").expanduser()
        try:
            if self.setpoints_path.exists():
                data = json.loads(self.setpoints_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.setpoints = data
        except (OSError, json.JSONDecodeError, TypeError):
            pass
        self.theme = "live"
        self.theme_path = Path("~/.config/wp-state-machine/theme.json").expanduser()
        try:
            if self.theme_path.exists():
                data = json.loads(self.theme_path.read_text(encoding="utf-8"))
                theme = data.get("theme")
                if theme in _AVAILABLE_THEMES:
                    self.theme = theme
        except (OSError, json.JSONDecodeError, TypeError):
            pass
        self._lock = asyncio.Lock()

    async def save_setpoints(self, setpoints: dict[str, Any]) -> None:
        """Persist setpoints atomically to ~/.config/wp-state-machine/setpoints.json."""
        async with self._lock:
            self.setpoints = setpoints
            self.setpoints_last_update = datetime.now(timezone.utc)
            self.setpoints_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.setpoints_path.with_suffix(self.setpoints_path.suffix + ".tmp")
            tmp_path.write_text(json.dumps(setpoints), encoding="utf-8")
            tmp_path.replace(self.setpoints_path)

    async def set_theme(self, theme: str) -> None:
        if theme not in _AVAILABLE_THEMES:
            raise ValueError(f"invalid theme: {theme}")
        async with self._lock:
            self.theme_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.theme_path.with_suffix(self.theme_path.suffix + ".tmp")
            tmp_path.write_text(json.dumps({"theme": theme}), encoding="utf-8")
            tmp_path.replace(self.theme_path)
            self.theme = theme

    async def update_sensoren(self, sensoren: Sensoren) -> None:
        """
        Web-Scraper-Update. Modbus = Primaerquelle: solange Modbus frisch
        liefert, werden seine Felder vom Scraper NICHT ueberschrieben.
        Nur Felder die Modbus nicht (mehr) liefert werden gemerged.
        """
        from wp_state_machine.ingest.modbus_slave import (
            MODBUS_FRESHNESS_SECONDS,
            MODBUS_OWNED_FIELDS,
        )
        async with self._lock:
            modbus_fresh = (
                self.last_modbus_update is not None
                and (datetime.now(timezone.utc) - self.last_modbus_update).total_seconds()
                < MODBUS_FRESHNESS_SECONDS
            )
            scraper_data = sensoren.model_dump(exclude_none=True)
            if modbus_fresh:
                for f in MODBUS_OWNED_FIELDS:
                    scraper_data.pop(f, None)
                # source/timestamp nicht ueberschreiben — Modbus haelt Hand drauf
                scraper_data.pop("source", None)
                scraper_data.pop("timestamp", None)
            merged = self.sensoren.model_copy(update=scraper_data)
            self.sensoren = merged
            self.wp_state = merged.derive_state()
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
            self.last_modbus_update = self.last_update
        log.debug("Modbus update: %s=%s -> WP_STATE=%s", field, value, self.wp_state)

    async def update_coil_from_modbus(self, coil_name: str, value: bool) -> None:
        """
        Aktualisiert einen einzelnen Digital-Wert aus Modbus-Coil.

        Thread-safe via asyncio.Lock. Triggert Edge-Aktionen direkt:
          - alarm False->True: handle_alarm_edge (Verifikation + 4-fach-Telegram)
          - verdichter False->True: handle_verdichter_edge (Mapping-Audit)
        """
        from wp_state_machine.ingest.modbus_slave import COIL_SENSOR_FIELD_MAP
        field = COIL_SENSOR_FIELD_MAP.get(coil_name)
        if field is None:
            log.debug("Modbus coil_name=%s: kein Sensoren-Feld, ignoriere", coil_name)
            return
        async with self._lock:
            prev_value = getattr(self.sensoren, field, None)
            updated = self.sensoren.model_copy(
                update={field: value, "source": "modbus", "timestamp": datetime.now(timezone.utc)}
            )
            self.sensoren = updated
            self.wp_state = updated.derive_state()
            self.last_update = datetime.now(timezone.utc)
            self.last_modbus_update = self.last_update
        log.debug("Modbus coil: %s=%s -> WP_STATE=%s", field, value, self.wp_state)

        # Edge-Triggers: SOFORT, ohne Loop. Fire-and-forget asyncio.create_task.
        if value is True and prev_value is not True and self.config is not None:
            if field == "alarm":
                from wp_state_machine.automation.coil_audit import handle_alarm_edge
                asyncio.create_task(handle_alarm_edge(self, self.config))
            elif field == "verdichter":
                from wp_state_machine.automation.coil_audit import handle_verdichter_edge
                asyncio.create_task(handle_verdichter_edge(self, self.config))

    async def get_snapshot(self) -> tuple["Sensoren", str]:
        """Atomic (sensoren, wp_state) read under the lock — prevents readers
        from observing a torn pair when a writer commits between two field
        accesses.
        """
        async with self._lock:
            return self.sensoren, self.wp_state


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
        version=_BACKEND_VERSION,
    )

    # Statische Web-Assets
    if _STATIC_DIR.exists():
        app.mount("/ui", StaticFiles(directory=str(_STATIC_DIR)), name="ui")

    @app.get("/api/version")
    async def api_version() -> dict[str, Any]:
        """Version-Info fuer Frontend-Footer und Debugging.

        backend  = Backend semver from wp_state_machine.__version__.
        frontend = Frontend semver from web/static/version.json.
        build    = Server-Startup-Zeit (ISO8601 UTC). Wechselt mit jedem Restart.
        """
        return {
            "backend": _BACKEND_VERSION,
            "frontend": _FRONTEND_VERSION,
            "build": _state.startup_time,
        }

    @app.get("/api/theme")
    async def api_theme() -> dict[str, Any]:
        return {
            "theme": _state.theme,
            "available": list(_AVAILABLE_THEMES),
        }

    @app.post("/api/theme")
    async def api_set_theme(req: ThemeRequest) -> dict[str, Any]:
        try:
            await _state.set_theme(req.theme)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "theme": _state.theme,
            "saved": True,
        }

    @app.get("/t/{theme}")
    async def theme_preview(theme: str):
        if theme not in _AVAILABLE_THEMES:
            raise HTTPException(status_code=404, detail="theme not found")
        if theme == "live":
            return RedirectResponse(url="/")
        path = _STATIC_DIR / f"mockup-{theme}.html"
        if path.exists():
            return FileResponse(str(path))
        raise HTTPException(status_code=404, detail="theme preview not found")

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
        """Aktueller WP-State, Sensor-Werte und Funktions-Sollwerte."""
        return {
            "state": _state.wp_state,
            "dry_run": _state.dry_run,
            "last_update": _state.last_update.isoformat() if _state.last_update else None,
            "sensoren": _state.sensoren.model_dump(),
            "setpoints": _state.setpoints,
        }

    @app.get("/api/reset")
    async def api_reset() -> Response:
        """
        Einmal-Aufruf zum Aufraeumen alter PWA/Service-Worker-Caches im Browser.
        Schickt 'Clear-Site-Data', danach ist alles weg, Browser laedt frisch.
        """
        from fastapi.responses import HTMLResponse
        body = """<!doctype html><html lang="de"><head><meta charset="utf-8">
<title>Reset</title>
<meta http-equiv="refresh" content="2;url=/">
<style>body{font-family:-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;
padding:2rem;text-align:center}a{color:#38bdf8}</style></head>
<body><h1>Cache zurueckgesetzt</h1>
<p>Service-Worker und Caches werden geloescht. Weiterleitung in 2 Sekunden ...</p>
<p>Falls nicht: <a href="/">zur Startseite</a></p>
<script>
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.getRegistrations().then(rs => rs.forEach(r => r.unregister()));
}
if (window.caches) caches.keys().then(ks => ks.forEach(k => caches.delete(k)));
</script>
</body></html>"""
        return HTMLResponse(
            content=body,
            headers={
                "Clear-Site-Data": '"cache", "storage"',
                "Cache-Control": "no-store",
            },
        )

    @app.post("/scrape/run")
    async def scrape_run() -> dict[str, Any]:
        """Manueller Web-Scrape (UI-Button). Holt eine Momentaufnahme von der CMI-Web-UI."""
        if _state.config is None:
            raise HTTPException(status_code=503, detail="Config nicht initialisiert")
        from wp_state_machine.__main__ import scrape_once
        try:
            merged = await scrape_once(_state.config, _state)
            return {"ok": True, "values": merged}
        except Exception as exc:
            log.error("Scrape-Endpoint-Fehler: %s", exc)
            raise HTTPException(status_code=502, detail=f"Scrape fehlgeschlagen: {exc}")

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

    async def _execute_write(address: str, value: int | float, label: str) -> WriteResult:
        """
        Generischer CMI-Schreib-Pfad: Whitelist → DRY/LIVE → Audit-Insert (ein Eintrag pro Versuch).
        """
        safety_result = check_write(address, value)

        async def _audit(cmi_called: bool, response_text: Optional[str], success: bool, reason: str) -> None:
            if _state.postgres and _state.postgres.is_connected:
                await _state.postgres.insert_function_audit(
                    address=address,
                    value=float(value),
                    whitelist_ok=safety_result.allowed,
                    dry_run=_state.dry_run,
                    cmi_called=cmi_called,
                    cmi_response=response_text,
                    success=success,
                    reason=reason,
                    caller="api/rest",
                )

        if not safety_result.allowed:
            await _audit(cmi_called=False, response_text=None, success=False, reason=safety_result.reason)
            return WriteResult(
                success=False, dry_run=_state.dry_run,
                address=address, value=value, reason=safety_result.reason,
            )

        if _state.dry_run:
            log.info("DRY_RUN: %s addr=%s value=%s", label, address, value)
            reason = f"DRY_RUN: {label} ({value}) waere geschrieben worden"
            await _audit(cmi_called=False, response_text=None, success=True, reason=reason)
            return WriteResult(
                success=True, dry_run=True, address=address, value=value, reason=reason,
            )

        # LIVE
        if _state.config is None:
            raise HTTPException(status_code=503, detail="Config nicht initialisiert")
        from wp_state_machine.ingest.cmi_writer import write_to_cmi
        result = await write_to_cmi(_state.config, address, value)
        await _audit(
            cmi_called=True,
            response_text=result.response_text,
            success=result.success,
            reason=result.reason,
        )
        log.info("LIVE %s addr=%s value=%s -> %s", label, address, value, result.reason)
        return WriteResult(
            success=result.success, dry_run=False,
            address=address, value=value, reason=result.reason,
        )

    @app.post("/functions/F1/betriebsart", response_model=WriteResult)
    async def set_betriebsart(req: SetBetriebsartRequest) -> WriteResult:
        """Setzt Betriebsart F:1 FBHEIZ (1..7)."""
        return await _execute_write("3E9001301C", req.betriebsart, "Betriebsart")

    @app.post("/functions/F1/normalsoll", response_model=WriteResult)
    async def set_normalsoll(req: SetNormalsollRequest) -> WriteResult:
        """Setzt Normal-Soll-Temperatur F:1 FBHEIZ (10..30 °C)."""
        return await _execute_write("3EB001300C", req.temp, "Normalsoll")

    @app.post("/functions/F1/absenksoll", response_model=WriteResult)
    async def set_absenksoll(req: SetAbsenksollRequest) -> WriteResult:
        """Setzt Absenk-Soll-Temperatur F:1 FBHEIZ (5..25 °C)."""
        return await _execute_write("3EB001300D", req.temp, "Absenksoll")

    @app.post("/functions/F9/wwsoll", response_model=WriteResult)
    async def set_wwsoll(req: SetNormalsollRequest) -> WriteResult:
        """Setzt WW-Soll-Temperatur F:9 (30..70 °C)."""
        return await _execute_write("3EB0023118", req.temp, "WW-Soll")

    @app.post("/functions/F9/start", response_model=WriteResult)
    async def start_ww_boost() -> WriteResult:
        """Startet WW-Boost / Legionellenschutz F:9 WW_ANF.2."""
        return await _execute_write("3E80093125", 1, "WW-Boost START")

    @app.post("/functions/F9/stop", response_model=WriteResult)
    async def stop_ww_boost() -> WriteResult:
        """Stoppt WW-Boost manuell F:9 WW_ANF.2."""
        return await _execute_write("3E80093126", 1, "WW-Boost STOP")

    # ---------------------------------------------------------------------------
    # Server-Sent-Events fuer Live-Updates
    # ---------------------------------------------------------------------------

    @app.get("/stream")
    async def stream_events() -> StreamingResponse:
        """
        Server-Sent-Events: sendet sofort beim Connect ein Event,
        danach alle 3s State + alle 6 Ticks (~18s) ein Heartbeat-Comment.
        iOS WebKit/Brave braucht den Initial-Push, sonst onerror.
        """

        async def event_generator() -> AsyncGenerator[str, None]:
            # SOFORT initialer Comment + retry-Hint (iOS WebKit-Fix)
            yield ": connected\n\nretry: 5000\n\n"

            tick = 0
            while True:
                data = {
                    "state": _state.wp_state,
                    "dry_run": _state.dry_run,
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "sensoren": _state.sensoren.model_dump(mode="json"),
                }
                yield f"data: {json.dumps(data)}\n\n"
                # Heartbeat-Comment alle 6 Ticks gegen iOS-Idle-Drop
                tick += 1
                if tick % 6 == 0:
                    yield ": ping\n\n"
                await asyncio.sleep(3)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream; charset=utf-8",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return app
