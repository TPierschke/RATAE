"""Unit-Tests fuer ingest/web_scraper.py — mit HTML-Fixtures aus cmi-crawl.

KEIN echter CMI-Call! Alle Tests arbeiten mit lokalen HTML-Snapshots.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from wp_state_machine.ingest.web_scraper import (
    _is_aus,
    _is_ein,
    _parse_betriebsart,
    _parse_temp,
    load_fixture,
    merge_scrape_results,
    parse_fbheiz_detail,
    parse_functions_overview,
    parse_outputs_page,
)

FIXTURES_DIR = Path(__file__).parents[1] / "fixtures" / "menupage_pages"


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------


class TestParseTempHelper:
    def test_temp_with_mojibake(self):
        assert _parse_temp("12,3 Â°C") == pytest.approx(12.3)

    def test_temp_with_real_degree(self):
        assert _parse_temp("12,3 °C") == pytest.approx(12.3)

    def test_temp_negative(self):
        assert _parse_temp("-5,2 °C") == pytest.approx(-5.2)

    def test_temp_integer(self):
        assert _parse_temp("27 °C") == pytest.approx(27.0)

    def test_temp_none_on_dash(self):
        assert _parse_temp("-----") is None

    def test_temp_none_on_empty(self):
        assert _parse_temp("") is None

    def test_temp_none_on_text(self):
        assert _parse_temp("EIN") is None

    def test_temp_with_dot(self):
        assert _parse_temp("35.5 °C") == pytest.approx(35.5)


class TestIsEinAus:
    def test_ein_variants(self):
        assert _is_ein("EIN")
        assert _is_ein("AUTO/EIN")
        assert _is_ein("  ein  ")

    def test_aus_variants(self):
        assert _is_aus("AUS")
        assert _is_aus("AUTO/AUS")
        assert _is_aus("  aus  ")

    def test_ein_false_for_aus(self):
        assert not _is_ein("AUTO/AUS")

    def test_aus_false_for_ein(self):
        assert not _is_aus("AUTO/EIN")


class TestParseBetriebsart:
    def test_normal(self):
        assert _parse_betriebsart("NORMAL") == 3

    def test_standby(self):
        assert _parse_betriebsart("STANDBY") == 1

    def test_abgesenkt(self):
        assert _parse_betriebsart("ABGESENKT") == 4

    def test_auto(self):
        assert _parse_betriebsart("AUTO") == 2

    def test_unknown_returns_none(self):
        assert _parse_betriebsart("IRGENDWAS") is None

    def test_case_insensitive(self):
        assert _parse_betriebsart("normal") == 3


# ---------------------------------------------------------------------------
# Fixture-Lader
# ---------------------------------------------------------------------------


class TestLoadFixture:
    def test_loads_existing_fixture(self):
        html = load_fixture("3E01581E", FIXTURES_DIR)
        assert len(html) > 100
        assert "FBHEIZ" in html or "BETRIEB" in html

    def test_raises_on_missing(self):
        with pytest.raises(FileNotFoundError):
            load_fixture("DOESNOTEXIST", FIXTURES_DIR)


# ---------------------------------------------------------------------------
# Parse Outputs Page (3E005806)
# ---------------------------------------------------------------------------


class TestParseOutputsPage:
    @pytest.fixture
    def outputs_html(self) -> str:
        return load_fixture("3E005806", FIXTURES_DIR)

    def test_parses_without_error(self, outputs_html: str):
        result = parse_outputs_page(outputs_html)
        assert isinstance(result, dict)

    def test_verdichter_present(self, outputs_html: str):
        result = parse_outputs_page(outputs_html)
        assert "verdichter" in result

    def test_ventil_ww_present(self, outputs_html: str):
        result = parse_outputs_page(outputs_html)
        assert "ventil_ww" in result

    def test_alarm_present(self, outputs_html: str):
        result = parse_outputs_page(outputs_html)
        assert "alarm" in result

    def test_heizstab_hz_present(self, outputs_html: str):
        result = parse_outputs_page(outputs_html)
        assert "heizstab_hz" in result

    def test_heizstab_ww_present(self, outputs_html: str):
        result = parse_outputs_page(outputs_html)
        assert "heizstab_ww" in result

    def test_pumpe_zirku_present(self, outputs_html: str):
        result = parse_outputs_page(outputs_html)
        assert "pumpe_zirku" in result

    def test_values_are_bool(self, outputs_html: str):
        result = parse_outputs_page(outputs_html)
        for key in ["verdichter", "ventil_ww", "alarm", "heizstab_hz", "heizstab_ww"]:
            if key in result and result[key] is not None:
                assert isinstance(result[key], bool), f"{key} sollte bool sein, ist {type(result[key])}"

    def test_verdichter_aus_in_fixture(self, outputs_html: str):
        """Im gespeicherten Fixture laeuft Verdichter AUS (AUTO/AUS)."""
        result = parse_outputs_page(outputs_html)
        assert result.get("verdichter") is False

    def test_heizstaebe_aus_in_fixture(self, outputs_html: str):
        """Heizstaebe sollen im Normalfall AUS sein."""
        result = parse_outputs_page(outputs_html)
        assert result.get("heizstab_hz") is False
        assert result.get("heizstab_ww") is False

    def test_alarm_aus_in_fixture(self, outputs_html: str):
        result = parse_outputs_page(outputs_html)
        assert result.get("alarm") is False


# ---------------------------------------------------------------------------
# Parse Functions Overview (3E01581E)
# ---------------------------------------------------------------------------


class TestParseFunctionsOverview:
    @pytest.fixture
    def functions_html(self) -> str:
        return load_fixture("3E01581E", FIXTURES_DIR)

    def test_parses_without_error(self, functions_html: str):
        result = parse_functions_overview(functions_html)
        assert isinstance(result, dict)

    def test_betriebsart_present(self, functions_html: str):
        result = parse_functions_overview(functions_html)
        assert "betriebsart" in result, f"betriebsart fehlt in: {result}"

    def test_betriebsart_is_normal(self, functions_html: str):
        """Im Fixture ist Betrieb NORMAL (= 3)."""
        result = parse_functions_overview(functions_html)
        assert result.get("betriebsart") == 3

    def test_normal_soll_present(self, functions_html: str):
        result = parse_functions_overview(functions_html)
        assert "normal_soll" in result

    def test_normal_soll_range(self, functions_html: str):
        result = parse_functions_overview(functions_html)
        soll = result.get("normal_soll")
        if soll is not None:
            assert 10 <= float(soll) <= 30, f"normal_soll={soll} ausserhalb Bereich"

    def test_absenk_soll_present(self, functions_html: str):
        result = parse_functions_overview(functions_html)
        assert "absenk_soll" in result

    def test_aussen_temp_present(self, functions_html: str):
        result = parse_functions_overview(functions_html)
        assert "aussen" in result, f"aussen fehlt, result={result}"

    def test_aussen_temp_plausible(self, functions_html: str):
        result = parse_functions_overview(functions_html)
        t = result.get("aussen")
        if t is not None:
            assert -30 <= float(t) <= 50, f"aussen={t} unplausibel"

    def test_vorlauf_temp_present(self, functions_html: str):
        result = parse_functions_overview(functions_html)
        assert "vorlauf" in result or "vorlauf_ist" in result

    def test_warmwasser_temp_present(self, functions_html: str):
        result = parse_functions_overview(functions_html)
        assert "warmwasser" in result, f"warmwasser fehlt: {result}"


# ---------------------------------------------------------------------------
# Parse FBHEIZ Detail (3E01580E)
# ---------------------------------------------------------------------------


class TestParseFbheizDetail:
    @pytest.fixture
    def fbheiz_html(self) -> str:
        return load_fixture("3E01580E", FIXTURES_DIR)

    def test_parses_without_error(self, fbheiz_html: str):
        result = parse_fbheiz_detail(fbheiz_html)
        assert isinstance(result, dict)

    def test_betriebsart_normal(self, fbheiz_html: str):
        result = parse_fbheiz_detail(fbheiz_html)
        assert result.get("betriebsart") == 3

    def test_normal_soll_24(self, fbheiz_html: str):
        result = parse_fbheiz_detail(fbheiz_html)
        soll = result.get("normal_soll")
        assert soll is not None
        assert float(soll) == pytest.approx(24.0)

    def test_absenk_soll_21(self, fbheiz_html: str):
        result = parse_fbheiz_detail(fbheiz_html)
        soll = result.get("absenk_soll")
        assert soll is not None
        assert float(soll) == pytest.approx(21.0)


# ---------------------------------------------------------------------------
# merge_scrape_results
# ---------------------------------------------------------------------------


class TestMergeScrapeResults:
    def test_merge_combines_dicts(self):
        outputs = {"verdichter": False, "alarm": False}
        functions = {"betriebsart": 3, "normal_soll": 24.0}
        merged = merge_scrape_results(outputs, functions)
        assert merged["verdichter"] is False
        assert merged["betriebsart"] == 3

    def test_functions_override_outputs(self):
        outputs = {"verdichter": False, "betriebsart": 1}
        functions = {"betriebsart": 3}
        merged = merge_scrape_results(outputs, functions)
        assert merged["betriebsart"] == 3

    def test_empty_inputs(self):
        merged = merge_scrape_results({}, {})
        assert merged == {}
