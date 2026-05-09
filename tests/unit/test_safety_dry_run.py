from __future__ import annotations

from wp_state_machine.safety import WHITELIST, check_write


def test_check_write_default_global_dry_run_is_true():
    result = check_write("3E9001301C", 3)

    assert result.effective_dry_run is True


def test_check_write_global_dry_run_false_no_override():
    result = check_write("3E9001301C", 3, global_dry_run=False)

    assert result.effective_dry_run is False


def test_check_write_address_override_true_wins(monkeypatch):
    monkeypatch.setitem(WHITELIST["3E9001301C"], "dry_run_override", True)

    result = check_write("3E9001301C", 3, global_dry_run=False)

    assert result.effective_dry_run is True


def test_check_write_forbidden_address_yields_none_dry_run():
    result = check_write("3E80153125", 1)

    assert result.allowed is False
    assert result.effective_dry_run is None
