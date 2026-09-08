"""library_admin: the read model behind the Library tab. One query with
subselects, filters and views resolved in SQL, server-side paging."""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db
import library_admin as la

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _src(name):
    with open(os.path.join(_ROOT, name), encoding="utf-8") as f:
        return f.read()


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
    yield
    _drop_cached_conn()


def _req(title, imdb, media_type="movie", status="success", **cols):
    rid = db.insert_request(title, imdb, media_type)
    db.update_request(rid, status, **cols)
    return rid


@pytest.fixture
def seeded():
    """Six titles covering every view."""
    uid = db.create_user("adam", "scrypt$x$y", role="user")
    _req("Heat", "tt1")                                   # plain success, requested by adam, mirrored, in torbox
    _req("Alien", "tt2", status="failed", error="no release")
    _req("Dune", "tt3", status="wanted")
    _req("Loki", "tt4", media_type="series")               # missing episodes
    _req("Fargo", "tt5", media_type="series", status="pending")
    _req("Tenet", "tt6")                                   # unplayable, in retry queue, unmirrored
    db.create_user_request(uid, "tt1", 949, "movie", "Heat", None)
    db.mark_arr_mirrored("tt1")
    with db._connect() as conn:
        conn.execute("INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, strm_path, imdb_id, torbox_id) "
                     "VALUES ('t1', 'h', 'm', 'Heat', 'movie', '/m/h.strm', 'tt1', 5)")
        conn.execute("UPDATE requests SET created_at = datetime('now', '-40 days') WHERE imdb_id = 'tt2'")
        conn.commit()
    db.upsert_wanted_episode("tt4", 100, "Loki", 2, 3, "2024-01-01")
    db.update_playability_fail("tt6", "cdn 404")
    db.enqueue_retry("tt6", "Tenet", "movie", None, attempt=3, delay_seconds=3600)
    return uid


def _ids(rows):
    return [r["imdb_id"] for r in rows]


def test_default_listing_is_every_title_newest_first_with_the_computed_columns(seeded):
    rows, total = la.list_titles({})
    assert total == 6 and len(rows) == 6
    by = {r["imdb_id"]: r for r in rows}
    assert by["tt1"]["requester"] == "adam" and by["tt1"]["arr_mirrored"] is True and by["tt1"]["in_torbox"] is True
    assert by["tt2"]["requester"] == "auto" and by["tt2"]["error"] == "no release"
    assert by["tt4"]["missing_episodes"] == 1
    assert by["tt6"]["playability"] == {"status": "degraded", "last_fail_reason": "cdn 404"}
    assert by["tt6"]["retry"]["attempt"] == 3 and by["tt6"]["arr_mirrored"] is False
    assert by["tt1"]["playability"] is None and by["tt1"]["retry"] is None


@pytest.mark.parametrize("view,expected", [
    ("attention", {"tt2", "tt6"}),
    ("wanted", {"tt3"}),
    ("queue", {"tt4", "tt5", "tt6"}),
    ("incomplete", {"tt4"}),
    ("unmirrored", {"tt4", "tt6"}),
    ("all", {"tt1", "tt2", "tt3", "tt4", "tt5", "tt6"}),
])
def test_views_select_exactly_their_titles(seeded, view, expected):
    rows, total = la.list_titles({"view": view})
    assert set(_ids(rows)) == expected and total == len(expected)


def test_view_counts_match_the_views(seeded):
    counts = la.view_counts()
    assert counts == {"all": 6, "attention": 2, "wanted": 1, "queue": 3, "incomplete": 1, "unmirrored": 2}


def test_playability_prefers_degraded_across_two_keys_for_the_same_title():
    """A title can carry more than one playability_state row (one per
    episode key, or a bare movie key alongside a stray episode key). The
    derived playability join must group them back to one imdb id and report
    the worst status, not the first row it happens to see."""
    _req("Severance", "tt7", media_type="series")
    db.update_playability_fail("tt7:S01E01", "cdn 404")
    db.update_playability_ok("tt7:S01E02", "torbox")
    rows, _ = la.list_titles({})
    by = {r["imdb_id"]: r for r in rows}
    assert by["tt7"]["playability"] == {"status": "degraded", "last_fail_reason": "cdn 404"}


def test_attention_view_includes_high_retry_attempts_on_their_own():
    """Two success movies with no playability record: only the one with
    three retry attempts belongs in attention, isolating that branch of
    the view's OR from the degraded-playability branch."""
    _req("Movie A", "tta1")
    _req("Movie B", "tta2")
    db.enqueue_retry("tta1", "Movie A", "movie", None, attempt=3, delay_seconds=3600)
    db.enqueue_retry("tta2", "Movie B", "movie", None, attempt=2, delay_seconds=3600)
    rows, total = la.list_titles({"view": "attention"})
    assert _ids(rows) == ["tta1"] and total == 1
    assert la.view_counts()["attention"] == 1


@pytest.mark.parametrize("filters,expected", [
    ({"q": "ali"}, {"tt2"}),
    ({"q": "tt4"}, {"tt4"}),
    ({"status": ["failed", "wanted"]}, {"tt2", "tt3"}),
    ({"type": "series"}, {"tt4", "tt5"}),
    ({"type": "movie", "status": ["success"]}, {"tt1", "tt6"}),
    ({"problem": "unplayable"}, {"tt6"}),
    ({"problem": "missing_episodes"}, {"tt4"}),
    ({"problem": "in_retry_queue"}, {"tt6"}),
    ({"problem": "no_requester"}, {"tt2", "tt3", "tt4", "tt5", "tt6"}),
    ({"problem": "not_mirrored"}, {"tt4", "tt6"}),
    ({"requester": "auto"}, {"tt2", "tt3", "tt4", "tt5", "tt6"}),
    ({"added": "30d"}, {"tt1", "tt3", "tt4", "tt5", "tt6"}),
])
def test_filters(seeded, filters, expected):
    rows, _ = la.list_titles(filters)
    assert set(_ids(rows)) == expected


def test_search_escapes_like_wildcards():
    """A literal `_` or `%` in the search term must not act as a SQL LIKE
    wildcard: `_` matches any single character and `%` matches any run of
    characters unless escaped."""
    _req("Silo_S1", "tts1")
    _req("SiloXS1", "tts2")
    rows, _ = la.list_titles({"q": "Silo_"})
    assert _ids(rows) == ["tts1"]

    _req("Movie 100% Done", "tts3")
    _req("Movie 1000 Done", "tts4")
    rows, _ = la.list_titles({"q": "100%"})
    assert _ids(rows) == ["tts3"]


def test_requester_filter_by_user_id(seeded):
    rows, _ = la.list_titles({"requester": str(seeded)})
    assert _ids(rows) == ["tt1"]


def test_sorting_and_paging(seeded):
    rows, total = la.list_titles({"sort": "title", "order": "asc", "per_page": 2, "page": 2})
    assert total == 6 and _ids(rows) == ["tt5", "tt1"], "Alien, Dune | Fargo, Heat | Loki, Tenet"
    rows, _ = la.list_titles({"sort": "title", "order": "desc", "per_page": 4})
    assert _ids(rows) == ["tt6", "tt4", "tt1", "tt5"]
    rows, _ = la.list_titles({"per_page": 1000})
    assert len(rows) == 6, "per_page is capped, not rejected"


def test_unknown_values_are_ignored_not_errors(seeded):
    rows, total = la.list_titles({"view": "bogus", "sort": "DROP TABLE", "status": ["nope"], "page": "x"})
    assert total == 0 and rows == []
    rows, total = la.list_titles({"view": "bogus"})
    assert total == 0


def test_the_routes_exist_and_are_admin_only():
    src = _src("app.py")
    for route in ('@app.get("/ui/api/library")', '@app.get("/ui/api/library/views")'):
        assert route in src
        body = src.split(route, 1)[1].split("\n\n\n", 1)[0]
        assert "auth.is_admin()" in body and "library_admin" in body
    body = src.split('@app.get("/ui/api/library")', 1)[1].split("\n\n\n", 1)[0]
    assert 'request.args.getlist("status")' in body
    views_body = src.split('@app.get("/ui/api/library/views")', 1)[1].split("\n\n\n", 1)[0]
    assert "mirror_on" in views_body


def test_title_detail_gathers_every_record(seeded):
    db.log_activity("added", "Heat", "movie", True, imdb_id="tt1")
    db.upsert_show_override("tt1", "1080p", True, False, "keep small")
    d = la.title_detail("tt1")
    assert d["request"]["imdb_id"] == "tt1"
    assert d["items"][0]["token"] == "t1" and d["items"][0]["torbox_id"] == 5
    assert d["user_requests"][0]["username"] == "adam"
    assert d["override"]["quality_preference"] == "1080p"
    assert d["hashes"][0]["info_hash"] == "h" and d["hashes"][0]["blacklisted"] is False
    assert d["activity"][0]["event"] == "added"
    assert d["arr"]["mirrored_at"] is not None
    assert d["retry"] is None and d["playability"] == [] and d["episodes"] is None
    assert la.title_detail("tt404") is None


def test_title_detail_reports_mirror_on_from_arr_sync(seeded, monkeypatch):
    import arr_sync
    monkeypatch.setattr(arr_sync, "is_enabled", lambda: True)
    assert la.title_detail("tt1")["mirror_on"] is True
    monkeypatch.setattr(arr_sync, "is_enabled", lambda: False)
    assert la.title_detail("tt1")["mirror_on"] is False


def test_series_detail_summarises_seasons_and_lists_episodes(seeded):
    with db._connect() as conn:
        for ep in (1, 2):
            conn.execute("INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, strm_path, imdb_id, season, episode) "
                         "VALUES (?, 'h', 'm', 'Loki', 'series', ?, 'tt4', 2, ?)", (f"e{ep}", f"/s/e{ep}.strm", ep))
        conn.commit()
    d = la.title_detail("tt4")
    assert d["episodes"] == [{"season": 2, "present": 2, "wanted": 1}]
    eps = la.season_episodes("tt4", 2)
    assert [(e["episode"], e["present"], e["wanted_status"]) for e in eps] == [(1, True, None), (2, True, None), (3, False, "wanted")]
    assert eps[2]["air_date"] == "2024-01-01"


def test_detail_routes_exist():
    src = _src("app.py")
    for route in ('@app.get("/ui/api/library/<imdb_id>")', '@app.get("/ui/api/library/<imdb_id>/season/<int:season>")',
                  '@app.get("/ui/api/library/<imdb_id>/activity")'):
        assert route in src, route
        body = src.split(route, 1)[1].split("\n\n\n", 1)[0]
        assert "auth.is_admin()" in body
