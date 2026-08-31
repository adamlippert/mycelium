"""
Unit tests for the createtorrent rate-limit reservation in torbox.py.

Covers the TOCTOU fix: reserving a slot must count against the budget
immediately (before the HTTP call happens), and releasing a slot after a
failed call must give the budget back.
"""
import os
import sys

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
