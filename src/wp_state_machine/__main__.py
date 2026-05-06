"""
__main__.py — Einstiegspunkt fuer WP State Machine.

Startet:
  - FastAPI (uvicorn) auf konfigurierbarem Port (default 8765)
  - CMI-Poll-Loop (asyncio, 60s Intervall)
  - Heartbeat-Loop (60s)
  - Watchdog (subprocess)

Verwendung:
  python3 -m wp_state_machine
  python3 -m wp_state_machine --dry-run-off   # VORSICHT: Live-Mode!
  python3 -m wp_state_machine --port 9000
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging-Setup (vor allen anderen Imports)
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("wp_state_machine")


# ---------------------------------------------------------------------------
# Imports (nach Logging)
# ---------------------------------------------------------------------------

from wp_state_machine.config import Config
from wp_state_machine.api.rest import create_app, get_app_state
from wp_state_machine.monitoring.health import run_all_checks


async def poll_loop(config: Config, app_state) -> None:
    """CMI-Poll-Loop: scrapet Daten alle poll_interval Sekunden."""
    from wp_state_machine.ingest.web_scraper import (
        parse_outputs_page,
        parse_functions_overview,
        merge_scrape_results,
        load_fixture,
    )
    from wp_state_machine.core.models import Sensoren, Betriebsart
    import aiohttp

    log.info("Poll-Loop gestartet (Intervall: %.0fs)", config.cmi_poll_interval)

    while True:
        try:
            auth = aiohttp.BasicAuth(*config.cmi_auth())
            timeout = aiohttp.ClientTimeout(total=config.cmi_timeout)

            async with aiohttp.ClientSession(auth=auth, timeout=timeout) as session:
                outputs_html = ""
                functions_html = ""

                url_outputs = config.cmi_menupage_url("3E005806")
                async with session.get(url_outputs) as resp:
                    if resp.status == 200:
                        outputs_html = await resp.text()
                    else:
                        log.warning("CMI Outputs-Page: HTTP %d", resp.status)

                # Rate-Limit: 1s Pause
                await asyncio.sleep(config.cmi_min_request_interval)

                url_functions = config.cmi_menupage_url("3E01581E")
                async with session.get(url_functions) as resp:
                    if resp.status == 200:
                        functions_html = await resp.text()
                    else:
                        log.warning("CMI Functions-Page: HTTP %d", resp.status)

            outputs = parse_outputs_page(outputs_html) if outputs_html else {}
            functions = parse_functions_overview(functions_html) if functions_html else {}
            merged = merge_scrape_results(outputs, functions)

            sensoren = Sensoren(
                aussen=merged.get("aussen"),
                vorlauf=merged.get("vorlauf"),
                ruecklauf=merged.get("ruecklauf"),
                warmwasser=merged.get("warmwasser"),
                verdichter=merged.get("verdichter"),
                ventil_ww=merged.get("ventil_ww"),
                heizstab_hz=merged.get("heizstab_hz"),
                heizstab_ww=merged.get("heizstab_ww"),
                alarm=merged.get("alarm"),
                betriebsart=Betriebsart(merged["betriebsart"]) if merged.get("betriebsart") else None,
                source="web_scraper",
            )
            await app_state.update_sensoren(sensoren)
            app_state.cmi_reachable = True

            # Telemetrie speichern
            if app_state.postgres and app_state.postgres.is_connected:
                from wp_state_machine.core.models import TelemetryRecord
                record = TelemetryRecord.from_sensoren(sensoren, app_state.wp_state)
                await app_state.postgres.insert_telemetry(record.model_dump())

            # Anomalie-Checks
            warnings = run_all_checks(sensoren, last_update=app_state.last_update)
            for w in warnings:
                log.warning("ANOMALIE: %s", w)

        except Exception as exc:
            log.error("Poll-Loop-Fehler: %s", exc)
            app_state.cmi_reachable = False

        await asyncio.sleep(config.cmi_poll_interval)


async def heartbeat_loop(config: Config, app_state) -> None:
    """Heartbeat alle 60s in DB schreiben."""
    while True:
        await asyncio.sleep(config.heartbeat_interval)
        if app_state.postgres and app_state.postgres.is_connected:
            await app_state.postgres.insert_heartbeat(
                module="main",
                details={"wp_state": app_state.wp_state, "dry_run": config.dry_run},
            )
            log.debug("Heartbeat geschrieben")


async def main() -> None:
    parser = argparse.ArgumentParser(description="WP State Machine")
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--dry-run-off", action="store_true", help="LIVE-Modus aktivieren")
    args = parser.parse_args()

    config = Config.load()

    if args.dry_run_off:
        config.dry_run = False
        log.warning("LIVE-MODUS AKTIVIERT — Echter CMI-Schreibzugriff moeglich!")
    else:
        log.info("DRY_RUN=%s", config.dry_run)

    if args.port:
        config.port = args.port

    # Logging-Level aus Config
    logging.getLogger().setLevel(config.log_level)

    app_state = get_app_state()
    app_state.dry_run = config.dry_run

    # Postgres verbinden
    if config.postgres_url:
        from wp_state_machine.storage.postgres import PostgresStore
        from wp_state_machine.storage import schema

        store = PostgresStore(config.postgres_url)
        if await store.connect():
            schema_sql = (Path(__file__).parent / "storage" / "schema.sql").read_text()
            await store.apply_schema(schema_sql)
            app_state.postgres = store
            log.info("Postgres verbunden")
        else:
            log.warning("Postgres nicht erreichbar — Telemetrie deaktiviert")

    # FastAPI-App
    app = create_app(state=app_state)

    import uvicorn

    server_config = uvicorn.Config(
        app=app,
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
    )
    server = uvicorn.Server(server_config)

    log.info("Starte WP State Machine auf %s:%d", config.host, config.port)

    # Tasks
    tasks = [
        asyncio.create_task(server.serve()),
        asyncio.create_task(poll_loop(config, app_state)),
        asyncio.create_task(heartbeat_loop(config, app_state)),
    ]

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        log.info("Shutdown...")
    finally:
        for t in tasks:
            t.cancel()
        if app_state.postgres:
            await app_state.postgres.close()


if __name__ == "__main__":
    asyncio.run(main())
