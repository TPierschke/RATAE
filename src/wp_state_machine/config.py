"""
config.py — Konfigurationslade-Modul.

Laedt aus:
  1. .env (Secrets, Umgebungsvariablen)
  2. config.toml (strukturierte Einstellungen)

Precedence: Umgebungsvariablen > config.toml > Defaults.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Standardpfade
_PROJECT_ROOT = Path(__file__).resolve().parents[2]  # src/../..
_DEFAULT_ENV = _PROJECT_ROOT / ".env"
_DEFAULT_CONFIG = _PROJECT_ROOT / "config.toml"


def _load_env_file(path: Path) -> dict[str, str]:
    """Laedt .env-Datei manuell. Gibt dict mit den geladenen Werten zurueck."""
    result: dict[str, str] = {}
    if not path.exists():
        log.debug("Kein .env gefunden unter %s — OK fuer Prod", path)
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            result[key] = value
    return result


def _load_toml(path: Path) -> dict[str, Any]:
    """Laedt TOML-Config. Gibt leeres dict zurueck wenn nicht vorhanden."""
    if not path.exists():
        log.debug("Keine config.toml unter %s — verwende Defaults", path)
        return {}
    try:
        # Python 3.11+ hat tomllib in der stdlib
        import tomllib  # type: ignore[import]

        return tomllib.loads(path.read_text(encoding="utf-8"))
    except ImportError:
        pass
    try:
        import toml  # type: ignore[import]

        return toml.load(str(path))
    except Exception as exc:
        log.warning("Fehler beim Laden von %s: %s — verwende Defaults", path, exc)
        return {}


class Config:
    """
    Zentrale Konfiguration. Singleton via Config.load().

    Alle Secrets kommen aus Umgebungsvariablen (.env).
    Strukturierte Einstellungen aus config.toml.
    """

    _instance: "Config | None" = None

    def __init__(self, env_path: Path | None = None, config_path: Path | None = None) -> None:
        env_path = env_path or _DEFAULT_ENV
        config_path = config_path or _DEFAULT_CONFIG

        # env_vars: .env-Datei hat NIEDRIGERE Prio als os.environ (echte Umgebung)
        env_vars = _load_env_file(env_path)

        def _get(key: str, default: str = "") -> str:
            """os.environ > .env > default."""
            return os.environ.get(key, env_vars.get(key, default))

        self._toml = _load_toml(config_path)

        # CMI
        self.cmi_host: str = _get("CMI_HOST", "192.168.178.45")
        self.cmi_user: str = _get("CMI_USER", "admin")
        self.cmi_pass: str = _get("CMI_PASS", "admin")
        self.cmi_timeout: float = float(
            self._toml.get("cmi", {}).get("request_timeout_seconds", 10)
        )
        self.cmi_poll_interval: float = float(
            self._toml.get("cmi", {}).get("poll_interval_seconds", 60)
        )
        self.cmi_min_request_interval: float = float(
            self._toml.get("cmi", {}).get("min_request_interval_seconds", 1.0)
        )

        # Betrieb
        dry_run_raw = _get("DRY_RUN", "").lower()
        toml_dry_run = self._toml.get("safety", {}).get("dry_run", True)
        if dry_run_raw in ("false", "0", "no"):
            self.dry_run: bool = False
        elif dry_run_raw in ("true", "1", "yes"):
            self.dry_run = True
        else:
            self.dry_run = bool(toml_dry_run)

        self.log_level: str = _get("LOG_LEVEL", "INFO").upper()

        # Web
        self.host: str = self._toml.get("web", {}).get("host", "0.0.0.0")
        _port_raw = _get("PORT", str(self._toml.get("web", {}).get("port", 8765)))
        self.port: int = int(_port_raw)
        self.sse_interval: float = float(
            self._toml.get("web", {}).get("sse_interval_seconds", 3)
        )

        # Postgres
        self.postgres_url: str = _get(
            "WPSM_POSTGRES_URL",
            "postgresql://wp_sm:changeme@192.168.178.10:5432/wp_state_machine",
        )

        # MQTT
        self.mqtt_enabled: bool = self._toml.get("mqtt", {}).get("enabled", False)
        self.mqtt_host: str = _get(
            "MQTT_HOST", self._toml.get("mqtt", {}).get("host", "192.168.178.10")
        )
        self.mqtt_port: int = int(_get("MQTT_PORT", "1883"))
        self.mqtt_user: str = _get("MQTT_USER", "")
        self.mqtt_pass: str = _get("MQTT_PASS", "")

        # Telegram
        self.telegram_enabled: bool = self._toml.get("telegram", {}).get("enabled", False)
        self.telegram_token: str = _get("TELEGRAM_TOKEN", "")
        self.telegram_chat_id: str = _get("TELEGRAM_CHAT_ID", "")

        # Modbus-Slave (primaere Datenquelle)
        self.modbus_enabled: bool = self._toml.get("modbus", {}).get("enabled", True)
        self.modbus_port: int = int(
            _get("MODBUS_PORT", str(self._toml.get("modbus", {}).get("port", 5020)))
        )
        self.modbus_slave_id: int = int(
            self._toml.get("modbus", {}).get("slave_id", 1)
        )
        # Sensor-Offsets: werden auf Rohwert addiert (Default 0.0 ueberall)
        # Konfigurierbar in config.toml unter [modbus.sensor_offsets]
        raw_offsets = self._toml.get("modbus", {}).get("sensor_offsets", {})
        self.sensor_offsets: dict[str, float] = {
            k: float(v) for k, v in raw_offsets.items()
        }

        # Monitoring
        self.watchdog_poll_interval: float = float(
            self._toml.get("monitoring", {}).get("watchdog_poll_interval_seconds", 30)
        )
        self.anomaly_heissgas_threshold: float = float(
            self._toml.get("monitoring", {}).get("anomaly_heissgas_threshold_celsius", 35.0)
        )
        self.anomaly_heizstab_threshold: float = float(
            self._toml.get("monitoring", {}).get("anomaly_heizstab_threshold_celsius", 50.0)
        )
        self.heartbeat_interval: float = float(
            self._toml.get("storage", {}).get("heartbeat_interval_seconds", 60)
        )

    @classmethod
    def load(
        cls, env_path: Path | None = None, config_path: Path | None = None
    ) -> "Config":
        """Singleton-Loader. Erstes Load gewinnt."""
        if cls._instance is None:
            cls._instance = cls(env_path=env_path, config_path=config_path)
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Test-Hilfsmethode: Singleton zuruecksetzen."""
        cls._instance = None

    def cmi_base_url(self) -> str:
        return f"http://{self.cmi_host}"

    def cmi_menupage_url(self, page: str) -> str:
        return f"http://{self.cmi_host}/menupage.cgi?page={page}"

    def cmi_api_url(self) -> str:
        return f"http://{self.cmi_host}/INCLUDE/api.cgi?jsonnode=62&jsonparam=I,O"

    def cmi_auth(self) -> tuple[str, str]:
        return (self.cmi_user, self.cmi_pass)

    def summary(self) -> dict[str, Any]:
        """Lesbare Zusammenfassung ohne Secrets (fuer /health)."""
        return {
            "cmi_host": self.cmi_host,
            "dry_run": self.dry_run,
            "port": self.port,
            "mqtt_enabled": self.mqtt_enabled,
            "telegram_enabled": self.telegram_enabled,
            "log_level": self.log_level,
            "cmi_poll_interval": self.cmi_poll_interval,
            "modbus_enabled": self.modbus_enabled,
            "modbus_port": self.modbus_port,
        }
