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
    LEGIONELLENSCHUTZ = "LEGIONELLENSCHUTZ"  # Verdichter AN + Ventil WW + Heizstab WW
    UNKNOWN = "UNKNOWN"      # Noch keine Daten


WP_STATES = {WPState.HEIZUNG, WPState.WARMWASSER, WPState.BEREIT, WPState.STANDBY, WPState.LEGIONELLENSCHUTZ, WPState.UNKNOWN}


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
    raum_ist: Optional[float] = Field(None, description="Raumtemperatur S5 (Grad C)")
    heissgas: Optional[float] = Field(None, description="Verdichter-Ausgang S7 (Grad C)")
    fluessigkeit: Optional[float] = Field(None, description="Fluessigkeitsleitung S8 (Grad C)")
    saugleitung: Optional[float] = Field(None, description="Saugleitung S9 (Grad C)")

    # Digital-Inputs
    phasenwaechter: Optional[bool] = Field(None, description="Phasenwaechter S10")
    verdichter_freigabe: Optional[bool] = Field(None, description="Verdichter-Freigabe S11")
    nd_schalter1: Optional[bool] = Field(None, description="ND-Schalter 1 S12")
    hd_schalter: Optional[bool] = Field(None, description="HD-Schalter S13")
    nd_schalter2: Optional[bool] = Field(None, description="ND-Schalter 2 S14")

    # Digital-Outputs (echte Zustaende — alle bool)
    pumpe_hzkr: Optional[bool] = Field(None, description="FBH-Pumpe A1 an/aus")
    ladepumpe: Optional[bool] = Field(None, description="Ladepumpe A2 an/aus")
    verdichter: Optional[bool] = Field(None, description="Verdichter laeuft A3")
    mvr0407_fl1: Optional[bool] = Field(None, description="Magnetventil R0407 FL1 A4")
    alarm: Optional[bool] = Field(None, description="Alarm-Ausgang A5")
    mvr0407_nach2: Optional[bool] = Field(None, description="Magnetventil R0407 Nach2 A6")
    ventil_ww: Optional[bool] = Field(None, description="WW-Ventil A7 (True=WW, False=Heizung)")
    heizstab_hz: Optional[bool] = Field(None, description="Heizstab Puffer A8 (Heizung)")
    heizstab_ww: Optional[bool] = Field(None, description="Heizstab WW A9 (Warmwasser)")
    pumpe_zirku: Optional[bool] = Field(None, description="Zirkulationspumpe A10")
    # Meldungen
    meldung_heizung: Optional[bool] = Field(None, description="Meldung 8 Heizung")

    # Betriebsart aus Funktion F:1
    betriebsart: Optional[Betriebsart] = Field(None, description="Aktuelle Betriebsart F:1")

    # Zaehler / Counter (Modbus M10..M13, uint32)
    betr_std_verdichter: Optional[int] = Field(None, description="Betriebsstunden Verdichter")
    schaltungen_verdichter: Optional[int] = Field(None, description="Schaltzyklen Verdichter")
    betr_std_heizstab_fb: Optional[int] = Field(None, description="Betriebsstunden Heizstab FBH")
    betr_std_heizstab_ww: Optional[int] = Field(None, description="Betriebsstunden Heizstab WW")

    # Status-Codes / Messages (Modbus M14, M15, uint16)
    message_fb: Optional[int] = Field(None, description="Status-Code Heizung")
    message_ww: Optional[int] = Field(None, description="Status-Code WW")

    # Sollwerte / weitere
    vorlauf_soll: Optional[float] = Field(None, description="Vorlauf-Soll-Temperatur")
    traum1: Optional[float] = Field(None, description="Raum-Solltemperatur effektiv")

    # Zeitstempel der letzten Aktualisierung
    timestamp: datetime = Field(default_factory=_utcnow)
    source: str = Field("unknown", description="Datenquelle: json_api | web_scraper | coe")

    def is_heizstab_active(self) -> bool:
        return bool(self.heizstab_hz or self.heizstab_ww)

    def is_verdichter_active(self) -> bool:
        return bool(self.verdichter)

    def derive_state(self) -> str:
        """Derive the current heat-pump state from the sensor combination."""
        if self.betriebsart == Betriebsart.STANDBY:
            return WPState.STANDBY
        # The DHW heating element is only used for domestic hot water. When it
        # is active, the system is in a DHW escalation step even if the
        # compressor or the DHW valve are currently inactive.
        if self.heizstab_ww:
            return WPState.LEGIONELLENSCHUTZ
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
    # Analog inputs
    vorlauf: Optional[float] = None
    ruecklauf: Optional[float] = None
    warmwasser: Optional[float] = None
    aussen: Optional[float] = None
    raum_ist: Optional[float] = None
    heissgas: Optional[float] = None
    fluessigkeit: Optional[float] = None
    saugleitung: Optional[float] = None
    # Digital inputs
    phasenwaechter: Optional[bool] = None
    verdichter_freigabe: Optional[bool] = None
    nd_schalter1: Optional[bool] = None
    hd_schalter: Optional[bool] = None
    nd_schalter2: Optional[bool] = None
    # Digital outputs
    pumpe_hzkr: Optional[bool] = None
    ladepumpe: Optional[bool] = None
    verdichter: Optional[bool] = None
    mvr0407_fl1: Optional[bool] = None
    alarm: Optional[bool] = None
    mvr0407_nach2: Optional[bool] = None
    ventil_ww: Optional[bool] = None
    heizstab_hz: Optional[bool] = None
    heizstab_ww: Optional[bool] = None
    pumpe_zirku: Optional[bool] = None
    meldung_heizung: Optional[bool] = None
    # Mode + state
    betriebsart: Optional[int] = None
    wp_state: Optional[str] = None
    # Counters
    betr_std_verdichter: Optional[int] = None
    schaltungen_verdichter: Optional[int] = None
    betr_std_heizstab_fb: Optional[int] = None
    betr_std_heizstab_ww: Optional[int] = None
    # Status codes
    message_fb: Optional[int] = None
    message_ww: Optional[int] = None
    # Setpoints from sensor readings
    vorlauf_soll: Optional[float] = None
    traum1: Optional[float] = None
    # Setpoints from CMI function-overview crawl (may be None until first crawl)
    normal_soll: Optional[float] = None
    absenk_soll: Optional[float] = None
    raum_ist: Optional[float] = None
    ww_soll_normal: Optional[float] = None
    # Forecast minutes until next demand (only set during BEREIT state).
    # Comparing these vs. actual time-to-next-demand later allows tuning of the
    # cooldown-rate defaults used by frontend + snapshot_logger.
    ww_eta_min: Optional[float] = None
    heat_eta_min: Optional[float] = None
    ww_soll_legio: Optional[float] = None
    ww_ist: Optional[float] = None

    @classmethod
    def from_sensoren(
        cls,
        s: "Sensoren",
        state: str,
        setpoints: Optional[dict] = None,
    ) -> "TelemetryRecord":
        """Build a TelemetryRecord from sensor data and optional function setpoints.

        Args:
            s: Current sensor snapshot.
            state: Derived WP state string (WPState constant).
            setpoints: Optional dict from app_state.setpoints (crawled from CMI
                function-overview).  Missing or None keys are stored as NULL.
        """
        sp = setpoints or {}
        return cls(
            timestamp=s.timestamp,
            vorlauf=s.vorlauf,
            ruecklauf=s.ruecklauf,
            warmwasser=s.warmwasser,
            aussen=s.aussen,
            raum_ist=sp.get("raum_ist"),  # prefer setpoints crawl (S5 + dial offset)
            heissgas=s.heissgas,
            fluessigkeit=s.fluessigkeit,
            saugleitung=s.saugleitung,
            phasenwaechter=s.phasenwaechter,
            verdichter_freigabe=s.verdichter_freigabe,
            nd_schalter1=s.nd_schalter1,
            hd_schalter=s.hd_schalter,
            nd_schalter2=s.nd_schalter2,
            pumpe_hzkr=s.pumpe_hzkr,
            ladepumpe=s.ladepumpe,
            verdichter=s.verdichter,
            mvr0407_fl1=s.mvr0407_fl1,
            alarm=s.alarm,
            mvr0407_nach2=s.mvr0407_nach2,
            ventil_ww=s.ventil_ww,
            heizstab_hz=s.heizstab_hz,
            heizstab_ww=s.heizstab_ww,
            pumpe_zirku=s.pumpe_zirku,
            meldung_heizung=s.meldung_heizung,
            betriebsart=int(s.betriebsart) if s.betriebsart is not None else None,
            wp_state=state,
            betr_std_verdichter=s.betr_std_verdichter,
            schaltungen_verdichter=s.schaltungen_verdichter,
            betr_std_heizstab_fb=s.betr_std_heizstab_fb,
            betr_std_heizstab_ww=s.betr_std_heizstab_ww,
            message_fb=s.message_fb,
            message_ww=s.message_ww,
            vorlauf_soll=sp.get("vorlauf_soll", s.vorlauf_soll),  # crawl wins, sensor fallback
            traum1=s.traum1,
            normal_soll=sp.get("normal_soll"),
            absenk_soll=sp.get("absenk_soll"),
            ww_soll_normal=sp.get("ww_soll_normal"),
            ww_soll_legio=sp.get("ww_soll_legio"),
            ww_ist=sp.get("ww_ist"),
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
