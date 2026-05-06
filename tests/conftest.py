"""pytest conftest — shared fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def menupage_fixtures_dir() -> Path:
    """Verzeichnis mit HTML-Snapshots der CMI-Seiten."""
    return FIXTURES_DIR / "menupage_pages"


@pytest.fixture
def coe_packets() -> list[dict]:
    """Beispiel CoE-UDP-Pakete fuer Tests."""
    fp = FIXTURES_DIR / "coe_packets.json"
    if fp.exists():
        return json.loads(fp.read_text())
    return []
