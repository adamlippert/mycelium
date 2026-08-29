"""A scraper outage must never be read as 'this title no longer exists'.

fetch_candidates swallows every scraper exception, so an empty list means both
"searched and found nothing" and "could not search". The two call sites that
destroy or de-prioritise something on an empty result ask for the distinction
via raise_if_all_failed; these tests pin both halves of it.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import scrapers


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
        assert seen["raise_if_all_failed"] is True
        seen.clear()
        cleanup._fetch_candidates("tt1", "X", "series")
        assert seen["raise_if_all_failed"] is True
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
