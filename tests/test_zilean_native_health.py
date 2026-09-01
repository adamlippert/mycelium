"""Native-mode Zilean (ZILEAN_MODE=native, the built-in SQLite index) has no
URL by design. The health plumbing required one anyway, which did two bad
things: scrapers._active() skipped the native index for every search (it was
enabled, working, and never queried), and both status surfaces showed it as
permanently down / disabled.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import health
import health_cache
import zilean_index


@pytest.fixture(autouse=True)
def _fresh_health_cache():
    with health_cache._lock:
        health_cache._cache.clear()
    yield
    with health_cache._lock:
        health_cache._cache.clear()


def _native_settings(monkeypatch, extra=None):
    values = {"ZILEAN_ENABLED": True, "ZILEAN_MODE": "native", **(extra or {})}
    monkeypatch.setattr(health_cache._settings, "get",
                        lambda k, d=None: values.get(k, d))
    return values


def test_native_zilean_is_up_without_a_url(monkeypatch):
    """The bug that mattered most: is_up gated every search through a URL
    check, so the enabled, working native index was never queried at all."""
    _native_settings(monkeypatch)
    monkeypatch.setattr(zilean_index, "get_status", lambda: {"total_hashes": 5})

    assert health_cache.is_up("zilean") is True


def test_native_zilean_is_down_when_the_index_cannot_open(monkeypatch):
    _native_settings(monkeypatch)
    def boom():
        raise RuntimeError("db locked")
    monkeypatch.setattr(zilean_index, "get_status", boom)

    assert health_cache.is_up("zilean") is False


def test_external_mode_still_requires_a_url(monkeypatch):
    values = {"ZILEAN_ENABLED": True, "ZILEAN_MODE": "external", "ZILEAN_URL": ""}
    monkeypatch.setattr(health_cache._settings, "get",
                        lambda k, d=None: values.get(k, d))
    monkeypatch.setattr(health_cache, "_ZILEAN_URL_DEFAULT", "")

    assert health_cache.is_up("zilean") is False


def test_check_all_reports_the_native_index_without_pinging(monkeypatch):
    pinged = []
    monkeypatch.setattr(health, "_ping",
                        lambda name, url, **kw: (pinged.append(name),
                                                 {"name": name, "status": "ok"})[1])
    values = {"ZILEAN_ENABLED": True, "ZILEAN_MODE": "native",
              "DEBRIDIO_ENABLED": False, "TORBOX_API_KEY": "x"}
    monkeypatch.setattr(health.settings, "get", lambda k, d=None: values.get(k, d))
    monkeypatch.setattr(zilean_index, "get_status", lambda: {"total_hashes": 12345})

    row = [s for s in health.check_all() if s["name"] == "Zilean"][0]

    assert row["status"] == "ok"
    assert "12345" in row.get("note", "")
    assert "Zilean" not in pinged, "native mode must not HTTP-ping anything"
