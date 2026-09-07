"""Per-title actions behind the Library drawer. Thin wrappers over existing
helpers; each returns {ok, message} and never raises."""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db
import library_actions as act

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
def spawned(monkeypatch):
    calls = []
    monkeypatch.setattr(act, "_spawn", lambda target, name: calls.append((target, name)))
    return calls


def test_mirror_and_unmirror_go_through_arr_sync(monkeypatch):
    import arr_sync
    rid = db.insert_request("Heat", "tt1", "movie")
    seen = []
    monkeypatch.setattr(arr_sync, "mirror_add", lambda imdb, mt, tmdb_id=None, title="": seen.append(("add", imdb, mt, title)) or True)
    monkeypatch.setattr(arr_sync, "mirror_remove", lambda imdb, mt, tmdb_id=None: seen.append(("remove", imdb, mt)) or True)
    assert act.mirror("tt1")["ok"] is True
    assert act.unmirror("tt1")["ok"] is True
    assert seen == [("add", "tt1", "movie", "Heat"), ("remove", "tt1", "movie")]
    assert act.mirror("tt404") == {"ok": False, "message": "unknown title"}


def test_drop_retry_and_retry_now(spawned):
    rid = db.insert_request("Tenet", "tt6", "movie")
    db.update_request(rid, "failed", error="x")
    db.enqueue_retry("tt6", "Tenet", "movie", None, attempt=2, delay_seconds=3600)
    assert act.drop_retry("tt6")["ok"] is True and db.get_retry_by_imdb("tt6") is None
    assert act.drop_retry("tt6")["ok"] is False
    db.enqueue_retry("tt6", "Tenet", "movie", None, attempt=2, delay_seconds=3600)
    out = act.retry_now("tt6")
    assert out["ok"] is True and db.get_retry_by_imdb("tt6") is None
    assert db.get_request_by_imdb("tt6")["status"] == "pending"
    assert spawned and spawned[0][1] == "retry-tt6"


def test_series_actions_spawn_the_monitor(spawned):
    db.insert_request("Loki", "tt4", "series")
    db.upsert_monitored_series("tt4", 100, "Loki", [1])
    assert act.recheck_series("tt4")["ok"] is True and spawned[-1][1] == "recheck-tt4"
    assert act.retry_episode("tt4", 1, 3)["ok"] is True and spawned[-1][1] == "episode-tt4-S01E03"
    assert act.recheck_series("tt404")["ok"] is False


def test_blacklist_playability_and_override():
    db.insert_request("Heat", "tt1", "movie")
    assert act.blacklist("a" * 40)["ok"] is True and ("a" * 40) in db.get_blacklisted_hashes()
    assert act.unblacklist("a" * 40)["ok"] is True and ("a" * 40) not in db.get_blacklisted_hashes()
    assert act.blacklist("short") == {"ok": False, "message": "not a valid info hash"}
    db.update_playability_fail("tt1", "x")
    assert act.reset_playability("tt1") == {"ok": True, "message": "1 record(s) reset"}
    assert act.save_override("tt1", {"quality_preference": "1080p", "allow_4k": False, "prefer_hevc": True, "notes": "n"})["ok"]
    assert db.get_show_override("tt1")["prefer_hevc"] == 1
    assert act.clear_override("tt1")["ok"] is True and db.get_show_override("tt1") is None


def test_the_routes_exist_and_delegate():
    src = _src("app.py")
    for route in ('@app.post("/ui/api/library/<imdb_id>/mirror")', '@app.post("/ui/api/library/<imdb_id>/unmirror")',
                  '@app.post("/ui/api/library/<imdb_id>/drop-retry")', '@app.post("/ui/api/library/<imdb_id>/retry-now")',
                  '@app.post("/ui/api/library/<imdb_id>/recheck-series")',
                  '@app.post("/ui/api/library/<imdb_id>/episodes/<int:season>/<int:episode>/retry")',
                  '@app.post("/ui/api/library/hash/<info_hash>/blacklist")', '@app.post("/ui/api/library/hash/<info_hash>/unblacklist")',
                  '@app.post("/ui/api/library/<imdb_id>/playability/reset")',
                  '@app.route("/ui/api/library/<imdb_id>/override", methods=["POST", "DELETE"])'):
        assert route in src, route
        body = src.split(route, 1)[1].split("\n\n\n", 1)[0]
        assert "_lib_action(" in body, route
    helper = src.split("def _lib_action", 1)[1][:400]
    assert "auth.is_admin()" in helper and "library_actions" in helper
