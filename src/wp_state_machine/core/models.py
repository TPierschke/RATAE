"""
core/models.py — Pydantic-Datenmodelle fuer WP State Machine.

Alle Typen die zwischen Modulen ausgetauscht werden.
Keine CMI-Calls hier — nur Datendefinitionen.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import IntEnum
from typing import Optional


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Betriebsart(IntEnum):
    STANDBY = 1
    ZEIT_AUTO = 2
    NORMAL = 3
    ABGESENKT = 4
    PARTY = 5
    URLAUB = 6
    FEIERTAG = 7

    @classmethod
    def from_int(cls, value: int) -> "Betriebsart":
        try:
            return cls(value)
        except ValueError:
            raise ValueError(f"Unbekannte Betriebsart: {value!r}. Erlaubt: 1-7.")


class WPState(str):
    """
    Betriebszustand der Waermepumpe (abgeleitet aus Sensor-Kombination).

    Werte als Klassenkonstanten — kein Enum damit JSON-Serialisierung direkt klappt.
    """

    HEIZUNG = "HEIZUNG"      # Verdichter AN + Ventil Heizung
    WARMWASSER = "WARMWASSER"  # Verdichter AN + Ventil WW
    BEREIT = "BEREIT"        # Verdichter AUS, Betrieb aktiv
    STANDBY = "STANDBY"      # Betriebsart == STANDBY
    UNKNOWN = "UNKNOWN"      # Noch keine Daten


WP_STATES = {WPState.HEIZUNG, WPState.WARMWASSER, WPState.BEREIT, WPState.STANDBY, WPState.UNKNOWN}


# ---------------------------------------------------------------------------
# Sensoren (CMI-Daten)
# ---------------------------------------------------------------------------


class Sensoren(BaseModel):
    """Aktuelle Sensor-Werte aus CMI (Inputs + Outputs)."""

    # Analog-Inputs (Temperaturen)
    aussen: Optional[float] = Field(None, description="Aussentemperatur S1 (Grad C)")
    vorlauf: Optional[float] = Field(None, description="Puffer oben S2 (Grad C)")
    ruecklauf: Optional[float] = Field(None, description="FBH-Ruecklauf S3 (Grad C)")
    warmwasser: Optional[float] = Field(None, description="WW-Speicher S4 (Grad C)")
    heissgas: Optional[float] = Field(None, description="Verdichter-Ausgang S7 (Grad C)")
    fluessigkeit: Optional[float] = Field(None, description="Fluessigkeitsleitung S8 (Grad C)")
    saugleitung: Optional[float] = Field(None, description="Saugleitung S9 (Grad C)")

    # Digital-Inputs
    phasenwaechter: Optional[bool] = Field(None, description="Phasenwaechter S10")
    verdichter_freigabe: Optional[bool] = Field(None, description="Verdichter-Freigabe S11")
    nd_schalter1: Optional[bool] = Field(None, description="ND-Schalter 1 S12")
    hd_schalter: Optional[bool] = Field(None, description="HD-Schalter S13")
    nd_schalter2: Optional[bool] = Field(None, description="ND-Schalter 2 S14")

    # Digital-Outputs (echte Zustaende)
    pumpe_hzkr: Optional[float] = Field(None, description="FBH-Pumpe A1 (0-100%)")
    ladepumpe: Optional[float] = Field(None, description="Ladepumpe A2 (0-100%)")
    verdichter: Optional[bool] = Field(None, description="Verdichter laeuft A3")
    ventil_ww: Optional[bool] = Field(None, description="WW-Ventil A7 (True=WW, False=Heizung)")
    heizstab_hz: Optional[bool] = Field(None, description="Heizstab Puffer A8")
    heizstab_ww: Optional[bool] = Field(None, description="Heizstab WW A9")
    pumpe_zirku: Optional[bool] = Field(None, description="Zirkulationspumpe A10")
    alarm: Optional[bool] = Field(None, description="Alarm-Ausgang A5")

    # Betriebsart aus Funktion F:1
    betriebsart: Optional[Betriebsart] = Field(None, description="Aktuelle Betriebsart F:1")

    # Zeitstempel der letzten Aktualisierung
    timestamp: datetime = Field(default_factory=_utcnow)
    source: str = Field("unknown", description="Datenquelle: json_api | web_scraper | coe")

    @field_validator("pumpe_hzkr", "ladepumpe", mode="before")
    @classmethod
    def clamp_percent(cls, v: object) -> Optional[float]:
        if v is None:
            return None
        f = float(v)  # type: ignore[arg-type]
        return max(0.0, min(100.0, f))

    def is_heizstab_active(self) -> bool:
        return bool(self.heizstab_hz or self.heizstab_ww)

    def is_verdichter_active(self) -> bool:
        return bool(self.verdichter)

    def derive_state(self) -> str:
        """Leitet WP-State aus Sensor-Kombination ab."""
        if self.betriebsart == Betriebsart.STANDBY:
            return WPState.STANDBY
        if self.verdichter is None:
            return WPState.UNKNOWN
        if self.verdichter:
            if self.ventil_ww:
                return WPState.WARMWASSER
            return WPState.HEIZUNG
        return WPState.BEREIT


# ---------------------------------------------------------------------------
# Telemetrie (was in DB landet)
# ---------------------------------------------------------------------------


class TelemetryRecord(BaseModel):
    """Ein Telemetrie-Datensatz fuer Postgres (Hypertable)."""

    timestamp: datetime = Field(default_factory=_utcnow)
    vorlauf: Optional[float] = None
    ruecklauf: Optional[float] = None
    warmwasser: Optional[float] = None
    aussen: Optional[float] = None
    heissgas: Optional[float] = None
    fluessigkeit: Optional[float] = None
    saugleitung: Optional[float] = None
    verdichter: Optional[bool] = None
    ventil_ww: Optional[bool] = None
    heizstab_hz: Optional[bool] = None
    heizstab_ww: Optional[bool] = None
    alarm: Optional[bool] = None
    betriebsart: Optional[int] = None
    wp_state: Optional[str] = None

    @classmethod
    def from_sensoren(cls, s: Sensoren, state: str) -> "TelemetryRecord":
        return cls(
            timestamp=s.timestamp,
            vorlauf=s.vorlauf,
            ruecklauf=s.ruecklauf,
            warmwasser=s.warmwasser,
            aussen=s.aussen,
            heissgas=s.heissgas,
            fluessigkeit=s.fluessigkeit,
            saugleitung=s.saugleitung,
            verdichter=s.verdichter,
            ventil_ww=s.ventil_ww,
            heizstab_hz=s.heizstab_hz,
            heizstab_ww=s.heizstab_ww,
            alarm=s.alarm,
            betriebsart=int(s.betriebsart) if s.betriebsart is not None else None,
            wp_state=state,
        )


# ---------------------------------------------------------------------------
# API Request/Response-Typen
# ---------------------------------------------------------------------------


class SetBetriebsartRequest(BaseModel):
    betriebsart: int = Field(..., ge=1, le=7, description="1=Standby..7=Feiertag")

    @field_validator("betriebsart")
    @classmethod
    def validate_betriebsart(cls, v: int) -> int:
        Betriebsart.from_int(v)  # raises if invalid
        return v


class SetNormalsollRequest(BaseModel):
    temp: float = Field(..., ge=10.0, le=30.0, description="Raumsoll Normal in Grad C")


class SetAbsenksollRequest(BaseModel):
    temp: float = Field(..., ge=5.0, le=25.0, description="Raumsoll Abgesenkt in Grad C")


class WriteResult(BaseModel):
    """Ergebnis eines CMI-Schreibvorgangs."""

    success: bool
    dry_run: bool
    address: str
    value: int | float | None = None
    reason: str
    cmi_response: Optional[str] = None
    timestamp: datetime = Field(default_factory=_utcnow)


class AlarmEvent(BaseModel):
    """Alarm-Ereignis (Ausgang A5 aktiv)."""

    timestamp: datetime = Field(default_factory=_utcnow)
    active: bool
    telegram_forwarded: bool = False
    details: str = ""


class HealthStatus(BaseModel):
    """Status aller Sub-Module fuer GET /health."""

    ok: bool
    timestamp: datetime = Field(default_factory=_utcnow)
    dry_run: bool
    cmi_reachable: Optional[bool] = None
    postgres_ok: Optional[bool] = None
    mqtt_ok: Optional[bool] = None
    telegram_ok: Optional[bool] = None
    last_telemetry: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None
    wp_state: str = WPState.UNKNOWN
    modules: dict[str, str] = Field(default_factory=dict)
