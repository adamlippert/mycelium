"""
Unit tests for the createtorrent rate-limit reservation in torbox.py.

Covers the TOCTOU fix: reserving a slot must count against the budget
immediately (before the HTTP call happens), and releasing a slot after a
failed call must give the budget back.
"""
import os
import sys

import time

import pytest

os.environ.setdefault("TORBOX_API_KEY", "test")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Other test modules (test_strm_generator.py) replace sys.modules["torbox"]
# with a MagicMock at collection time and only restore it once their own
# tests run. Grab a real import for our own use, then put back whatever was
# there so those other files' torbox_mod references stay mocked as they
# expect - our own `torbox` name below stays bound to the real module either way.
_prior_torbox = sys.modules.get("torbox")
sys.modules.pop("torbox", None)
import torbox  # noqa: E402
if _prior_torbox is not None:
    sys.modules["torbox"] = _prior_torbox
else:
    sys.modules.pop("torbox", None)


import db


def _drop_cached_conn():
    conn = getattr(db._tls, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        db._tls.conn = None


@pytest.fixture(autouse=True)
def _isolated_log(tmp_path, monkeypatch):
    """The reservation log lives in SQLite (the single source of truth, so
    the budget holds across processes); give each test its own database."""
    _drop_cached_conn()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    _drop_cached_conn()
    db.init()
    yield
    _drop_cached_conn()


def _log_count():
    with db._connect() as conn:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM createtorrent_log").fetchone()["n"]


def test_reservation_counts_immediately():
    entry = torbox._reserve_createtorrent_slot("test")
    assert isinstance(entry, int)
    assert _log_count() == 1


def test_release_gives_the_slot_back():
    entry = torbox._reserve_createtorrent_slot("test")
    torbox._release_createtorrent_slot(entry)
    assert _log_count() == 0


def test_usage_reads_from_the_database():
    torbox._reserve_createtorrent_slot("play")
    torbox._reserve_createtorrent_slot("play")
    torbox._reserve_createtorrent_slot("upgrade")

    usage = torbox.createtorrent_usage()

    assert usage["count"] == 3
    assert usage["by_reason"] == {"play": 2, "upgrade": 1}


def test_hourly_limit_blocks_reservation_once_reached(monkeypatch):
    monkeypatch.setattr(torbox, "_CREATETORRENT_LIMIT_MIN", 10_000)  # isolate the hourly check
    for _ in range(torbox._CREATETORRENT_LIMIT_HOUR - 2):
        torbox._reserve_createtorrent_slot("test")
    with pytest.raises(torbox.RateLimited):
        torbox._reserve_createtorrent_slot("test")


def test_released_slot_is_available_again(monkeypatch):
    monkeypatch.setattr(torbox, "_CREATETORRENT_LIMIT_MIN", 10_000)  # isolate the hourly check
    entries = [torbox._reserve_createtorrent_slot("test")
               for _ in range(torbox._CREATETORRENT_LIMIT_HOUR - 2)]
    with pytest.raises(torbox.RateLimited):
        torbox._reserve_createtorrent_slot("test")
    torbox._release_createtorrent_slot(entries[0])
    # Releasing one slot should free up room for exactly one more reservation.
    torbox._reserve_createtorrent_slot("test")
    with pytest.raises(torbox.RateLimited):
        torbox._reserve_createtorrent_slot("test")


# -- cached adds do not count against the hour ---------------------------------

def test_cached_reservation_skips_the_hourly_budget(monkeypatch):
    monkeypatch.setattr(torbox, "_CREATETORRENT_LIMIT_MIN", 10_000)
    for _ in range(torbox._CREATETORRENT_LIMIT_HOUR - 2):
        torbox._reserve_createtorrent_slot("play")
    with pytest.raises(torbox.RateLimited):
        torbox._reserve_createtorrent_slot("play")
    entry = torbox._reserve_createtorrent_slot("play", cached=True)
    assert isinstance(entry, int), "a cached add goes through with the hour full"
    usage = torbox.createtorrent_usage()
    assert usage["count"] == torbox._CREATETORRENT_LIMIT_HOUR - 2
    assert usage["cached_count"] == 1
    assert "play" in usage["by_reason"] and usage["by_reason"]["play"] == torbox._CREATETORRENT_LIMIT_HOUR - 2


def test_cached_reservation_still_obeys_the_per_minute_burst(monkeypatch):
    monkeypatch.setattr(torbox, "_CREATETORRENT_LIMIT_MIN", 3)
    torbox._reserve_createtorrent_slot("play", cached=True)
    torbox._reserve_createtorrent_slot("play", cached=True)
    with pytest.raises(torbox.RateLimited):
        torbox._reserve_createtorrent_slot("play", cached=True)


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status
        self.headers = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def test_torbox_saying_cached_frees_the_hourly_slot(monkeypatch):
    monkeypatch.setattr(torbox, "_CREATETORRENT_LIMIT_MIN", 10_000)
    monkeypatch.setattr(torbox, "_headers", lambda: {})
    monkeypatch.setattr(torbox, "_base_url", lambda: "http://torbox.test")
    monkeypatch.setattr(torbox, "invalidate_mylist_cache", lambda: None)
    monkeypatch.setattr(torbox.requests, "post", lambda *a, **k: _Resp(
        {"success": True, "detail": "Found cached torrent. Using cached torrent.", "data": {"torrent_id": 7}}))
    torbox.add_magnet("magnet:?xt=urn:btih:" + "a" * 40, reason="processor")  # caller did not know
    usage = torbox.createtorrent_usage()
    assert usage["count"] == 0 and usage["cached_count"] == 1


def test_torbox_queueing_a_download_counts_even_when_the_caller_expected_cached(monkeypatch):
    monkeypatch.setattr(torbox, "_CREATETORRENT_LIMIT_MIN", 10_000)
    monkeypatch.setattr(torbox, "_headers", lambda: {})
    monkeypatch.setattr(torbox, "_base_url", lambda: "http://torbox.test")
    monkeypatch.setattr(torbox, "invalidate_mylist_cache", lambda: None)
    monkeypatch.setattr(torbox.requests, "post", lambda *a, **k: _Resp(
        {"success": True, "detail": "Torrent added to queue.", "data": {"id": 8}}))
    torbox.add_magnet("magnet:?xt=urn:btih:" + "b" * 40, reason="processor", cached=True)
    usage = torbox.createtorrent_usage()
    assert usage["count"] == 1 and usage["cached_count"] == 0


def test_a_duplicate_item_answer_is_not_an_uncached_add(monkeypatch):
    monkeypatch.setattr(torbox, "_CREATETORRENT_LIMIT_MIN", 10_000)
    monkeypatch.setattr(torbox, "_headers", lambda: {})
    monkeypatch.setattr(torbox, "_base_url", lambda: "http://torbox.test")
    monkeypatch.setattr(torbox, "invalidate_mylist_cache", lambda: None)
    monkeypatch.setattr(torbox.requests, "post", lambda *a, **k: _Resp(
        {"success": False, "error": "DUPLICATE_ITEM", "data": {}}))
    torbox.add_magnet("magnet:?xt=urn:btih:" + "c" * 40, reason="processor")
    assert torbox.createtorrent_usage()["count"] == 0


def test_an_existing_log_gains_the_cached_column():
    import sqlite3
    _drop_cached_conn()
    with sqlite3.connect(db.DB_PATH) as conn:
        conn.execute("DROP TABLE createtorrent_log")
        conn.execute("CREATE TABLE createtorrent_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, reason TEXT NOT NULL DEFAULT '')")
        conn.execute("INSERT INTO createtorrent_log (ts, reason) VALUES (?, 'old')", (time.time(),))
        conn.commit()
    db.init()
    usage = torbox.createtorrent_usage()
    assert usage["count"] == 1 and usage["cached_count"] == 0, "pre-migration rows count as uncached"


def test_cached_rows_do_not_fill_the_hour_for_an_uncached_add(monkeypatch):
    monkeypatch.setattr(torbox, "_CREATETORRENT_LIMIT_MIN", 10_000)
    for _ in range(torbox._CREATETORRENT_LIMIT_HOUR + 5):
        torbox._reserve_createtorrent_slot("play", cached=True)
    entry = torbox._reserve_createtorrent_slot("play")
    assert isinstance(entry, int), "65 cached adds leave the uncached budget untouched"
    assert torbox.createtorrent_usage()["count"] == 1
