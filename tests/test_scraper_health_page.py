"""The admin Scrapers page must show every scraper's status, not just the
ones currently taking traffic.

It used scrapers._active() as its data source - a traffic-routing filter -
which hid exactly the scrapers whose status matters: disabled ones showed
nothing at all, and a scraper whose health probe failed vanished from the
page instead of showing "down". And because latency samples live in process
memory, every restart showed "unknown" until the first search; the live
health probe now stands in for that.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import scrapers
import scraper_metrics


@pytest.fixture(autouse=True)
def _fresh_metrics():
    scraper_metrics.reset()
    yield
    scraper_metrics.reset()


def _settings_returning(values, monkeypatch):
    monkeypatch.setattr(scrapers._settings, "get",
                        lambda k, d=None: values.get(k, d))


def test_disabled_scrapers_are_listed_as_disabled(monkeypatch):
    _settings_returning({}, monkeypatch)  # zilean and debridio off
    monkeypatch.setattr(scrapers.health_cache, "is_up", lambda name: True)

    rows = {r["name"]: r for r in scrapers.health_rows()}

    assert rows["zilean"]["state"] == "disabled"
    assert rows["debridio"]["state"] == "disabled"
    assert rows["torrentio"]["state"] == "ok"


def test_a_down_scraper_stays_on_the_page(monkeypatch):
    """The whole point of a status page: the unhealthy scraper must show as
    down, not vanish."""
    _settings_returning({"DEBRIDIO_ENABLED": True}, monkeypatch)
    monkeypatch.setattr(scrapers.health_cache, "is_up",
                        lambda name: name != "debridio")

    rows = {r["name"]: r for r in scrapers.health_rows()}

    assert rows["debridio"]["state"] == "down"
    assert rows["torrentio"]["state"] == "ok"


def test_probe_stands_in_only_until_real_samples_exist(monkeypatch):
    """Measured latency beats the probe once a search has actually run."""
    _settings_returning({}, monkeypatch)
    monkeypatch.setattr(scrapers.health_cache, "is_up", lambda name: True)
    scraper_metrics.record("torrentio", 250, True)

    rows = {r["name"]: r for r in scrapers.health_rows()}

    assert rows["torrentio"]["state"] == "ok"
    assert rows["torrentio"]["samples"] == 1
    assert rows["torrentio"]["latency_ms"] == 250


def test_every_scraper_appears_exactly_once(monkeypatch):
    _settings_returning({"ZILEAN_ENABLED": True, "DEBRIDIO_ENABLED": True}, monkeypatch)
    monkeypatch.setattr(scrapers.health_cache, "is_up", lambda name: True)

    names = [r["name"] for r in scrapers.health_rows()]

    assert sorted(names) == ["debridio", "torrentio", "zilean"]


def test_the_endpoint_uses_health_rows_not_active():
    with open(os.path.join(os.path.dirname(__file__), "..", "app.py")) as f:
        src = f.read()
    import re
    m = re.search(r"def ui_api_scraper_health\(.*?\n(.*?)\n@app\.", src, re.S)
    assert m
    assert "health_rows()" in m.group(1)
    assert "_active()" not in m.group(1)
