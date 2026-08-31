"""Tier 2 performance fixes: required for a 100k-item library.

From the 2026-08-31 performance review:
1. stats.get_overview derives its numbers from aggregate SQL instead of four
   full-table loads, and the whole result (including the media-tree walk for
   the strm counts) is cached for 60s so the admin's 30s poll and every
   Library visitor share one computation.
2. virtual_items gets the indexes for the columns it is actually filtered on
   (imdb_id+media_type, info_hash); media_items gets one on media_type.
3. reconcile_wanted_episodes batches its per-episode UPDATEs into a single
   transaction (the connection is in autocommit mode, so each UPDATE used to
   take the writer lock on its own) and both reconcile functions are
   debounced: they run from GET handlers on the busiest pages, at most once
   per window now no matter how many users are navigating.
4. The series-episodes endpoint caches its response for 30s instead of
   walking every show and season folder per request, and a purge invalidates
   the cache. The strm repair job checks tokens against one snapshot query
   instead of one SELECT per file, and its no-strm pass consults a prebuilt
   sibling map instead of re-listing the whole root per broken folder.
"""
import os
import re
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db
import stats

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _drop_cached_conn():
    conn = getattr(db._tls, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        db._tls.conn = None


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    _drop_cached_conn()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    _drop_cached_conn()
    db.init()
    db._reconcile_last.clear()
    stats._overview_cache["data"] = None
    stats._overview_cache["ts"] = 0.0
    yield
    db._reconcile_last.clear()
    stats._overview_cache["data"] = None
    stats._overview_cache["ts"] = 0.0
    _drop_cached_conn()


def _src(relpath):
    with open(os.path.join(_ROOT, relpath), encoding="utf-8") as f:
        return f.read()


def _insert_virtual_item(token, imdb_id, media_type, strm_path):
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO virtual_items "
            "(token, info_hash, magnet, title, imdb_id, media_type, strm_path) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (token, "f" * 40, "magnet:?xt=x", "Title", imdb_id, media_type, strm_path),
        )
        conn.commit()


# -- 2. indexes ---------------------------------------------------------------

def test_the_hot_columns_are_indexed():
    with db._connect() as conn:
        names = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    assert "idx_virtual_items_imdb_media" in names
    assert "idx_virtual_items_info_hash" in names
    assert "idx_media_items_type" in names


# -- 3. reconcile: batched and debounced --------------------------------------

def test_reconcile_episodes_marks_found_from_strm_paths():
    db.upsert_wanted_episode("tt0000001", 1, "Show", 1, 2, air_date=None)
    _insert_virtual_item("a" * 16, "tt0000001", "series",
                         "/media/series/Show/Season 01/Show S01E02.strm")

    assert db.reconcile_wanted_episodes(force=True) == 1
    with db._connect() as conn:
        row = conn.execute(
            "SELECT status FROM wanted_episodes WHERE episode=2").fetchone()
    assert row["status"] == "found"


def test_reconcile_is_debounced_between_calls():
    """GET handlers call this on every page load; only the first call inside
    the window does work."""
    db.upsert_wanted_episode("tt0000001", 1, "Show", 1, 2, air_date=None)
    _insert_virtual_item("a" * 16, "tt0000001", "series",
                         "/media/series/Show/Season 01/Show S01E02.strm")

    assert db.reconcile_wanted_episodes() == 1
    # Same window: the strm for episode 3 appears, but the debounce holds.
    db.upsert_wanted_episode("tt0000001", 1, "Show", 1, 3, air_date=None)
    _insert_virtual_item("b" * 16, "tt0000001", "series",
                         "/media/series/Show/Season 01/Show S01E03.strm")
    assert db.reconcile_wanted_episodes() == 0
    # force bypasses the window (jobs and tests use this).
    assert db.reconcile_wanted_episodes(force=True) == 1


def test_reconcile_movies_is_debounced_too():
    assert db.reconcile_wanted_movies() == 0
    src = _src("db.py")
    m = re.search(r"def reconcile_wanted_movies\(.*?\n(.*?)\ndef ", src, re.S)
    assert m and "_reconcile_due" in m.group(1)


def test_reconcile_episodes_updates_inside_one_transaction():
    """The connection is autocommit; without an explicit transaction every
    UPDATE takes the writer lock and syncs on its own."""
    src = _src("db.py")
    m = re.search(r"def reconcile_wanted_episodes\(.*?\n(.*?)\n\n# ", src, re.S)
    assert m, "reconcile_wanted_episodes not found"
    body = m.group(1)
    assert "BEGIN IMMEDIATE" in body
    assert "executemany" in body


# -- 1. stats overview --------------------------------------------------------

def _seed_stats_data():
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO requests (title, imdb_id, media_type, status, quality) "
            "VALUES ('Won', 'tt0000010', 'movie', 'success', '1080p')")
        conn.execute(
            "INSERT INTO requests (title, imdb_id, media_type, status) "
            "VALUES ('Lost', 'tt0000011', 'movie', 'failed')")
        conn.execute(
            "INSERT INTO monitored_series (imdb_id, title) "
            "VALUES ('tt0000012', 'Show')")
        conn.execute(
            "INSERT INTO media_items (imdb_id, title, media_type, strm_found) "
            "VALUES ('tt0000013', 'Pending Movie', 'movie', 0)")
        conn.commit()
    db.upsert_wanted_episode("tt0000012", 1, "Show", 1, 1, air_date=None)


def test_overview_is_built_from_aggregates(tmp_path, monkeypatch):
    monkeypatch.setattr(stats, "MEDIA_PATH", str(tmp_path))
    movies = tmp_path / "movies" / "Won (2024)"
    movies.mkdir(parents=True)
    (movies / "Won (2024).strm").write_text("/stream/aaaa", encoding="utf-8")
    _seed_stats_data()

    d = stats.get_overview(force=True)

    assert d["library"]["movie_count"] == 1
    assert d["library"]["episode_count"] == 0
    assert d["library"]["series_count"] == 1
    assert d["requests"]["total"] == 2
    assert d["requests"]["succeeded_7d"] == 1
    assert d["requests"]["failed_7d"] == 1
    assert d["requests"]["success_rate_7d"] == 50.0
    assert d["wanted"] == {"active": 1, "found": 0, "give_up": 0}
    assert d["movies_pending"] == 1
    assert d["qualities"] == {"1080p": 1}


def test_overview_no_longer_loads_whole_tables():
    src = _src("stats.py")
    m = re.search(r"def _build_overview\(\).*?(?=\ndef )", src, re.S)
    assert m
    body = m.group(0)
    for banned in ("get_recent", "get_all_monitored_series",
                   "get_all_wanted_episodes", "get_media_items"):
        assert banned not in body, f"_build_overview still calls {banned}"


def test_overview_is_cached_across_pollers(tmp_path, monkeypatch):
    monkeypatch.setattr(stats, "MEDIA_PATH", str(tmp_path))
    calls = {"n": 0}
    real = stats._build_overview

    def counting():
        calls["n"] += 1
        return real()
    monkeypatch.setattr(stats, "_build_overview", counting)

    first = stats.get_overview()
    second = stats.get_overview()

    assert calls["n"] == 1
    assert second is first


def test_overview_force_bypasses_the_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(stats, "MEDIA_PATH", str(tmp_path))
    stats.get_overview()
    _seed_stats_data()

    assert stats.get_overview(force=True)["requests"]["total"] == 2


# -- 4a. series-episodes endpoint cache ---------------------------------------

def test_series_episodes_route_serves_from_the_cache():
    src = _src("app.py")
    m = re.search(
        r'@app\.get\(["\']/ui/api/library/series-episodes["\']\)\s*\n'
        r"def ui_api_library_series_episodes\(\):(.*?)\ndef ", src, re.S)
    assert m, "series-episodes route not found"
    body = m.group(1)
    assert "_series_episodes_cache" in body
    assert "_SERIES_EPISODES_TTL_SEC" in body


def test_purge_invalidates_the_series_episodes_cache():
    """Purge deletes .strm files; a cached tree would keep showing them."""
    src = _src("app.py")
    m = re.search(r"def ui_api_purge_request\(.*?\n(.*?)\n@app\.", src, re.S)
    assert m
    assert "invalidate_series_episodes_cache()" in m.group(1)


# -- 4b. repair job: batched token check, linear sibling scan -----------------

def test_get_all_virtual_item_tokens_returns_the_set():
    _insert_virtual_item("a" * 16, "tt0000001", "movie", "/media/movies/A/A.strm")
    _insert_virtual_item("b" * 16, "tt0000002", "movie", "/media/movies/B/B.strm")

    assert db.get_all_virtual_item_tokens() == {"a" * 16, "b" * 16}


def test_repair_pass2_checks_tokens_against_the_snapshot():
    src = _src("strm_generator.py")
    assert "valid_tokens = db.get_all_virtual_item_tokens()" in src
    # The per-file SELECT survives only as the confirm-on-miss fallback.
    m = re.search(r"token in valid_tokens or db\.get_virtual_item\(token\)", src)
    assert m, "snapshot check with DB fallback not found"


def test_repair_pass1_uses_a_prebuilt_sibling_map():
    src = _src("strm_generator.py")
    assert "strm_norms" in src
    m = re.search(r"for sib in root\.iterdir\(\)", src)
    assert m is None, "pass 1 still re-lists the root per broken folder"
