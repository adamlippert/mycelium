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
    rows, total, _ = ra.list_requests({})
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
    rows, total, _ = ra.list_requests({"view": view})
    assert set(_ids(rows)) == {seeded[k] for k in key} and total == len(key)


def test_pending_view_sorts_oldest_first(seeded):
    rows, _, _ = ra.list_requests({"view": "pending"})
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
    rows, _, _ = ra.list_requests(filters)
    assert set(_ids(rows)) == {seeded[k] for k in key}


def test_search_escapes_like_wildcards(seeded):
    db.create_user_request(seeded["bea"], "tt5", 5, "movie", "Silo_S1")
    db.create_user_request(seeded["bea"], "tt6", 6, "movie", "SiloXS1")
    rows, _, _ = ra.list_requests({"q": "Silo_"})
    assert [r["title"] for r in rows] == ["Silo_S1"]


def test_sorting_and_paging(seeded):
    rows, total, _ = ra.list_requests({"sort": "title", "order": "asc", "per_page": 2, "page": 2})
    assert total == 4 and [r["title"] for r in rows] == ["Heat", "Loki"], "Alien, Dune | Heat, Loki"
    rows, _, _ = ra.list_requests({"sort": "user", "order": "desc"})
    assert [r["username"] for r in rows][:2] == ["bea", "bea"]
    rows, _, _ = ra.list_requests({"sort": "reviewed", "order": "desc"})
    assert rows[0]["id"] in (seeded["r2"], seeded["r3"]) and rows[-1]["reviewed_at"] is None
    rows, _, _ = ra.list_requests({"per_page": 1000})
    assert len(rows) == 4


def test_unknown_values_are_ignored_not_errors(seeded):
    rows, total, _ = ra.list_requests({"view": "bogus", "sort": "DROP", "user": "x", "page": "y", "type": "cartoon"})
    assert total == 0
    rows, total, _ = ra.list_requests({"sort": "DROP", "user": "x", "page": "y", "type": "cartoon"})
    assert total == 4


def test_page_past_the_end_clamps_to_the_last_page():
    """A page number past the end of the result set must serve the last
    real page rather than an empty one, and say so in the returned page."""
    z = db.create_user("zed", "scrypt$x$y", role="user")
    db.create_user_request(z, "ttp1", 1, "movie", "A")
    db.create_user_request(z, "ttp2", 2, "movie", "B")
    db.create_user_request(z, "ttp3", 3, "movie", "C")
    rows, total, page = ra.list_requests({"per_page": 2, "page": 99, "sort": "title", "order": "asc"})
    assert total == 3 and page == 2
    assert [r["title"] for r in rows] == ["C"]


def test_page_clamps_to_1_when_the_filtered_set_is_empty():
    rows, total, page = ra.list_requests({"q": "nonexistent-title-xyz"})
    assert total == 0 and rows == [] and page == 1


def test_the_status_index_exists():
    with db._connect() as conn:
        names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_user_requests_status" in names


def test_the_routes_exist_and_are_admin_only():
    src = _src("app.py")
    for route in ('@app.get("/ui/api/admin/requests")', '@app.get("/ui/api/admin/requests/views")'):
        assert route in src, route
        body = src.split(route, 1)[1].split("\n\n\n", 1)[0]
        assert "auth.is_admin()" in body and "requests_admin" in body


def test_quota_rows_cover_every_non_admin_user_including_disabled(seeded):
    db.update_user(seeded["adam"], auto_approve=1)
    db.create_user_request(seeded["adam"], "tt9", 9, "movie", "Third")
    carl = db.create_user("carl", "scrypt$x$y", role="user", quota_monthly=5)
    db.update_user(carl, enabled=0)
    rows = ra.quota_rows()
    assert [r["username"] for r in rows] == ["adam", "bea", "carl"], "admins are left out, disabled users are not"
    adam = rows[0]
    # r1 sits two days back; on the 1st or 2nd of a month it falls into last month, so allow 2 or 3
    assert adam["used"] in (2, 3) and adam["limit"] == 2 and adam["remaining"] == 0
    assert adam["unlimited"] is False and adam["auto_approve"] is True and adam["paused"] is True
    assert adam["enabled"] is True
    bea = rows[1]
    assert bea["unlimited"] is True and bea["remaining"] is None and bea["paused"] is False
    assert bea["enabled"] is True
    carl_row = rows[2]
    assert carl_row["enabled"] is False and carl_row["used"] == 0 and carl_row["limit"] == 5
    assert adam["resets_at"].endswith("-01T00:00:00Z")


def test_the_old_requests_panels_are_gone():
    src = _src("frontend/src/pages/admin/Requests.tsx")
    assert "PendingApprovalsPanel" not in src and "AllRequestsPanel" not in src
    assert "RowActions" in src and "QuotasCard" in src and "AutoApproveCard" in src
