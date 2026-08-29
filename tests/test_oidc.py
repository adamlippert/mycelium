import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

sys.modules.pop("settings", None)

import pytest

import config as cfg
import db
import oidc
import settings


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init()
    yield


@pytest.fixture(autouse=True)
def _oidc_configured(monkeypatch):
    """Required non-toggle vars present, as they would be for any real deployment."""
    monkeypatch.setattr(cfg, "OIDC_ISSUER_URL", "https://idp.example.com")
    monkeypatch.setattr(cfg, "OIDC_CLIENT_ID", "mycelium")
    yield


def test_is_enabled_true_when_config_enabled_and_no_override(monkeypatch):
    monkeypatch.setattr(cfg, "OIDC_ENABLED", True)
    assert oidc.is_enabled() is True


def test_is_enabled_honours_settings_overlay_when_disabled():
    """Unticking OIDC in the UI stores OIDC_ENABLED=False in the DB overlay;
    is_enabled() must consult it, not just the static config default."""
    settings.set("OIDC_ENABLED", False)
    assert oidc.is_enabled() is False


def test_is_enabled_honours_settings_overlay_when_enabled():
    settings.set("OIDC_ENABLED", True)
    assert oidc.is_enabled() is True


def test_is_enabled_false_without_issuer_or_client_even_if_overlay_enabled(monkeypatch):
    monkeypatch.setattr(cfg, "OIDC_ISSUER_URL", "")
    settings.set("OIDC_ENABLED", True)
    assert oidc.is_enabled() is False
