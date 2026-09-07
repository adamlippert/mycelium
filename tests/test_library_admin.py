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
