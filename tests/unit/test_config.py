"""Unit-Tests fuer config.py."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from wp_state_machine.config import Config


@pytest.fixture(autouse=True)
def reset_config_singleton():
    """Singleton nach jedem Test zuruecksetzen."""
    Config.reset()
    yield
    Config.reset()


@pytest.fixture
def tmp_env(tmp_path: Path) -> Path:
    f = tmp_path / ".env"
    f.write_text("DRY_RUN=true\nCMI_HOST=10.0.0.1\nCMI_USER=testuser\nCMI_PASS=testpass\n")
    return f


@pytest.fixture
def tmp_toml(tmp_path: Path) -> Path:
    f = tmp_path / "config.toml"
    f.write_text(
        """
[cmi]
poll_interval_seconds = 30
request_timeout_seconds = 5

[web]
port = 9999
host = "127.0.0.1"

[safety]
dry_run = true

[mqtt]
enabled = false

[telegram]
enabled = false
"""
    )
    return f


class TestConfigDefaults:
    def test_dry_run_default_is_true(self):
        """DRY_RUN muss default True sein — Sicherheit."""
        cfg = Config(env_path=Path("/nonexistent/.env"), config_path=Path("/nonexistent/c.toml"))
        assert cfg.dry_run is True

    def test_cmi_host_default(self):
        cfg = Config(env_path=Path("/nonexistent"), config_path=Path("/nonexistent"))
        assert cfg.cmi_host == "192.168.178.45"

    def test_port_default(self):
        cfg = Config(env_path=Path("/nonexistent"), config_path=Path("/nonexistent"))
        assert cfg.port == 8765

    def test_mqtt_disabled_default(self):
        cfg = Config(env_path=Path("/nonexistent"), config_path=Path("/nonexistent"))
        assert cfg.mqtt_enabled is False

    def test_telegram_disabled_default(self):
        cfg = Config(env_path=Path("/nonexistent"), config_path=Path("/nonexistent"))
        assert cfg.telegram_enabled is False


class TestConfigFromEnv:
    def test_loads_env_file(self, tmp_env: Path):
        cfg = Config(env_path=tmp_env, config_path=Path("/nonexistent"))
        assert cfg.cmi_host == "10.0.0.1"
        assert cfg.cmi_user == "testuser"

    def test_dry_run_false_from_env(self, tmp_path: Path):
        env = tmp_path / ".env"
        env.write_text("DRY_RUN=false\n")
        cfg = Config(env_path=env, config_path=Path("/nonexistent"))
        assert cfg.dry_run is False

    def test_dry_run_true_from_env(self, tmp_path: Path):
        env = tmp_path / ".env"
        env.write_text("DRY_RUN=true\n")
        cfg = Config(env_path=env, config_path=Path("/nonexistent"))
        assert cfg.dry_run is True

    def test_env_overrides_toml(self, tmp_path: Path, tmp_toml: Path):
        env = tmp_path / ".env"
        env.write_text("PORT=1234\n")
        cfg = Config(env_path=env, config_path=tmp_toml)
        assert cfg.port == 1234


class TestConfigFromToml:
    def test_loads_toml(self, tmp_toml: Path):
        cfg = Config(env_path=Path("/nonexistent"), config_path=tmp_toml)
        assert cfg.cmi_poll_interval == 30.0
        assert cfg.cmi_timeout == 5.0
        assert cfg.port == 9999
        assert cfg.host == "127.0.0.1"

    def test_missing_toml_uses_defaults(self):
        cfg = Config(env_path=Path("/nonexistent"), config_path=Path("/nonexistent/x.toml"))
        assert cfg.cmi_poll_interval == 60.0


class TestSingleton:
    def test_load_returns_same_instance(self, tmp_env: Path, tmp_toml: Path):
        c1 = Config.load(env_path=tmp_env, config_path=tmp_toml)
        c2 = Config.load(env_path=tmp_env, config_path=tmp_toml)
        assert c1 is c2

    def test_reset_clears_singleton(self, tmp_env: Path, tmp_toml: Path):
        c1 = Config.load(env_path=tmp_env, config_path=tmp_toml)
        Config.reset()
        c2 = Config.load(env_path=tmp_env, config_path=tmp_toml)
        assert c1 is not c2


class TestUrls:
    def test_cmi_menupage_url(self, tmp_path: Path):
        env = tmp_path / ".env"
        env.write_text("CMI_HOST=192.168.178.45\n")
        cfg = Config(env_path=env, config_path=Path("/nonexistent"))
        url = cfg.cmi_menupage_url("3E01581E")
        assert "192.168.178.45" in url
        assert "3E01581E" in url
        assert "menupage.cgi" in url

    def test_cmi_api_url(self, tmp_path: Path):
        env = tmp_path / ".env"
        env.write_text("CMI_HOST=192.168.178.45\n")
        cfg = Config(env_path=env, config_path=Path("/nonexistent"))
        url = cfg.cmi_api_url()
        assert "jsonnode=62" in url
        assert "api.cgi" in url

    def test_cmi_auth_tuple(self, tmp_path: Path):
        env = tmp_path / ".env"
        env.write_text("CMI_USER=admin\nCMI_PASS=admin\n")
        cfg = Config(env_path=env, config_path=Path("/nonexistent"))
        auth = cfg.cmi_auth()
        assert isinstance(auth, tuple)
        assert len(auth) == 2

    def test_summary_no_secrets(self, tmp_path: Path):
        env = tmp_path / ".env"
        env.write_text("DRY_RUN=true\n")
        cfg = Config(env_path=env, config_path=Path("/nonexistent"))
        s = cfg.summary()
        assert "cmi_pass" not in s
        assert "telegram_token" not in s
        assert "dry_run" in s
        assert "cmi_host" in s
