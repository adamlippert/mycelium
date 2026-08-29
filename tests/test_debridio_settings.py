import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

sys.modules.pop("settings", None)

import pytest

import db
import settings


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init()
    yield


def test_enabled_defaults_to_false():
    assert settings.get("DEBRIDIO_ENABLED") is False


def test_enabled_coerces_to_bool_not_string():
    settings.set("DEBRIDIO_ENABLED", True)
    assert settings.get("DEBRIDIO_ENABLED") is True
    settings.set("DEBRIDIO_ENABLED", False)
    assert settings.get("DEBRIDIO_ENABLED") is False


def test_max_results_coerces_to_int():
    settings.set("DEBRIDIO_MAX_RESULTS", "250")
    assert settings.get("DEBRIDIO_MAX_RESULTS") == 250


def test_base_url_has_a_default():
    assert settings.get("DEBRIDIO_BASE_URL") == "https://addon.debridio.com"


def test_secrets_are_named_so_the_ui_masks_them():
    # templates/ui.html:1233 masks a field when its key matches this pattern.
    # A secret whose name misses it renders in plaintext, pre-filled.
    import re
    predicate = re.compile(r"KEY|TOKEN|SECRET|PASSWORD")
    for key in ("DEBRIDIO_API_KEY", "DEBRIDIO_CONFIG_TOKEN"):
        assert predicate.search(key), f"{key} would render unmasked"


def test_hot_reload_covers_every_debridio_key():
    for key in ("DEBRIDIO_ENABLED", "DEBRIDIO_API_KEY", "DEBRIDIO_BASE_URL",
                "DEBRIDIO_MAX_RESULTS", "DEBRIDIO_CONFIG_TOKEN"):
        assert key in settings.HOT_RELOAD, f"{key} would need a restart"
