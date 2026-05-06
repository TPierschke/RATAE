"""
monitoring/watchdog.py — Watchdog-Subprocess.

Pollt eigene API alle 30s. Sendet Telegram-Alert wenn keine Antwort.
Laeuft als separater Subprocess (via subprocess.Popen) um vom Main-Process
unabhaengig zu sein.

Aufruf: python3 -m wp_state_machine.monitoring.watchdog --url http://localhost:8765
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)


async def check_api_health(url: str, timeout: float = 5.0) -> tuple[bool, str]:
    """
    Prueft ob API erreichbar ist.

    Gibt (ok, reason) zurueck.
    Kein echter HTTP-Call in Tests (wird gemockt).
    """
    try:
        import aiohttp  # type: ignore[import]

        async with aiohttp.ClientSession() as session:
            async with session.get(f"{url}/health", timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                if resp.status == 200:
                    return True, "OK"
                return False, f"HTTP {resp.status}"
    except Exception as exc:
        return False, str(exc)


async def watchdog_loop(
    api_url: str,
    poll_interval: float = 30.0,
    telegram_alerter: Optional[object] = None,
    max_failures: int = 3,
) -> None:
    """
    Watchdog-Loop. Laeuft bis zum Prozess-Ende.

    api_url: z.B. http://localhost:8765
    poll_interval: Sekunden zwischen Checks
    telegram_alerter: TelegramAlerter-Instanz oder None
    max_failures: Anzahl Failures bevor Alert
    """
    failures = 0
    last_alert_ts: Optional[datetime] = None
    alert_cooldown = 300.0  # 5 Min

    log.info("Watchdog gestartet: %s (interval=%.0fs)", api_url, poll_interval)

    while True:
        try:
            ok, reason = await check_api_health(api_url)
            if ok:
                if failures > 0:
                    log.info("Watchdog: API wieder erreichbar nach %d Failures", failures)
                failures = 0
            else:
                failures += 1
                log.warning("Watchdog: API nicht erreichbar (%d/%d): %s", failures, max_failures, reason)

                if failures >= max_failures:
                    now = datetime.now(timezone.utc)
                    should_alert = (
                        last_alert_ts is None
                        or (now - last_alert_ts).total_seconds() >= alert_cooldown
                    )
                    if should_alert and telegram_alerter is not None:
                        try:
                            await telegram_alerter.send_watchdog_alert(reason)
                            last_alert_ts = now
                        except Exception as exc:
                            log.error("Watchdog: Telegram-Alert fehlgeschlagen: %s", exc)

        except Exception as exc:
            log.error("Watchdog-Loop-Fehler: %s", exc)

        await asyncio.sleep(poll_interval)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="WP State Machine Watchdog")
    parser.add_argument("--url", default="http://localhost:8765", help="API-URL")
    parser.add_argument("--interval", type=float, default=30.0, help="Poll-Intervall in Sekunden")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    asyncio.run(watchdog_loop(api_url=args.url, poll_interval=args.interval))
