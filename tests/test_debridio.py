import base64
import json
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import debridio


@pytest.fixture
def configured(monkeypatch):
    values = {"DEBRIDIO_API_KEY": "dk" * 16, "TORBOX_API_KEY": "tb-uuid-value",
              "DEBRIDIO_BASE_URL": "https://addon.debridio.com",
              "DEBRIDIO_MAX_RESULTS": 100, "DEBRIDIO_CONFIG_TOKEN": "",
              "DEBRIDIO_ENABLED": True}
    monkeypatch.setattr(debridio._settings, "get",
                        lambda k, d=None: values.get(k, d))
    return values


def _decode(token):
    return json.loads(base64.b64decode(token))


def test_config_contains_both_credentials(configured):
    cfg = _decode(debridio.build_config_token())
    assert cfg["api_key"] == "dk" * 16
    assert cfg["providerKey"] == "tb-uuid-value"
    assert cfg["provider"] == "torbox"


def test_config_is_permissive(configured):
    # Mycelium's filters are soft and Debridio's are hard. Pushing ours down
    # would stop the "only remux available; allowing them" fallback firing.
    cfg = _decode(debridio.build_config_token())
    assert cfg["excludedQualities"] == []
    assert cfg["preferredLang"] == []
    assert cfg["maxSize"] == ""
    assert cfg["disableUncached"] is False
    assert "unknown" in cfg["resolutions"]
    for res in ("8k", "4k", "1440p", "1080p", "720p", "480p", "360p"):
        assert res in cfg["resolutions"]


def test_config_token_override_is_used_verbatim(monkeypatch):
    monkeypatch.setattr(debridio._settings, "get",
                        lambda k, d=None: "PREBUILT" if k == "DEBRIDIO_CONFIG_TOKEN" else d)
    assert debridio.build_config_token() == "PREBUILT"


def test_unconfigured_returns_empty_token(monkeypatch):
    monkeypatch.setattr(debridio._settings, "get", lambda k, d=None: d)
    assert debridio.build_config_token() == ""
    assert debridio.is_configured() is False


def test_is_configured_requires_both_keys(monkeypatch):
    monkeypatch.setattr(debridio._settings, "get",
                        lambda k, d=None: "x" if k == "DEBRIDIO_API_KEY" else d)
    monkeypatch.setattr(debridio.config, "TORBOX_API_KEY", "")
    assert debridio.is_configured() is False


def test_redact_removes_the_config_segment():
    url = "https://addon.debridio.com/eyJhcGlfa2V5IjoiEXAMPLE/stream/movie/tt1.json"
    out = debridio.redact(url)
    assert "eyJhcGlfa2V5" not in out
    assert "addon.debridio.com" in out


def test_redact_removes_credentials_from_a_play_url():
    url = ("https://addon.debridio.com/play/movie/torbox/"
           + "d" * 32 + "/tb-uuid-value/" + "a" * 40 + "/File.mkv")
    out = debridio.redact(url)
    assert "d" * 32 not in out
    assert "tb-uuid-value" not in out


def test_redact_handles_none_and_empty():
    assert debridio.redact("") == ""
    assert debridio.redact(None) == ""


def test_redact_scrubs_the_live_credential_values(configured):
    msg = "Error for url: https://x/" + "dk" * 16 + "/y and key tb-uuid-value"
    out = debridio.redact(msg)
    assert "dk" * 16 not in out
    assert "tb-uuid-value" not in out
