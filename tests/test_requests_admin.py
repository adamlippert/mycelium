"""requests_admin: the read model behind the admin Requests tab."""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db
import requests_admin as ra

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


@pytest.fixture
def seeded():
    """Three users, every status, movie and series. Returns ids by name."""
    adam = db.create_user("adam", "scrypt$x$y", role="user", quota_monthly=2)
    bea = db.create_user("bea", "scrypt$x$y", role="user", quota_monthly=0)
    root = db.create_user("root", "scrypt$x$y", role="admin")
    r1 = db.create_user_request(adam, "tt1", 1, "movie", "Heat")                      # pending
    r2 = db.create_user_request(adam, "tt2", 2, "series", "Loki")                     # approved, in library
    r3 = db.create_user_request(bea, "tt3", 3, "movie", "Alien")                      # denied with note
    r4 = db.create_user_request(bea, "tt4", 4, "movie", "Dune")                       # pending
    db.update_user_request_status(r2, "approved", reviewed_by=root)
    db.update_user_request_status(r3, "denied", reviewed_by=root, note="too big")
    db.insert_request("Loki", "tt2", "series")
    db.update_request(db.get_request_by_imdb("tt2")["id"], "success")
    with db._connect() as conn:
        conn.execute("UPDATE user_requests SET created_at = datetime('now', '-40 days') WHERE id = ?", (r3,))
        conn.execute("UPDATE user_requests SET created_at = datetime('now', '-2 days') WHERE id = ?", (r1,))
        conn.commit()
    return {"adam": adam, "bea": bea, "root": root, "r1": r1, "r2": r2, "r3": r3, "r4": r4}


def _ids(rows):
    return [r["id"] for r in rows]


def test_default_listing_is_every_request_newest_first_with_joined_columns(seeded):
    rows, total = ra.list_requests({})
    assert total == 4 and _ids(rows) == [seeded["r4"], seeded["r2"], seeded["r1"], seeded["r3"]]
    by = {r["id"]: r for r in rows}
    assert by[seeded["r2"]]["username"] == "adam" and by[seeded["r2"]]["reviewer"] == "root"
    assert by[seeded["r2"]]["library_status"] == "success"
    assert by[seeded["r1"]]["reviewer"] is None and by[seeded["r1"]]["library_status"] is None
    assert by[seeded["r3"]]["note"] == "too big"
    assert set(rows[0]) == {"id", "imdb_id", "tmdb_id", "title", "media_type", "seasons", "status", "note",
                            "created_at", "reviewed_at", "user_id", "username", "reviewer", "library_status"}


@pytest.mark.parametrize("view,key", [("pending", ["r1", "r4"]), ("approved", ["r2"]), ("denied", ["r3"]),
                                      ("all", ["r1", "r2", "r3", "r4"])])
def test_views_select_exactly_their_rows(seeded, view, key):
    rows, total = ra.list_requests({"view": view})
    assert set(_ids(rows)) == {seeded[k] for k in key} and total == len(key)


def test_pending_view_sorts_oldest_first(seeded):
    rows, _ = ra.list_requests({"view": "pending"})
    assert _ids(rows) == [seeded["r1"], seeded["r4"]]


def test_view_counts_match(seeded):
    assert ra.view_counts() == {"pending": 2, "approved": 1, "denied": 1, "all": 4}


@pytest.mark.parametrize("filters,key", [
    ({"user": "adam"}, ["r1", "r2"]),
    ({"type": "series"}, ["r2"]),
    ({"type": "movie", "view": "pending"}, ["r1", "r4"]),
    ({"added": "7d"}, ["r1", "r2", "r4"]),
    ({"added": "24h"}, ["r2", "r4"]),
    ({"q": "ali"}, ["r3"]),
    ({"q": "tt4"}, ["r4"]),
])
def test_filters(seeded, filters, key):
    if "user" in filters:
        filters = {**filters, "user": str(seeded[filters["user"]])}
    rows, _ = ra.list_requests(filters)
    assert set(_ids(rows)) == {seeded[k] for k in key}


def test_search_escapes_like_wildcards(seeded):
    db.create_user_request(seeded["bea"], "tt5", 5, "movie", "Silo_S1")
    db.create_user_request(seeded["bea"], "tt6", 6, "movie", "SiloXS1")
    rows, _ = ra.list_requests({"q": "Silo_"})
    assert [r["title"] for r in rows] == ["Silo_S1"]


def test_sorting_and_paging(seeded):
    rows, total = ra.list_requests({"sort": "title", "order": "asc", "per_page": 2, "page": 2})
    assert total == 4 and [r["title"] for r in rows] == ["Heat", "Loki"], "Alien, Dune | Heat, Loki"
    rows, _ = ra.list_requests({"sort": "user", "order": "desc"})
    assert [r["username"] for r in rows][:2] == ["bea", "bea"]
    rows, _ = ra.list_requests({"sort": "reviewed", "order": "desc"})
    assert rows[0]["id"] in (seeded["r2"], seeded["r3"]) and rows[-1]["reviewed_at"] is None
    rows, _ = ra.list_requests({"per_page": 1000})
    assert len(rows) == 4


def test_unknown_values_are_ignored_not_errors(seeded):
    rows, total = ra.list_requests({"view": "bogus", "sort": "DROP", "user": "x", "page": "y", "type": "cartoon"})
    assert total == 0
    rows, total = ra.list_requests({"sort": "DROP", "user": "x", "page": "y", "type": "cartoon"})
    assert total == 4


def test_the_index_exists():
    with db._connect() as conn:
        names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_user_requests_status_created" in names


def test_the_routes_exist_and_are_admin_only():
    src = _src("app.py")
    for route in ('@app.get("/ui/api/admin/requests")', '@app.get("/ui/api/admin/requests/views")'):
        assert route in src, route
        body = src.split(route, 1)[1].split("\n\n\n", 1)[0]
        assert "auth.is_admin()" in body and "requests_admin" in body
