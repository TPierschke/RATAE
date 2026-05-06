"""Unit-Tests fuer ingest/json_poller.py.

KEIN echter CMI-Call! Alle Tests arbeiten mit gemockten Response-Dicts.
"""

from __future__ import annotations

import pytest

from wp_state_machine.ingest.json_poller import (
    CMI_STATUS_OK,
    CMI_STATUS_TOO_MANY_REQUESTS,
    parse_json_api_response,
    check_status_code,
)

# Beispiel-Response aus echter CMI JSON-API (anonymisiert)
SAMPLE_RESPONSE_OK = {
    "StatusCode": 0,
    "Data": {
        "Inputs": [
            {"Value": 12.3, "Unit": "°C"},   # I1: Aussen
            {"Value": 27.5, "Unit": "°C"},   # I2: Vorlauf
            {"Value": 30.8, "Unit": "°C"},   # I3: Ruecklauf
            {"Value": 50.7, "Unit": "°C"},   # I4: WW
            {},                               # I5: unbenutzt
            {},                               # I6: unbenutzt
            {"Value": 41.2, "Unit": "°C"},   # I7: Heissgas
            {"Value": 15.1, "Unit": "°C"},   # I8: Fluessigkeit
            {"Value": 5.3, "Unit": "°C"},    # I9: Saugleitung
            {"Value": 1, "Unit": ""},         # I10: Phasenwaechter (Digital)
            {"Value": 1, "Unit": ""},         # I11: Verdichter-Freigabe (Digital)
            {"Value": 0, "Unit": ""},         # I12: ND-Schalter1
            {"Value": 1, "Unit": ""},         # I13: HD-Schalter
            {"Value": 0, "Unit": ""},         # I14: ND-Schalter2
        ],
        "Outputs": []  # CMI-Bug: immer leer
    }
}

SAMPLE_RESPONSE_TOO_MANY = {"StatusCode": 4}

SAMPLE_RESPONSE_ERROR = {"StatusCode": 99, "Data": {}}

SAMPLE_RESPONSE_EMPTY_DATA = {"StatusCode": 0, "Data": {"Inputs": []}}


class TestParseJsonApiResponse:
    def test_parses_aussen_temp(self):
        result = parse_json_api_response(SAMPLE_RESPONSE_OK)
        assert "aussen" in result
        assert result["aussen"] == pytest.approx(12.3)

    def test_parses_vorlauf_temp(self):
        result = parse_json_api_response(SAMPLE_RESPONSE_OK)
        assert result.get("vorlauf") == pytest.approx(27.5)

    def test_parses_ruecklauf_temp(self):
        result = parse_json_api_response(SAMPLE_RESPONSE_OK)
        assert result.get("ruecklauf") == pytest.approx(30.8)

    def test_parses_warmwasser_temp(self):
        result = parse_json_api_response(SAMPLE_RESPONSE_OK)
        assert result.get("warmwasser") == pytest.approx(50.7)

    def test_parses_heissgas_temp(self):
        result = parse_json_api_response(SAMPLE_RESPONSE_OK)
        assert result.get("heissgas") == pytest.approx(41.2)

    def test_parses_digital_phasenwaechter(self):
        result = parse_json_api_response(SAMPLE_RESPONSE_OK)
        assert result.get("phasenwaechter") is True

    def test_parses_digital_verdichter_freigabe(self):
        result = parse_json_api_response(SAMPLE_RESPONSE_OK)
        assert result.get("verdichter_freigabe") is True

    def test_parses_digital_nd_schalter1_false(self):
        result = parse_json_api_response(SAMPLE_RESPONSE_OK)
        assert result.get("nd_schalter1") is False

    def test_too_many_requests_returns_empty(self):
        result = parse_json_api_response(SAMPLE_RESPONSE_TOO_MANY)
        assert result == {}

    def test_error_status_returns_empty(self):
        result = parse_json_api_response(SAMPLE_RESPONSE_ERROR)
        assert result == {}

    def test_empty_inputs_returns_empty(self):
        result = parse_json_api_response(SAMPLE_RESPONSE_EMPTY_DATA)
        assert result == {}

    def test_outputs_ignored(self):
        """Outputs aus JSON-API werden ignoriert (CMI-Bug)."""
        response = {
            "StatusCode": 0,
            "Data": {
                "Inputs": [{"Value": 10.0, "Unit": "°C"}],
                "Outputs": [{"Value": 1, "Unit": ""}]
            }
        }
        result = parse_json_api_response(response)
        # Outputs duerfen nicht im Ergebnis landen als Output-Felder
        assert "verdichter" not in result  # Outputs ignoriert

    def test_missing_value_skipped(self):
        response = {
            "StatusCode": 0,
            "Data": {"Inputs": [{}]}  # I1 ohne Value
        }
        result = parse_json_api_response(response)
        assert "aussen" not in result

    def test_returns_dict(self):
        result = parse_json_api_response(SAMPLE_RESPONSE_OK)
        assert isinstance(result, dict)

    def test_no_side_effects_on_input(self):
        """Input-Dict nicht veraendern."""
        original = dict(SAMPLE_RESPONSE_OK)
        parse_json_api_response(SAMPLE_RESPONSE_OK)
        assert SAMPLE_RESPONSE_OK == original


class TestCheckStatusCode:
    def test_ok_status(self):
        ok, msg = check_status_code({"StatusCode": 0})
        assert ok is True
        assert "OK" in msg

    def test_too_many_requests(self):
        ok, msg = check_status_code({"StatusCode": 4})
        assert ok is False
        assert "TOO_MANY" in msg or "warten" in msg.lower()

    def test_unknown_status(self):
        ok, msg = check_status_code({"StatusCode": 99})
        assert ok is False

    def test_missing_status_code(self):
        ok, msg = check_status_code({})
        assert ok is False

    def test_constants_correct(self):
        assert CMI_STATUS_OK == 0
        assert CMI_STATUS_TOO_MANY_REQUESTS == 4
