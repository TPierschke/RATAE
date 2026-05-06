"""
api/telegram.py — Telegram-Alarm-Forward.

Sendet NUR bei Fehler/Alarm. Kein Daily-Report.
Alarm-Trigger: CMI Ausgang A5 "Alarm ext." aktiv.

Konfiguration via .env: TELEGRAM_TOKEN + TELEGRAM_CHAT_ID.
Disabled per Default (telegram.enabled=false in config.toml).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

log = logging.getLogger(__name__)

try:
    from telegram import Bot  # type: ignore[import]
    from telegram.error import TelegramError  # type: ignore[import]

    _TELEGRAM_AVAILABLE = True
except ImportError:
    _TELEGRAM_AVAILABLE = False
    log.debug("python-telegram-bot nicht installiert — Telegram deaktiviert")


class TelegramAlerter:
    """
    Telegram-Alerter fuer WP State Machine.

    Sendet nur bei Fehler/Alarm. Keine Heartbeat-Nachrichten.
    """

    def __init__(self, token: str, chat_id: str) -> None:
        self.token = token
        self.chat_id = chat_id
        self._bot: Optional[object] = None
        self._last_alarm_ts: Optional[datetime] = None
        self._alarm_cooldown_seconds: float = 300.0  # 5 Min Cooldown

    def _init_bot(self) -> bool:
        """Initialisiert Bot-Instanz (lazy)."""
        if not _TELEGRAM_AVAILABLE:
            return False
        if self._bot is None and self.token:
            try:
                self._bot = Bot(token=self.token)
                return True
            except Exception as exc:
                log.error("Telegram-Bot-Init fehlgeschlagen: %s", exc)
                return False
        return self._bot is not None

    async def send_alarm(self, message: str) -> bool:
        """
        Sendet Alarm-Nachricht. Mit Cooldown (5 Min zwischen gleichen Alarmen).

        Gibt True bei Erfolg zurueck.
        """
        if not self._init_bot():
            log.debug("Telegram nicht verfuegbar, skip alarm: %s", message[:50])
            return False

        # Cooldown-Check
        now = datetime.now(timezone.utc)
        if self._last_alarm_ts is not None:
            elapsed = (now - self._last_alarm_ts).total_seconds()
            if elapsed < self._alarm_cooldown_seconds:
                log.debug("Telegram Cooldown aktiv (%.0fs), skip alarm", elapsed)
                return False

        try:
            text = f"[WP ALARM] {now.strftime('%H:%M')} — {message}"
            await self._bot.send_message(  # type: ignore[union-attr]
                chat_id=self.chat_id, text=text
            )
            self._last_alarm_ts = now
            log.info("Telegram Alarm gesendet: %s", message[:50])
            return True
        except Exception as exc:
            log.error("Telegram send_alarm Fehler: %s", exc)
            return False

    async def send_cmi_alarm(self, active: bool, details: str = "") -> bool:
        """Sendet CMI-Alarm (A5 aktiv/inaktiv)."""
        if not active:
            return False  # Entwarnung nicht senden
        msg = f"CMI Alarm-Ausgang A5 AKTIV! {details}"
        return await self.send_alarm(msg)

    async def send_watchdog_alert(self, reason: str) -> bool:
        """Sendet Watchdog-Alert (API nicht erreichbar)."""
        msg = f"WATCHDOG: WP State Machine nicht erreichbar! {reason}"
        return await self.send_alarm(msg)

    @property
    def is_configured(self) -> bool:
        return bool(self.token and self.chat_id)
