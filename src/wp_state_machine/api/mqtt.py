"""
api/mqtt.py — MQTT-Publisher Skelett.

Publiziert WP-State und Telemetrie per MQTT.
FHEM/HA subscriben. paho-mqtt (v2).

Topics:
  wp/state         aktueller WP-State (HEIZUNG/WARMWASSER/BEREIT/STANDBY/UNKNOWN)
  wp/telemetry/... einzelne Sensor-Werte
  wp/alarm         Alarm-State (0/1)
  wp/dry_run       DRY_RUN-Status

Phase 1: Skelett. Disabled per Default (mqtt.enabled=false in config.toml).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

log = logging.getLogger(__name__)

try:
    import paho.mqtt.client as mqtt_client  # type: ignore[import]

    _PAHO_AVAILABLE = True
except ImportError:
    _PAHO_AVAILABLE = False
    log.debug("paho-mqtt nicht installiert — MQTT deaktiviert")


class MqttPublisher:
    """
    MQTT-Publisher fuer WP State Machine.

    Verwendung:
        pub = MqttPublisher(host="192.168.178.10", port=1883)
        await pub.connect()
        await pub.publish_state("HEIZUNG")
        await pub.publish_telemetry(sensoren_dict)
    """

    TOPIC_STATE = "wp/state"
    TOPIC_ALARM = "wp/alarm"
    TOPIC_DRY_RUN = "wp/dry_run"
    TOPIC_TELEMETRY_PREFIX = "wp/telemetry"

    def __init__(
        self,
        host: str = "192.168.178.10",
        port: int = 1883,
        user: str = "",
        password: str = "",
    ) -> None:
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self._client: Any = None
        self._connected = False

    def connect(self) -> bool:
        """Verbindet mit MQTT-Broker (synchron)."""
        if not _PAHO_AVAILABLE:
            log.warning("paho-mqtt nicht verfuegbar — MQTT deaktiviert")
            return False
        try:
            self._client = mqtt_client.Client(
                callback_api_version=mqtt_client.CallbackAPIVersion.VERSION2
            )
            if self.user:
                self._client.username_pw_set(self.user, self.password)
            self._client.connect(self.host, self.port, keepalive=60)
            self._client.loop_start()
            self._connected = True
            log.info("MQTT verbunden mit %s:%d", self.host, self.port)
            return True
        except Exception as exc:
            log.error("MQTT-Verbindungsfehler: %s", exc)
            self._connected = False
            return False

    def disconnect(self) -> None:
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def publish(self, topic: str, payload: Any, retain: bool = False) -> bool:
        """Publiziert Nachricht. Payload wird JSON-serialisiert wenn dict/list."""
        if not self._connected or not self._client:
            log.debug("MQTT nicht verbunden, skip publish: %s", topic)
            return False
        try:
            if isinstance(payload, (dict, list)):
                payload = json.dumps(payload)
            elif not isinstance(payload, (str, bytes)):
                payload = str(payload)
            self._client.publish(topic, payload, qos=1, retain=retain)
            return True
        except Exception as exc:
            log.error("MQTT publish Fehler (%s): %s", topic, exc)
            return False

    def publish_state(self, state: str, dry_run: bool = True) -> bool:
        """Publiziert WP-State."""
        ok1 = self.publish(self.TOPIC_STATE, state, retain=True)
        ok2 = self.publish(self.TOPIC_DRY_RUN, "1" if dry_run else "0", retain=True)
        return ok1 and ok2

    def publish_telemetry(self, sensoren: dict[str, Any]) -> bool:
        """Publiziert einzelne Sensor-Werte als separate Topics."""
        fields = [
            "vorlauf", "ruecklauf", "warmwasser", "aussen",
            "heissgas", "verdichter", "ventil_ww", "alarm",
            "heizstab_hz", "heizstab_ww", "betriebsart",
        ]
        ok = True
        for field in fields:
            val = sensoren.get(field)
            if val is not None:
                topic = f"{self.TOPIC_TELEMETRY_PREFIX}/{field}"
                if not self.publish(topic, val):
                    ok = False
        return ok

    def publish_alarm(self, active: bool) -> bool:
        """Publiziert Alarm-State (0/1)."""
        return self.publish(self.TOPIC_ALARM, "1" if active else "0", retain=True)
