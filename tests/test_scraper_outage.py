"""A scraper outage must never be read as 'this title no longer exists'.

fetch_candidates swallows every scraper exception, so an empty list means both
"searched and found nothing" and "could not search". The two call sites that
destroy or de-prioritise something on an empty result ask for the distinction
via raise_if_inconclusive; these tests pin both halves of it.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import scrapers
import streams as streams_mod


# ── cleanup._repair_strm ───────────────────────────────────────────────────────

@pytest.fixture
def broken_strm(tmp_path, monkeypatch):
    """A .strm whose torrent is gone from the TorBox mylist, plus its .nfo."""
    import cleanup

    folder = tmp_path / "Some Movie (2020)"
    folder.mkdir()
    path = folder / "Some Movie (2020).strm"
    path.write_text("https://api.torbox.app/v1/api/torrents/requestdl"
                    "?torrent_id=123&file_id=4", encoding="utf-8")
    nfo = path.with_suffix(".nfo")
    nfo.write_text("<movie/>", encoding="utf-8")

    monkeypatch.setattr(cleanup.tmdb, "search_movie", lambda *a, **k: "tt1")
    monkeypatch.setattr(cleanup.tmdb, "search_tv", lambda *a, **k: "tt1")
    return path, nfo


def _record_db(monkeypatch):
    import cleanup
    calls = {"repair": [], "deleted": []}
    monkeypatch.setattr(cleanup.db, "insert_repair_item",
                        lambda *a, **k: calls["repair"].append(a))
    monkeypatch.setattr(cleanup.db, "delete_virtual_item_by_strm_path",
                        lambda p: calls["deleted"].append(p))
    return calls


def test_outage_keeps_the_strm_the_nfo_the_row_and_the_retry(broken_strm, monkeypatch):
    import cleanup
    path, nfo = broken_strm
    calls = _record_db(monkeypatch)

    def _down(*a, **k):
        raise scrapers.ScrapersUnavailable("all 3 active scraper(s) failed")

    monkeypatch.setattr(cleanup.scrapers, "fetch_candidates", _down)

    result = cleanup._repair_strm(path, run_id=1, mylist=[])

    assert result == "failed"          # not "unfixable": no 24h retry block
    assert path.exists()
    assert nfo.exists()
    assert calls["deleted"] == []
    assert calls["repair"] == []


def test_a_real_miss_still_deletes(broken_strm, monkeypatch):
    # The mirror image: scrapers ran fine and this title really is gone, so
    # the destructive path must be untouched by the fix above.
    import cleanup
    path, nfo = broken_strm
    calls = _record_db(monkeypatch)
    monkeypatch.setattr(cleanup.scrapers, "fetch_candidates", lambda *a, **k: [])

    assert cleanup._repair_strm(path, run_id=1, mylist=[]) == "unfixable"
    assert not path.exists()
    assert not nfo.exists()
    assert calls["deleted"] == [str(path)]


def test_cleanup_asks_for_the_distinction():
    import cleanup
    seen = {}
    real = scrapers.fetch_candidates
    try:
        scrapers.fetch_candidates = lambda *a, **k: seen.update(k) or []
        cleanup._fetch_candidates("tt1", "X", "movie")
        assert seen["raise_if_inconclusive"] is True
        seen.clear()
        cleanup._fetch_candidates("tt1", "X", "series")
        assert seen["raise_if_inconclusive"] is True
    finally:
        scrapers.fetch_candidates = real


# ── catbox._search_best_cached_release ─────────────────────────────────────────

_ITEM = {"imdb_id": "tt1", "media_type": "movie", "title": "X", "token": "tok"}


def test_catbox_outage_returns_the_unavailable_sentinel(monkeypatch):
    # None here would send the caller down the 6-hour backoff, outliving the
    # outage by hours; the sentinel uses the short _FAIL_COOLDOWN_SEC instead.
    import catbox

    def _down(*a, **k):
        raise scrapers.ScrapersUnavailable("no scraper is enabled and healthy")

    monkeypatch.setattr(scrapers, "fetch_candidates", _down)
    assert catbox._search_best_cached_release(dict(_ITEM)) is catbox._SEARCH_UNAVAILABLE


def test_catbox_real_miss_still_returns_none(monkeypatch):
    import catbox
    monkeypatch.setattr(scrapers, "fetch_candidates", lambda *a, **k: [])
    assert catbox._search_best_cached_release(dict(_ITEM)) is None


def test_catbox_unavailable_result_is_not_cached_for_six_hours(monkeypatch):
    # _search_cached_release used to fall through to _SEARCH_MISS_TTL (6h) for
    # the sentinel too, since `result and result is not _SEARCH_UNAVAILABLE`
    # is False for it just like for a real miss. That defeats the sentinel's
    # whole point: a token's retry cooldown is 30s but the title itself
    # wouldn't be re-searched for 6 hours, well past any real outage.
    import catbox

    calls = []

    def _search(item):
        calls.append(1)
        return catbox._SEARCH_UNAVAILABLE

    monkeypatch.setattr(catbox, "_search_best_cached_release", _search)
    catbox._search_cache.clear()
    try:
        item = dict(_ITEM)
        first = catbox._search_cached_release(item)
        second = catbox._search_cached_release(item)
        assert first is catbox._SEARCH_UNAVAILABLE
        assert second is catbox._SEARCH_UNAVAILABLE
        assert len(calls) == 2, "second call must re-search, not read a cached sentinel"
    finally:
        catbox._search_cache.clear()


# ── scrapers.fetch_candidates: the guard itself, with realistic adapters ──────
#
# fetch_candidates only turns "could not search" into ScrapersUnavailable if
# raise_if_inconclusive asks for it, and only if the underlying failure
# actually surfaces as an exception. Of the three real adapters, only
# Torrentio propagates - Debridio and Zilean both document "never raises,
# returns [] on failure". A mock that makes all three raise passes even with
# the old, broken `failed == len(active)` guard and hides that gap entirely.
# These mirror the real adapters' failure shape instead.

@pytest.fixture
def _all_scrapers_enabled_and_healthy(monkeypatch):
    monkeypatch.setattr(scrapers._settings, "get", lambda k, d=None: True)
    monkeypatch.setattr(scrapers.health_cache, "is_up", lambda name: True)
    monkeypatch.setattr(scrapers, "rank_streams",
                        lambda s, prefer_season_pack=False, override=None: list(s))


def test_all_three_failing_at_the_query_layer_raises(monkeypatch, _all_scrapers_enabled_and_healthy):
    # health_cache still says "up" (it probes a different endpoint on a TTL,
    # not the query path) while every scraper actually fails to find anything.
    monkeypatch.setattr(scrapers.debridio, "fetch", lambda *a, **k: [])
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", lambda *a, **k: [])

    def _boom(*a, **k):
        raise RuntimeError("torrentio down")

    monkeypatch.setattr(scrapers.torrentio, "fetch_streams", _boom)

    with pytest.raises(scrapers.ScrapersUnavailable):
        scrapers.fetch_candidates("movie", "tt1", raise_if_inconclusive=True)


def test_one_scraper_fails_another_still_finds_candidates(monkeypatch, _all_scrapers_enabled_and_healthy):
    h = "a" * 40

    def _boom(*a, **k):
        raise RuntimeError("debridio down")

    monkeypatch.setattr(scrapers.debridio, "fetch", _boom)
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", lambda *a, **k: [])
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams",
                        lambda *a, **k: [streams_mod.Stream(
                            name="t", title="T.1080p", info_hash=h, quality="1080p",
                            seeders=1, size_gb=1.0, is_season_pack=False, source="torrentio")])

    out = scrapers.fetch_candidates("movie", "tt1", raise_if_inconclusive=True)
    assert [s.source for s in out] == ["torrentio"]


def test_one_scraper_fails_others_return_empty_raises(monkeypatch, _all_scrapers_enabled_and_healthy):
    def _boom(*a, **k):
        raise RuntimeError("debridio down")

    monkeypatch.setattr(scrapers.debridio, "fetch", _boom)
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", lambda *a, **k: [])
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams", lambda *a, **k: [])

    with pytest.raises(scrapers.ScrapersUnavailable):
        scrapers.fetch_candidates("movie", "tt1", raise_if_inconclusive=True)


def test_all_scrapers_succeed_and_return_empty_is_a_real_miss(monkeypatch, _all_scrapers_enabled_and_healthy):
    monkeypatch.setattr(scrapers.debridio, "fetch", lambda *a, **k: [])
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", lambda *a, **k: [])
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams", lambda *a, **k: [])

    assert scrapers.fetch_candidates("movie", "tt1", raise_if_inconclusive=True) == []
