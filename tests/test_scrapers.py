import os
import sys
import time

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import scrapers
import streams as streams_mod


def _s(h, source, quality="1080p"):
    return streams_mod.Stream(name=source, title=f"T.{quality}", info_hash=h,
                              quality=quality, seeders=10, size_gb=5.0,
                              is_season_pack=False, source=source)


@pytest.fixture(autouse=True)
def _all_enabled_and_healthy(monkeypatch):
    monkeypatch.setattr(scrapers._settings, "get", lambda k, d=None: True)
    monkeypatch.setattr(scrapers.health_cache, "is_up", lambda name: True)
    monkeypatch.setattr(scrapers, "rank_streams",
                        lambda s, prefer_season_pack=False, override=None: list(s))


def _wire(monkeypatch, deb=(), zil=(), tor=()):
    monkeypatch.setattr(scrapers.debridio, "fetch", lambda *a, **k: list(deb))
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", lambda *a, **k: list(zil))
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams", lambda *a, **k: list(tor))


def test_debridio_wins_a_duplicate_hash(monkeypatch):
    h = "a" * 40
    _wire(monkeypatch, deb=[_s(h, "debridio")], tor=[_s(h, "torrentio")])
    out = scrapers.fetch_candidates("movie", "tt1")
    assert len(out) == 1
    assert out[0].source == "debridio"


def test_also_seen_in_records_the_other_sources_in_priority_order(monkeypatch):
    h = "a" * 40
    _wire(monkeypatch, deb=[_s(h, "debridio")], zil=[_s(h, "zilean")],
          tor=[_s(h, "torrentio")])
    out = scrapers.fetch_candidates("movie", "tt1")
    assert out[0].also_seen_in == ("zilean", "torrentio")


def test_unique_result_has_empty_also_seen_in(monkeypatch):
    _wire(monkeypatch, deb=[_s("a" * 40, "debridio")], tor=[_s("b" * 40, "torrentio")])
    out = scrapers.fetch_candidates("movie", "tt1")
    assert all(s.also_seen_in == () for s in out)


def test_all_sources_are_merged(monkeypatch):
    _wire(monkeypatch, deb=[_s("a" * 40, "debridio")], zil=[_s("b" * 40, "zilean")],
          tor=[_s("c" * 40, "torrentio")])
    assert len(scrapers.fetch_candidates("movie", "tt1")) == 3


def test_a_failing_scraper_does_not_fail_the_call(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("debridio exploded")

    monkeypatch.setattr(scrapers.debridio, "fetch", _boom)
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", lambda *a, **k: [])
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams",
                        lambda *a, **k: [_s("c" * 40, "torrentio")])
    out = scrapers.fetch_candidates("movie", "tt1")
    assert [s.source for s in out] == ["torrentio"]


def test_disabled_scraper_is_not_called(monkeypatch):
    monkeypatch.setattr(scrapers._settings, "get",
                        lambda k, d=None: k != "DEBRIDIO_ENABLED")

    def _boom(*a, **k):
        raise AssertionError("disabled scraper must not be called")

    monkeypatch.setattr(scrapers.debridio, "fetch", _boom)
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", lambda *a, **k: [])
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams", lambda *a, **k: [])
    assert scrapers.fetch_candidates("movie", "tt1") == []


def test_unhealthy_scraper_is_skipped(monkeypatch):
    monkeypatch.setattr(scrapers.health_cache, "is_up", lambda name: name != "debridio")

    def _boom(*a, **k):
        raise AssertionError("unhealthy scraper must not be called")

    monkeypatch.setattr(scrapers.debridio, "fetch", _boom)
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", lambda *a, **k: [])
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams", lambda *a, **k: [])
    assert scrapers.fetch_candidates("movie", "tt1") == []


def test_merge_order_is_priority_not_completion_order(monkeypatch):
    h = "a" * 40

    def _slow_debridio(*a, **k):
        time.sleep(0.15)
        return [_s(h, "debridio")]

    monkeypatch.setattr(scrapers.debridio, "fetch", _slow_debridio)
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", lambda *a, **k: [])
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams", lambda *a, **k: [_s(h, "torrentio")])
    out = scrapers.fetch_candidates("movie", "tt1")
    assert out[0].source == "debridio"
    assert out[0].also_seen_in == ("torrentio",)


def test_zilean_receives_no_media_type_argument(monkeypatch):
    seen = {}

    def _zilean(imdb_id, season=None, episode=None):
        seen["args"] = (imdb_id, season, episode)
        return []

    monkeypatch.setattr(scrapers.debridio, "fetch", lambda *a, **k: [])
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", _zilean)
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams", lambda *a, **k: [])
    scrapers.fetch_candidates("series", "tt9", season=2, episode=3)
    assert seen["args"] == ("tt9", 2, 3)


def test_empty_everywhere_returns_empty(monkeypatch):
    _wire(monkeypatch)
    assert scrapers.fetch_candidates("movie", "tt1") == []
