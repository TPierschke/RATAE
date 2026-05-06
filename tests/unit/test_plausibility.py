"""
tests/unit/test_plausibility.py — Unit-Tests fuer tools/plausibility_check.py.

Testet:
  - parse_messwerte(): HTML-Parser fuer CMI Messwerte-Seite
  - parse_ausgaenge(): HTML-Parser fuer CMI Ausgaenge-Seite
  - extract_modbus_values(): JSON-Parser fuer /state-Endpoint
  - compare_values(): Diff-Berechnung + Threshold-Trigger
  - Telegram-Mock: send_telegram() kein echter API-Call in Tests

KEIN echter HTTP-Call — alle Fixtures sind inline definiert.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

# Pfad zum Tool-Modul (nicht installiert, daher sys.path-Hack)
import sys

_TOOLS_DIR = Path(__file__).parents[2] / "tools"
if str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))

from plausibility_check import (
    ANALOG_THRESHOLD,
    compare_values,
    extract_modbus_values,
    parse_ausgaenge,
    parse_messwerte,
)


# ---------------------------------------------------------------------------
# Fixtures — Inline-HTML (kein Filesystem-Zugriff)
# ---------------------------------------------------------------------------

_MESSWERTE_HTML = """\
<!DOCTYPE html><html><body>
<hr>&nbsp;MESSWERTEUEBERSICHT<br>
<hr>&nbsp;1:&nbsp;10,5 °C&nbsp;&nbsp;29,4 °C<br>
&nbsp;3:&nbsp;30,3 °C&nbsp;&nbsp;50,4 °C<br>
&nbsp;5:&nbsp;&nbsp;-----&nbsp;&nbsp; &nbsp;&nbsp;-----<br>
&nbsp;7:&nbsp;40,9 °C&nbsp;&nbsp;39,4 °C<br>
&nbsp;9:&nbsp;17,2 °C&nbsp;&nbsp;EIN<br>
11:&nbsp;EIN&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;EIN<br>
</body></html>"""

_MESSWERTE_HTML_NEGATIV = """\
<!DOCTYPE html><html><body>
<hr>&nbsp;MESSWERTEUEBERSICHT<br>
<hr>&nbsp;1:&nbsp;-3,5 °C&nbsp;&nbsp;28,0 °C<br>
&nbsp;3:&nbsp;25,0 °C&nbsp;&nbsp;45,0 °C<br>
&nbsp;7:&nbsp;50,0 °C&nbsp;&nbsp;42,0 °C<br>
</body></html>"""

_AUSGAENGE_HTML = """\
<!DOCTYPE html><html><body>
&nbsp;1:&nbsp;Pumpe-Hzkr<br>
&nbsp;&nbsp;&nbsp;&nbsp;AUTO/AUS<br>
&nbsp;2:&nbsp;Ladepumpe<br>
&nbsp;&nbsp;&nbsp;&nbsp;AUTO/AUS<br>
&nbsp;3:&nbsp;Verdichter<br>
&nbsp;&nbsp;&nbsp;&nbsp;AUTO/AUS<br>
&nbsp;5:&nbsp;Alarm ext.<br>
&nbsp;&nbsp;&nbsp;&nbsp;AUTO/AUS<br>
&nbsp;7:&nbsp;Ventil-WW<br>
&nbsp;&nbsp;&nbsp;&nbsp;AUTO/AUS<br>
&nbsp;9:&nbsp;Heizstab2<br>
&nbsp;&nbsp;&nbsp;&nbsp;AUTO/AUS<br>
</body></html>"""

_AUSGAENGE_EIN_HTML = """\
<!DOCTYPE html><html><body>
&nbsp;3:&nbsp;Verdichter<br>
&nbsp;&nbsp;&nbsp;&nbsp;AUTO/EIN<br>
&nbsp;5:&nbsp;Alarm ext.<br>
&nbsp;&nbsp;&nbsp;&nbsp;AUTO/EIN<br>
&nbsp;9:&nbsp;Heizstab2<br>
&nbsp;&nbsp;&nbsp;&nbsp;AUTO/EIN<br>
</body></html>"""

_STATE_JSON_OK = {
    "state": "STANDBY",
    "dry_run": True,
    "last_update": "2026-05-06T14:00:00+00:00",
    "sensoren": {
        "aussen": 10.5,
        "vorlauf": 29.4,
        "ruecklauf": 30.3,
        "warmwasser": 50.4,
        "heissgas": 40.9,
        "fluessigkeit": None,
        "saugleitung": None,
        "verdichter": False,
        "heizstab_ww": False,
        "alarm": False,
        "betriebsart": 1,
        "source": "modbus",
    },
}


# ---------------------------------------------------------------------------
# parse_messwerte()
# ---------------------------------------------------------------------------


class TestParseMesswerte:
    def test_aussen_parsed(self):
        result = parse_messwerte(_MESSWERTE_HTML)
        assert result.get("aussen") is not None
        assert abs(result["aussen"] - 10.5) < 0.1

    def test_vorlauf_parsed(self):
        result = parse_messwerte(_MESSWERTE_HTML)
        assert result.get("vorlauf") is not None
        assert abs(result["vorlauf"] - 29.4) < 0.1

    def test_ruecklauf_parsed(self):
        result = parse_messwerte(_MESSWERTE_HTML)
        assert result.get("ruecklauf") is not None
        assert abs(result["ruecklauf"] - 30.3) < 0.1

    def test_warmwasser_parsed(self):
        result = parse_messwerte(_MESSWERTE_HTML)
        assert result.get("warmwasser") is not None
        assert abs(result["warmwasser"] - 50.4) < 0.1

    def test_heissgas_parsed(self):
        result = parse_messwerte(_MESSWERTE_HTML)
        assert result.get("heissgas") is not None
        assert abs(result["heissgas"] - 40.9) < 0.1

    def test_phasenwaechter_ein(self):
        result = parse_messwerte(_MESSWERTE_HTML)
        # Row 9 col2 = "EIN"
        assert result.get("phasenwaechter") is True

    def test_negative_temperature(self):
        """Minustemperatur (-3,5°C) korrekt geparst."""
        result = parse_messwerte(_MESSWERTE_HTML_NEGATIV)
        assert result.get("aussen") is not None
        assert abs(result["aussen"] - (-3.5)) < 0.1

    def test_leeres_html_gibt_leeres_dict(self):
        result = parse_messwerte("<html><body></body></html>")
        assert isinstance(result, dict)
        # Keine Crashes, aber auch keine Werte
        assert result.get("aussen") is None

    def test_alle_relevanten_keys_vorhanden(self):
        result = parse_messwerte(_MESSWERTE_HTML)
        expected_keys = {"aussen", "vorlauf", "ruecklauf", "warmwasser", "heissgas"}
        found = {k for k in expected_keys if result.get(k) is not None}
        assert found == expected_keys, f"Fehlende Keys: {expected_keys - found}"


# ---------------------------------------------------------------------------
# parse_ausgaenge()
# ---------------------------------------------------------------------------


class TestParseAusgaenge:
    def test_verdichter_aus(self):
        result = parse_ausgaenge(_AUSGAENGE_HTML)
        assert result.get("verdichter") is False

    def test_alarm_aus(self):
        result = parse_ausgaenge(_AUSGAENGE_HTML)
        assert result.get("alarm") is False

    def test_heizstab_ww_aus(self):
        result = parse_ausgaenge(_AUSGAENGE_HTML)
        assert result.get("heizstab_ww") is False

    def test_verdichter_ein(self):
        result = parse_ausgaenge(_AUSGAENGE_EIN_HTML)
        assert result.get("verdichter") is True

    def test_alarm_ein(self):
        result = parse_ausgaenge(_AUSGAENGE_EIN_HTML)
        assert result.get("alarm") is True

    def test_heizstab_ein(self):
        result = parse_ausgaenge(_AUSGAENGE_EIN_HTML)
        assert result.get("heizstab_ww") is True

    def test_leeres_html_gibt_leeres_dict(self):
        result = parse_ausgaenge("<html><body></body></html>")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# extract_modbus_values()
# ---------------------------------------------------------------------------


class TestExtractModbusValues:
    def test_alle_analog_felder(self):
        result = extract_modbus_values(_STATE_JSON_OK)
        assert abs(result["aussen"] - 10.5) < 0.01
        assert abs(result["vorlauf"] - 29.4) < 0.01
        assert abs(result["ruecklauf"] - 30.3) < 0.01
        assert abs(result["warmwasser"] - 50.4) < 0.01
        assert abs(result["heissgas"] - 40.9) < 0.01

    def test_digitale_felder(self):
        result = extract_modbus_values(_STATE_JSON_OK)
        assert result["verdichter"] is False
        assert result["heizstab_ww"] is False
        assert result["alarm"] is False

    def test_none_werte_bei_fehlendem_sensor(self):
        state = {
            "sensoren": {
                "aussen": None,
                "vorlauf": 29.0,
                "ruecklauf": None,
                "warmwasser": None,
                "heissgas": None,
                "verdichter": None,
                "heizstab_ww": None,
                "alarm": None,
            }
        }
        result = extract_modbus_values(state)
        assert result["aussen"] is None
        assert abs(result["vorlauf"] - 29.0) < 0.01

    def test_leeres_sensoren_dict(self):
        result = extract_modbus_values({"sensoren": {}})
        assert result["aussen"] is None
        assert result["verdichter"] is None

    def test_fehlendes_sensoren_key(self):
        result = extract_modbus_values({})
        assert result["aussen"] is None


# ---------------------------------------------------------------------------
# compare_values() — Diff-Berechnung + Threshold
# ---------------------------------------------------------------------------


class TestCompareValues:
    def _modbus(self, **kwargs) -> dict:
        base = {
            "aussen": 10.5,
            "vorlauf": 29.4,
            "ruecklauf": 30.3,
            "warmwasser": 50.4,
            "heissgas": 40.9,
            "verdichter": False,
            "heizstab_ww": False,
            "alarm": False,
        }
        base.update(kwargs)
        return base

    def _messwerte(self, **kwargs) -> dict:
        base = {
            "aussen": 10.5,
            "vorlauf": 29.4,
            "ruecklauf": 30.3,
            "warmwasser": 50.4,
            "heissgas": 40.9,
        }
        base.update(kwargs)
        return base

    def _ausgaenge(self, **kwargs) -> dict:
        base = {
            "verdichter": False,
            "heizstab_ww": False,
            "alarm": False,
        }
        base.update(kwargs)
        return base

    def test_alles_ok_keine_warnungen(self):
        warnings = compare_values(self._modbus(), self._messwerte(), self._ausgaenge())
        assert warnings == []

    def test_analog_diff_unter_schwelle_keine_warnung(self):
        """Diff 0.4K < 0.5K → kein Alarm."""
        warnings = compare_values(
            self._modbus(vorlauf=29.4),
            self._messwerte(vorlauf=29.8),  # diff=0.4
            self._ausgaenge(),
        )
        assert warnings == []

    def test_analog_diff_genau_schwelle_keine_warnung(self):
        """Diff == 0.5K → kein Alarm (> nicht >=)."""
        warnings = compare_values(
            self._modbus(vorlauf=29.4),
            self._messwerte(vorlauf=29.9),  # diff=0.5
            self._ausgaenge(),
        )
        assert warnings == []

    def test_analog_diff_ueber_schwelle_warnung(self):
        """Diff 3.6K > 0.5K → Warnung."""
        warnings = compare_values(
            self._modbus(vorlauf=29.4),
            self._messwerte(vorlauf=33.0),  # diff=3.6
            self._ausgaenge(),
        )
        assert len(warnings) == 1
        assert "vorlauf" in warnings[0]
        assert "29.4" in warnings[0]
        assert "33.0" in warnings[0]

    def test_warnung_enthaelt_diff_wert(self):
        warnings = compare_values(
            self._modbus(aussen=10.5),
            self._messwerte(aussen=15.0),  # diff=4.5
            self._ausgaenge(),
        )
        assert len(warnings) == 1
        assert "4.5K" in warnings[0]

    def test_digital_mismatch_warnung(self):
        """Modbus sagt AUS, CMI sagt EIN → Warnung."""
        warnings = compare_values(
            self._modbus(verdichter=False),
            self._messwerte(),
            self._ausgaenge(verdichter=True),
        )
        assert len(warnings) == 1
        assert "verdichter" in warnings[0]
        assert "False" in warnings[0]
        assert "True" in warnings[0]

    def test_digital_gleich_keine_warnung(self):
        warnings = compare_values(
            self._modbus(alarm=True),
            self._messwerte(),
            self._ausgaenge(alarm=True),
        )
        assert warnings == []

    def test_none_wert_wird_uebersprungen(self):
        """Wenn ein Wert None ist, kein Vergleich, keine Warnung."""
        warnings = compare_values(
            self._modbus(heissgas=None),
            self._messwerte(heissgas=None),
            self._ausgaenge(),
        )
        assert warnings == []

    def test_mehrere_abweichungen(self):
        """Mehrere Abweichungen → mehrere Warnungen."""
        warnings = compare_values(
            self._modbus(vorlauf=29.4, aussen=10.5, verdichter=False),
            self._messwerte(vorlauf=35.0, aussen=18.0),
            self._ausgaenge(verdichter=True),
        )
        assert len(warnings) == 3  # vorlauf, aussen, verdichter

    def test_schwelle_ist_0_5_kelvin(self):
        """Sicherstellen dass ANALOG_THRESHOLD == 0.5."""
        assert ANALOG_THRESHOLD == 0.5

    def test_heizstab_ww_digital_check(self):
        warnings = compare_values(
            self._modbus(heizstab_ww=True),
            self._messwerte(),
            self._ausgaenge(heizstab_ww=False),
        )
        assert len(warnings) == 1
        assert "heizstab_ww" in warnings[0]

    def test_alarm_digital_check(self):
        warnings = compare_values(
            self._modbus(alarm=False),
            self._messwerte(),
            self._ausgaenge(alarm=True),
        )
        assert len(warnings) == 1
        assert "alarm" in warnings[0]


# ---------------------------------------------------------------------------
# Telegram-Mock — send_telegram() kein echter API-Call
# ---------------------------------------------------------------------------


class TestTelegramMock:
    @patch("plausibility_check.urllib.request.urlopen")
    def test_send_telegram_called_bei_abweichung(self, mock_urlopen):
        """Bei Abweichung wird send_telegram() aufgerufen (via compare+main-flow)."""
        import plausibility_check as pc

        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = json.dumps({"ok": True}).encode()
        mock_urlopen.return_value = mock_resp

        with patch.object(pc, "_load_telegram_token", return_value="FAKE_TOKEN"):
            result = pc.send_telegram("[ThoPAS|plausibility] WARNUNG: test")

        assert result is True
        assert mock_urlopen.called

    @patch("plausibility_check.urllib.request.urlopen")
    def test_send_telegram_api_fehler_gibt_false(self, mock_urlopen):
        """Bei API-Fehler gibt send_telegram() False zurueck."""
        import plausibility_check as pc

        mock_urlopen.side_effect = OSError("Connection refused")

        with patch.object(pc, "_load_telegram_token", return_value="FAKE_TOKEN"):
            result = pc.send_telegram("[ThoPAS|plausibility] WARNUNG: test")

        assert result is False

    def test_send_telegram_ohne_token_gibt_false(self):
        """Ohne Token: False, kein HTTP-Call."""
        import plausibility_check as pc

        with patch.object(pc, "_load_telegram_token", return_value=None):
            result = pc.send_telegram("[ThoPAS|plausibility] test")

        assert result is False

    @patch("plausibility_check.urllib.request.urlopen")
    def test_telegram_prefix_im_payload(self, mock_urlopen):
        """Payload enthaelt [ThoPAS|plausibility] Praefix."""
        import plausibility_check as pc

        captured_payload = []

        def fake_urlopen(req, timeout=None):
            captured_payload.append(req.data)
            mock_resp = MagicMock()
            mock_resp.__enter__ = MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read.return_value = json.dumps({"ok": True}).encode()
            return mock_resp

        mock_urlopen.side_effect = fake_urlopen

        msg = "[ThoPAS|plausibility] WARNUNG: vorlauf modbus=29.4 cmi=33.0 diff=3.6K"
        with patch.object(pc, "_load_telegram_token", return_value="FAKE_TOKEN"):
            pc.send_telegram(msg)

        assert len(captured_payload) == 1
        payload = json.loads(captured_payload[0])
        assert "[ThoPAS|plausibility]" in payload["text"]
        assert payload["chat_id"] == "5955462676"


# ---------------------------------------------------------------------------
# Cooldown-Logik
# ---------------------------------------------------------------------------


class TestCooldown:
    def test_cooldown_initial_not_active(self, tmp_path, monkeypatch):
        """Ohne Cooldown-File ist Cooldown nicht aktiv."""
        import plausibility_check as pc
        monkeypatch.setattr(pc, "COOLDOWN_FILE", tmp_path / ".plausibility_lastalert")
        assert pc._cooldown_active() is False

    def test_cooldown_nach_set_aktiv(self, tmp_path, monkeypatch):
        """Nach _set_cooldown() ist Cooldown heute aktiv."""
        import plausibility_check as pc
        monkeypatch.setattr(pc, "COOLDOWN_FILE", tmp_path / ".plausibility_lastalert")
        pc._set_cooldown()
        assert pc._cooldown_active() is True

    def test_cooldown_altes_datum_nicht_aktiv(self, tmp_path, monkeypatch):
        """Cooldown vom Vortag ist nicht aktiv."""
        import plausibility_check as pc
        f = tmp_path / ".plausibility_lastalert"
        f.write_text("2020-01-01")
        monkeypatch.setattr(pc, "COOLDOWN_FILE", f)
        assert pc._cooldown_active() is False
