"""db helpers behind the Library admin tab: per-title reads, the activity
log's imdb_id, and the blacklist and playability helpers the drawer uses.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db

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


def _item(imdb, token, info_hash, season=None, episode=None, torbox_id=None):
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, strm_path, imdb_id, season, episode, torbox_id) "
            "VALUES (?, ?, 'magnet:?x', 'T', ?, ?, ?, ?, ?, ?)",
            (token, info_hash, "movie" if season is None else "series", f"/media/{token}.strm", imdb, season, episode, torbox_id))
        conn.commit()


def test_activity_log_has_imdb_id_and_the_title_query_falls_back_to_title_text():
    db.log_activity("added", "Heat", "movie", True, imdb_id="tt0113277")
    db.log_activity("failed", "Heat", "old row without an id", False)
    db.log_activity("added", "Alien", "movie", True, imdb_id="tt0078748")
    rows = db.get_activity_for_title("tt0113277", "Heat")
    assert [r["event"] for r in rows] == ["failed", "added"], "newest first, title fallback included"
    assert rows[1]["imdb_id"] == "tt0113277"
    page2 = db.get_activity_for_title("tt0113277", "Heat", limit=1, before_id=rows[0]["id"])
    assert [r["event"] for r in page2] == ["added"]


def test_every_activity_caller_that_knows_the_title_passes_its_id():
    for name in ("processor.py", "upgrader.py", "disk_sync.py"):
        src = _src(name)
        calls = [line for line in src.splitlines() if "log_activity(" in line]
        assert calls, name
        assert all("imdb_id=" in line for line in calls), f"{name}: {[c.strip() for c in calls if 'imdb_id=' not in c]}"
    purge = _src("app.py").split('db.log_activity("purged"', 1)[1][:200]
    assert "imdb_id=" in purge


def test_retry_row_and_wanted_movie_by_imdb():
    assert db.get_retry_by_imdb("tt1") is None
    db.enqueue_retry("tt1", "T", "movie", None, attempt=2, delay_seconds=60)
    assert db.get_retry_by_imdb("tt1")["attempt"] == 2
    assert db.get_wanted_movie("tt1") is None


def test_user_requests_for_title_carry_usernames():
    uid = db.create_user("adam", "scrypt$x$y", role="user")
    admin = db.create_user("root", "scrypt$x$y", role="admin")
    rid = db.create_user_request(uid, "tt0113277", 949, "movie", "Heat", None)
    db.update_user_request_status(rid, "approved", reviewed_by=admin, note="fine")
    rows = db.get_user_requests_for_title("tt0113277")
    assert rows[0]["username"] == "adam" and rows[0]["reviewer"] == "root" and rows[0]["note"] == "fine"


def test_hashes_for_title_join_the_blacklist_and_mark_the_current_one():
    rid = db.insert_request("Heat", "tt0113277", "movie")
    db.update_request(rid, "success", info_hash="b" * 40)
    _item("tt0113277", "tok1", "a" * 40)
    _item("tt0113277", "tok2", "b" * 40, torbox_id=7)
    db.blacklist_hash("a" * 40, "blacklisted by admin")
    rows = {r["info_hash"]: r for r in db.get_hashes_for_title("tt0113277")}
    assert rows["a" * 40]["blacklisted"] is True and rows["a" * 40]["last_error"] == "blacklisted by admin"
    assert rows["b" * 40]["blacklisted"] is False and rows["b" * 40]["current"] is True
    assert ("a" * 40) in db.get_blacklisted_hashes()
    db.clear_failed_hash("a" * 40)
    assert ("a" * 40) not in db.get_blacklisted_hashes()


def test_hashes_for_title_uses_the_configured_threshold_like_blacklist_hash_does(monkeypatch):
    """get_hashes_for_title must agree with blacklist_hash and
    get_blacklisted_hashes about what counts as blacklisted; all three read
    BLACKLIST_FAIL_THRESHOLD through settings, not a hardcoded 3."""
    import settings
    monkeypatch.setattr(settings, "get", lambda key, default=None:
                        1 if key == "BLACKLIST_FAIL_THRESHOLD" else default)
    db.insert_request("Heat", "tt0113277", "movie")
    _item("tt0113277", "tok1", "a" * 40)
    db.record_failed_hash("a" * 40, "cdn 404")
    rows = {r["info_hash"]: r for r in db.get_hashes_for_title("tt0113277")}
    assert rows["a" * 40]["fail_count"] == 1
    assert rows["a" * 40]["blacklisted"] is True


def test_playability_for_title_covers_movie_and_episode_keys():
    db.update_playability_fail("tt1", "cdn 404")
    db.update_playability_fail("tt2:S01E02", "timeout")
    db.update_playability_ok("tt2:S01E03", "torbox")
    assert [r["content_key"] for r in db.get_playability_for_title("tt1")] == ["tt1"]
    keys = {r["content_key"] for r in db.get_playability_for_title("tt2")}
    assert keys == {"tt2:S01E02", "tt2:S01E03"}
    assert db.reset_playability_for_title("tt2") == 2
    assert all(r["status"] == "unknown" for r in db.get_playability_for_title("tt2"))


def test_series_reads_by_imdb():
    db.upsert_monitored_series("tt2", 100, "Show", [1, 2])
    db.upsert_wanted_episode("tt2", 100, "Show", 1, 2, "2024-01-01")
    assert db.get_monitored_series_by_imdb("tt2")["title"] == "Show"
    assert db.get_wanted_episodes_for_title("tt2")[0]["episode"] == 2
    assert db.get_monitored_series_by_imdb("nope") is None


def test_the_new_indexes_exist():
    with db._connect() as conn:
        names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_activity_imdb", "idx_user_requests_imdb", "idx_wanted_episodes_imdb_status",
            "idx_requests_info_hash"} <= names


def test_titles_for_hashes_matches_via_requests_and_virtual_items_in_one_query():
    db.insert_request("Heat", "tt1", "movie")
    db.insert_request("Alien", "tt2", "movie")
    # tt1's request row carries the hash directly.
    db.set_request_release(db.get_request_by_imdb("tt1")["id"], "1080p", "src", "a" * 40)
    # tt2 only has the hash on its virtual_items row.
    _item("tt2", "tok", "b" * 40)
    out = db.titles_for_hashes(["a" * 40, "b" * 40, "c" * 40])
    assert out["a" * 40] == [{"imdb_id": "tt1", "title": "Heat"}]
    assert out["b" * 40] == [{"imdb_id": "tt2", "title": "Alien"}]
    assert out["c" * 40] == []


def test_titles_for_hashes_with_no_hashes_returns_empty():
    assert db.titles_for_hashes([]) == {}


def test_titles_for_hashes_spans_chunks(monkeypatch):
    """A hash list longer than one chunk still returns matches from every
    chunk. _HASH_CHUNK is forced down to 2 so 5 hashes span three chunks
    ([0,1], [2,3], [4]); the match in the first chunk and the match in the
    last chunk must both survive the merge, which is what this test is
    really pinning (not the chunk size itself)."""
    monkeypatch.setattr(db, "_HASH_CHUNK", 2)
    db.insert_request("Heat", "tt1", "movie")
    db.insert_request("Alien", "tt2", "movie")
    hashes = [f"{i:040x}" for i in range(5)]
    db.set_request_release(db.get_request_by_imdb("tt1")["id"], "1080p", "src", hashes[0])
    _item("tt2", "tok", hashes[-1])
    out = db.titles_for_hashes(hashes)
    assert out[hashes[0]] == [{"imdb_id": "tt1", "title": "Heat"}]
    assert out[hashes[-1]] == [{"imdb_id": "tt2", "title": "Alien"}]
    assert sum(1 for v in out.values() if v) == 2


def test_blacklist_route_attaches_titles_for_each_hash_in_one_call():
    src = _src("app.py")
    route = src.split('def ui_api_blacklist():', 1)[1][:300]
    assert "titles_for_hashes" in route
    assert "titles_for_hash(" not in route
