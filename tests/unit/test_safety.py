"""Unit-Tests fuer safety.py — Whitelist-Enforcement.

Tests duerfen NIEMALS einen echten CMI-Call machen!
"""

from __future__ import annotations

import pytest

from wp_state_machine.safety import (
    FORBIDDEN_EXACT,
    FORBIDDEN_PREFIXES,
    WHITELIST,
    WhitelistResult,
    check_write,
    get_whitelist_info,
)


# ---------------------------------------------------------------------------
# Whitelist — erlaubte Schreibzugriffe
# ---------------------------------------------------------------------------


class TestWhitelistAllowed:
    def test_betriebsart_standby(self):
        r = check_write("3E9001301C", 1)
        assert r.allowed is True
        assert r.address == "3E9001301C"

    def test_betriebsart_normal(self):
        r = check_write("3E9001301C", 3)
        assert r.allowed is True

    def test_ww_start(self):
        r = check_write("3E80093125", 1)
        assert r.allowed is True

    def test_ww_stop(self):
        r = check_write("3E80093126", 1)
        assert r.allowed is True

    def test_address_lowercase_normalized(self):
        """Lowercase-Adressen werden normalisiert."""
        r = check_write("3e9001301c", 3)
        assert r.allowed is True

    def test_address_with_spaces_normalized(self):
        """Leerzeichen werden getrimmt."""
        r = check_write("  3E9001301C  ", 3)
        assert r.allowed is True


# ---------------------------------------------------------------------------
# Verbotene Betriebsart-Werte
# ---------------------------------------------------------------------------


class TestBetriebsartInvalidValues:
    def test_betriebsart_zero_blocked(self):
        r = check_write("3E9001301C", 0)
        assert r.allowed is False
        assert "0" in r.reason or "AUSSERHALB" in r.reason

    def test_betriebsart_zeit_blocked(self):
        """Wert 2 (Zeit/Auto) nicht mehr erlaubt seit User-Regel 2026-05-15."""
        r = check_write("3E9001301C", 2)
        assert r.allowed is False

    def test_betriebsart_abgesenkt_blocked(self):
        """Wert 4 (Abgesenkt) nicht erlaubt — nur ueber CMI/Anlage selbst."""
        r = check_write("3E9001301C", 4)
        assert r.allowed is False

    def test_betriebsart_party_blocked(self):
        r = check_write("3E9001301C", 5)
        assert r.allowed is False

    def test_betriebsart_urlaub_blocked(self):
        r = check_write("3E9001301C", 6)
        assert r.allowed is False

    def test_betriebsart_feiertag_blocked(self):
        r = check_write("3E9001301C", 7)
        assert r.allowed is False

    def test_betriebsart_eight_blocked(self):
        r = check_write("3E9001301C", 8)
        assert r.allowed is False

    def test_betriebsart_negative_blocked(self):
        r = check_write("3E9001301C", -1)
        assert r.allowed is False


# ---------------------------------------------------------------------------
# Sollwert-Adressen seit User-Regel 2026-05-15 NICHT mehr in Whitelist
# (nur ueber CMI/Anlage direkt aenderbar — WW-Soll disruptiv: HD-Schalter-Risiko)
# ---------------------------------------------------------------------------


class TestSollwertNoLongerWhitelisted:
    def test_normalsoll_now_blocked(self):
        """3EB001300C Normalsoll seit 2026-05-15 nicht mehr automatisiert setzbar."""
        r = check_write("3EB001300C", 22)
        assert r.allowed is False
        assert "WHITELIST" in r.reason

    def test_absenksoll_now_blocked(self):
        """3EB001300D Absenksoll seit 2026-05-15 nicht mehr automatisiert setzbar."""
        r = check_write("3EB001300D", 18)
        assert r.allowed is False
        assert "WHITELIST" in r.reason

    def test_wwsoll_now_blocked(self):
        """3EB0023118 WW-Soll seit 2026-05-15 raus — HD-Schalter-Risiko bei >50 Grad."""
        r = check_write("3EB0023118", 50)
        assert r.allowed is False
        assert "WHITELIST" in r.reason


# ---------------------------------------------------------------------------
# Heizstab direkt — explizit verboten
# ---------------------------------------------------------------------------


class TestHeizstabForbidden:
    def test_heizstab_direkt_start_blocked(self):
        """F:21 WW_ANF.9 Heizstab-Direkt ist absolut verboten."""
        r = check_write("3E80153125", 1)
        assert r.allowed is False
        assert "VERBOTEN" in r.reason

    def test_heizstab_direkt_stop_blocked(self):
        r = check_write("3E80153126", 1)
        assert r.allowed is False

    def test_ww_start_value_not_one_blocked(self):
        """Nur value=1 ist fuer WW-Start erlaubt."""
        r = check_write("3E80093125", 0)
        assert r.allowed is False

    def test_ww_start_value_two_blocked(self):
        r = check_write("3E80093125", 2)
        assert r.allowed is False


# ---------------------------------------------------------------------------
# Direkte Aktor-Ausgaenge gesperrt (Praefix 3E91)
# ---------------------------------------------------------------------------


class TestForbiddenOutputs:
    def test_ausgang_a1_blocked(self):
        """Direkte Output-Schaltung A1 gesperrt."""
        r = check_write("3E910120A1", 1)
        assert r.allowed is False
        assert "3E91" in r.reason or "VERBOTEN" in r.reason

    def test_ausgang_a3_verdichter_blocked(self):
        """A3 = Verdichter — niemals direkt schalten."""
        r = check_write("3E910320A1", 1)
        assert r.allowed is False

    def test_ausgang_a8_heizstab_hz_blocked(self):
        """A8 = HeizstabHZ — DANGEROUS OUTPUT."""
        r = check_write("3E910820A1", 1)
        assert r.allowed is False

    def test_ausgang_a9_heizstab_ww_blocked(self):
        """A9 = HeizstabWW — DANGEROUS OUTPUT."""
        r = check_write("3E910920A1", 1)
        assert r.allowed is False

    def test_ausgang_a10_zirkulation_blocked(self):
        r = check_write("3E910A20A1", 1)
        assert r.allowed is False

    @pytest.mark.parametrize(
        "addr",
        [
            "3E910120A1",
            "3E910220A1",
            "3E910320A1",
            "3E910420A1",
            "3E910520A1",
            "3E910620A1",
            "3E910720A1",
            "3E910820A1",
            "3E910920A1",
            "3E910A20A1",
        ],
    )
    def test_all_output_addresses_blocked(self, addr: str):
        r = check_write(addr, 1)
        assert r.allowed is False, f"Adresse {addr} sollte gesperrt sein"


# ---------------------------------------------------------------------------
# Unbekannte Adressen
# ---------------------------------------------------------------------------


class TestUnknownAddresses:
    def test_unknown_address_blocked(self):
        r = check_write("3EDEADBEEF", 1)
        assert r.allowed is False
        assert "WHITELIST" in r.reason

    def test_heizkurve_address_blocked(self):
        """Heizkurven-Adressen sind NICHT in Phase-1-Whitelist."""
        r = check_write("3EB001300F", 35)
        assert r.allowed is False

    def test_empty_address_blocked(self):
        r = check_write("", 1)
        assert r.allowed is False

    def test_ww_soll_no_longer_whitelisted(self):
        """Seit 2026-05-15 ist WW-Soll wieder geblockt — HD-Schalter-Risiko bei >50 Grad."""
        r = check_write("3EB0023118", 50)
        assert r.allowed is False
        assert "WHITELIST" in r.reason


# ---------------------------------------------------------------------------
# WhitelistResult-Datentyp
# ---------------------------------------------------------------------------


class TestWhitelistResult:
    def test_result_is_frozen_dataclass(self):
        r = check_write("3E9001301C", 3)
        with pytest.raises(Exception):
            r.allowed = False  # type: ignore[misc]

    def test_result_has_reason(self):
        r = check_write("3E9001301C", 3)
        assert isinstance(r.reason, str)
        assert len(r.reason) > 0

    def test_blocked_result_has_reason(self):
        r = check_write("3E80153125", 1)
        assert isinstance(r.reason, str)
        assert len(r.reason) > 0


# ---------------------------------------------------------------------------
# Whitelist-Info
# ---------------------------------------------------------------------------


class TestGetWhitelistInfo:
    def test_returns_all_whitelisted_addresses(self):
        info = get_whitelist_info()
        for addr in WHITELIST:
            assert addr in info

    def test_sets_converted_to_lists(self):
        """Sets werden zu Listen konvertiert fuer JSON-Serialisierbarkeit."""
        info = get_whitelist_info()
        for entry in info.values():
            if "allowed_values" in entry:
                assert isinstance(entry["allowed_values"], list)

    def test_info_is_copy_not_reference(self):
        """Whitelist-Info ist eine Kopie — kein Zugriff auf interne Daten."""
        info1 = get_whitelist_info()
        info2 = get_whitelist_info()
        assert info1 == info2


# ---------------------------------------------------------------------------
# Invarianten der Konstanten
# ---------------------------------------------------------------------------


class TestConstants:
    def test_forbidden_exact_contains_heizstab(self):
        assert "3E80153125" in FORBIDDEN_EXACT

    def test_forbidden_prefixes_contains_3e91(self):
        assert "3E91" in FORBIDDEN_PREFIXES

    def test_whitelist_has_three_entries(self):
        """Phase 2 (seit 2026-05-15, User-Regel): 3 Adressen — Betriebsart + WW-Start + WW-Stop."""
        assert len(WHITELIST) == 3

    def test_whitelist_contains_betriebsart(self):
        assert "3E9001301C" in WHITELIST

    def test_whitelist_contains_ww_start(self):
        assert "3E80093125" in WHITELIST

    def test_whitelist_contains_ww_stop(self):
        assert "3E80093126" in WHITELIST

    def test_whitelist_betriebsart_only_standby_normal(self):
        """Nur Werte 1 und 3 erlaubt fuer Betriebsart."""
        entry = WHITELIST["3E9001301C"]
        assert entry["allowed_values"] == {1, 3}
