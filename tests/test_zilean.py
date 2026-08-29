"""zilean.fetch_streams's raise_on_error flag.

scrapers.py sets raise_on_error=True so a Zilean failure becomes a counted
`failed` instead of silently disappearing into an empty list - see
scrapers._fetch_zilean and tests/test_scraper_outage.py.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import requests

import zilean


@pytest.fixture(autouse=True)
def _external_mode(monkeypatch):
    # ZILEAN_MODE defaults to "external" via this fallback; pin it explicitly
    # so these tests don't depend on real settings.
    monkeypatch.setattr(zilean._settings, "get", lambda k, d=None: d)


def test_external_failure_returns_empty_by_default(monkeypatch):
    def _boom(*a, **k):
        raise requests.RequestException("down")

    monkeypatch.setattr(zilean.requests, "get", _boom)
    assert zilean.fetch_streams("tt1") == []


def test_external_failure_propagates_when_raise_on_error(monkeypatch):
    def _boom(*a, **k):
        raise requests.RequestException("down")

    monkeypatch.setattr(zilean.requests, "get", _boom)
    with pytest.raises(requests.RequestException):
        zilean.fetch_streams("tt1", raise_on_error=True)


def _native_mode(monkeypatch):
    monkeypatch.setattr(zilean._settings, "get",
                        lambda k, d=None: "native" if k == "ZILEAN_MODE" else d)


def test_native_failure_returns_empty_by_default(monkeypatch):
    import tmdb
    _native_mode(monkeypatch)

    def _boom(*a, **k):
        raise RuntimeError("index db down")

    monkeypatch.setattr(tmdb, "display_title", _boom)
    assert zilean.fetch_streams("tt1") == []


def test_native_failure_propagates_when_raise_on_error(monkeypatch):
    import tmdb
    _native_mode(monkeypatch)

    def _boom(*a, **k):
        raise RuntimeError("index db down")

    monkeypatch.setattr(tmdb, "display_title", _boom)
    with pytest.raises(RuntimeError):
        zilean.fetch_streams("tt1", raise_on_error=True)


def test_native_unresolved_title_is_not_an_outage(monkeypatch):
    # A per-title condition (nothing to resolve), not a scraper outage: must
    # not raise even when raise_on_error is set.
    import tmdb
    _native_mode(monkeypatch)
    monkeypatch.setattr(tmdb, "display_title", lambda *a, **k: None)
    assert zilean.fetch_streams("tt1", raise_on_error=True) == []
