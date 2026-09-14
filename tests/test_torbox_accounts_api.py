"""torbox_accounts_api: admin CRUD over the TorBox account pool, and the
five routes behind /ui/api/torbox-accounts in app.py."""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db
import settings
import torbox_pool

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
    monkeypatch.setenv("TORBOX_API_KEY", "k1")
    _drop_cached_conn()
    db.init()
    settings.set("TORBOX_API_KEY", "k1")
    torbox_pool.invalidate()
    torbox_pool._health.clear()
    yield
    _drop_cached_conn()


def _item(token, account_id, torbox_id=5):
    with db._connect() as conn:
        conn.execute("INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, torbox_id, torbox_account) "
                     "VALUES (?, 'h', 'm', ?, 'movie', ?, ?)", (token, token, torbox_id, account_id))
        conn.commit()


def test_routes_exist_and_are_admin_only():
    src = _src("app.py")
    for route in ('@app.get("/ui/api/torbox-accounts")', '@app.post("/ui/api/torbox-accounts")',
                  '@app.post("/ui/api/torbox-accounts/<int:account_id>")',
                  '@app.delete("/ui/api/torbox-accounts/<int:account_id>")',
                  '@app.post("/ui/api/torbox-accounts/<int:account_id>/test")'):
        assert route in src
        body = src.split(route)[1].split("\n@app.")[0]
        assert "auth.is_admin()" in body and "torbox_accounts_api." in body


def test_list_hides_keys_and_carries_items_and_health():
    import torbox_accounts_api as api
    db.insert_torbox_account("second", "k2-secret-tail")
    _item("a", 2)
    out = api.list_accounts()
    assert [a["label"] for a in out] == ["main", "second"]
    assert out[1]["key_hint"] == "tail" and out[1]["items"] == 1 and "api_key" not in out[1]
    assert set(out[0]["health"]) == {"rate_limited_until", "auth_failed_at", "budget_left"}


def test_add_update_delete_rules():
    import torbox_accounts_api as api
    assert api.add("", "k")["ok"] is False and api.add("x", "")["ok"] is False
    r = api.add("second", "k2"); assert r["ok"] and r["id"] == 2
    assert api.add("second", "k3")["ok"] is False, "labels are unique"
    assert api.update(2, enabled=False)["ok"] and db.get_torbox_account(2)["enabled"] == 0
    assert api.update(9, label="x")["ok"] is False
    _item("a", 2)
    r = api.delete(2)
    assert r["ok"] is False and "1 title" in r["message"]
    db.set_virtual_torbox("a", None, None)
    assert api.delete(2)["ok"] and db.get_torbox_account(2) is None
    assert api.delete(1)["ok"] is False


def test_add_narrows_the_exception_catch_to_integrity_error(monkeypatch):
    import torbox_accounts_api as api

    def _boom(label, api_key):
        raise RuntimeError("disk full")

    monkeypatch.setattr(db, "insert_torbox_account", _boom)
    with pytest.raises(RuntimeError):
        api.add("x", "k")

    monkeypatch.undo()
    # the pre-check path: a label already in the table is refused before any insert
    r = api.add("main", "k2")
    assert r["ok"] is False and "main" in r["message"]

    # the pre-check passes (accounts() faked empty) but the real table still
    # has the label, so the insert itself raises sqlite3.IntegrityError
    monkeypatch.setattr(torbox_pool, "accounts", lambda enabled_only=True: [])
    r = api.add("main", "k3")
    assert r["ok"] is False and "main" in r["message"]


def test_test_runs_the_torbox_tester_with_that_accounts_key(monkeypatch):
    import torbox_accounts_api as api
    import service_tests
    seen = {}
    monkeypatch.setattr(service_tests, "run", lambda kind, values: (seen.update(values), {"ok": True, "message": "ok"})[1])
    db.insert_torbox_account("second", "k2")
    assert api.test(2)["ok"] is True and seen["TORBOX_API_KEY"] == "k2"
    assert api.test(9)["ok"] is False
