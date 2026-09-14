"""Important 2, monitor.py: fixed-mode episode adds (_retry_episode, not
CATBOX_MODE) check every enabled account's library first
(torbox_pool.find_hash_anywhere), not just the one choose_for_add() would
pick for a brand new torrent, so a torrent another account already holds
is never re-added."""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db
import monitor
import torbox_pool as pool

torbox = monitor.torbox


def _db_modules():
    import catbox
    mods = []
    for m in (db, monitor.db, catbox.db, pool.db):
        if not any(m is x for x in mods):
            mods.append(m)
    return mods


def _drop_cached_conn():
    for m in _db_modules():
        conn = getattr(m._tls, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            m._tls.conn = None


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    _drop_cached_conn()
    for m in _db_modules():
        monkeypatch.setattr(m, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("TORBOX_API_KEY", "k1")
    _drop_cached_conn()
    db.init()
    db.insert_torbox_account("second", "k2")
    pool.invalidate()
    pool._health.clear()
    monkeypatch.setattr(monitor._settings, "get", lambda key, default=None: False if key == "CATBOX_MODE" else default)
    yield
    _drop_cached_conn()


_H = "c" * 40


def _wanted():
    db.upsert_wanted_episode("tt9288030", 108978, "Reacher", 4, 4, "2026-08-19")
    return db.get_wanted_episode("tt9288030", 4, 4)


def test_retry_episode_uses_the_account_that_already_holds_the_hash(monkeypatch):
    ep = _wanted()
    cand = SimpleNamespace(info_hash=_H, magnet=f"magnet:?xt=urn:btih:{_H}",
                           is_season_pack=False, quality="1080p", name="Reacher.S04E04", size_gb=1.0)
    monkeypatch.setattr(monitor.scrapers, "fetch_candidates", lambda *a, **k: [cand])
    monkeypatch.setattr(monitor.torbox, "check_cached", lambda hashes: set(hashes))
    monkeypatch.setattr(pool, "choose_for_add", lambda: pool.account(1))

    ready = {"id": 9, "hash": _H, "download_state": "cached", "download_finished": True}
    calls = []

    def fake_find_by_hash(account_id, info_hash, **k):
        calls.append(("find_by_hash", account_id))
        return dict(ready) if account_id == 2 else None

    def fake_add_magnet(account_id, magnet, **k):
        calls.append(("add_magnet", account_id))
        return {"id": 1}

    def fake_wait_until_ready(account_id, info_hash, **k):
        calls.append(("wait_until_ready", account_id))
        return {"id": 1}

    monkeypatch.setattr(torbox, "find_by_hash", fake_find_by_hash)
    monkeypatch.setattr(torbox, "add_magnet", fake_add_magnet)
    monkeypatch.setattr(torbox, "wait_until_ready", fake_wait_until_ready)

    assert monitor._retry_episode(ep) is True
    assert not any(name in ("add_magnet", "wait_until_ready") for name, _ in calls), \
        "already ready on account 2: no add, no wait anywhere"
    assert ("add_magnet", 1) not in calls and ("wait_until_ready", 1) not in calls
