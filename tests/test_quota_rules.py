"""quota.allows: the one rule behind request quotas, and the routes that
apply it (checked on source text; tests never import app.py)."""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db
import quota

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


def _user(name, role="user", cap=0, auto=False):
    uid = db.create_user(name, "scrypt$x$y", role=role, quota_monthly=cap, auto_approve=auto)
    return db.get_user(uid)


def test_unlimited_and_admin_users_are_always_allowed():
    ok, info = quota.allows(_user("free"))
    assert ok and info["unlimited"] is True
    root = _user("root", role="admin", cap=1)
    db.create_user_request(root["id"], "tt1", 1, "movie", "A")
    db.create_user_request(root["id"], "tt2", 2, "movie", "B")
    assert quota.allows(root)[0] is True
    assert quota.allows(None)[0] is True


def test_a_capped_user_is_refused_at_the_cap_with_the_numbers():
    u = _user("adam", cap=2)
    assert quota.allows(u)[0] is True
    db.create_user_request(u["id"], "tt1", 1, "movie", "A")
    ok, info = quota.allows(u)
    assert ok is True and info["used"] == 1 and info["limit"] == 2
    db.create_user_request(u["id"], "tt2", 2, "movie", "B")
    ok, info = quota.allows(u)
    assert ok is False and info["reason"] == "quota reached" and info["used"] == 2
    assert info["resets_at"].endswith("-01T00:00:00Z")


def test_the_add_route_refuses_with_409_and_downgrades_auto_approve():
    body = _src("app.py").split('@app.post("/ui/api/discover/add")', 1)[1].split("\n\n\n", 1)[0]
    assert "quota.allows(user_rec)" in body
    assert "409" in body and '"quota reached"' in body
    assert "auto-approve paused: monthly quota reached" in body
    assert body.index("quota.allows(user_rec)") < body.index("db.create_user_request(")


def test_the_pause_note_is_carried_from_creation_not_a_later_review():
    u = _user("adam")
    rid = db.create_user_request(u["id"], "tt1", 1, "movie", "A",
                                  note="auto-approve paused: monthly quota reached")
    row = db.get_user_request(rid)
    assert row["note"] == "auto-approve paused: monthly quota reached"
    assert row["reviewed_at"] is None and row["reviewed_by"] is None


def test_a_denied_request_does_not_spend_quota():
    u = _user("adam", cap=2)
    root = _user("root", role="admin")
    r1 = db.create_user_request(u["id"], "tt1", 1, "movie", "A")
    db.create_user_request(u["id"], "tt2", 2, "movie", "B")
    ok, info = quota.allows(u)
    assert ok is False and info["used"] == 2
    db.update_user_request_status(r1, "denied", reviewed_by=root["id"], note="no")
    ok, info = quota.allows(u)
    assert ok is True and info["used"] == 1


def test_reopen_helper_only_reopens_denied_rows():
    u = _user("adam")
    root = _user("root", role="admin")
    rid = db.create_user_request(u["id"], "tt1", 1, "movie", "A")
    assert db.reopen_user_request(rid) is False, "pending stays pending"
    db.update_user_request_status(rid, "denied", reviewed_by=root["id"], note="no")
    assert db.reopen_user_request(rid) is True
    row = db.get_user_request(rid)
    assert row["status"] == "pending" and row["reviewed_by"] is None and row["reviewed_at"] is None and row["note"] is None
    assert db.reopen_user_request(999) is False


def test_reopen_and_quota_routes_exist_and_the_orphan_is_gone():
    src = _src("app.py")
    for route in ('@app.post("/ui/api/user-requests/<int:req_id>/reopen")', '@app.get("/ui/api/admin/quotas")'):
        assert route in src, route
        body = src.split(route, 1)[1].split("\n\n\n", 1)[0]
        assert "auth.is_admin()" in body
    assert '"/ui/api/requests/all"' not in src
    assert "requestsAll" not in _src("frontend/src/api.ts")
