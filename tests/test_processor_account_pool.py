"""Important 2, processor.py: adding a torrent checks every enabled
account's library first (torbox_pool.find_hash_anywhere), not just the
one choose_for_add() would pick for a brand new torrent  -  so a torrent
another account already holds is never re-added and never waited on
twice."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db
import processor
import torbox_pool as pool

# processor.py does a plain `import torbox`; alias to that exact object so
# monkeypatching here reaches every call processor.py (and torbox_pool.py's
# own lazy `import torbox`) makes  -  they all resolve the same sys.modules
# entry.
torbox = processor.torbox


def _db_modules():
    """Isolate every db module object the code under test may be bound to."""
    mods = []
    for m in (db, processor.db, pool.db):
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
    yield
    _drop_cached_conn()


class _Stream:
    def __init__(self, info_hash, magnet=None):
        self.info_hash = info_hash
        self.magnet = magnet or f"magnet:?xt=urn:btih:{info_hash}"


_H = "a" * 40
_READY = {"id": 9, "hash": _H, "download_state": "cached", "download_finished": True, "files": []}


def test_hash_on_another_account_is_neither_re_added_nor_waited_on(monkeypatch):
    """choose_for_add() picks account 1, but account 2 already holds the
    hash, ready. _try_add_magnet must use account 2 and never touch
    account 1 at all."""
    stream = _Stream(_H)
    monkeypatch.setattr(pool, "choose_for_add", lambda: pool.account(1))

    calls = []

    def fake_find_by_hash(account_id, info_hash, **k):
        calls.append(("find_by_hash", account_id))
        return dict(_READY) if account_id == 2 else None

    def fake_add_magnet(account_id, magnet, **k):
        calls.append(("add_magnet", account_id))
        return {"id": 1}

    def fake_wait_until_ready(account_id, info_hash, **k):
        calls.append(("wait_until_ready", account_id))
        return {"id": 1, "files": []}

    monkeypatch.setattr(torbox, "find_by_hash", fake_find_by_hash)
    monkeypatch.setattr(torbox, "add_magnet", fake_add_magnet)
    monkeypatch.setattr(torbox, "wait_until_ready", fake_wait_until_ready)

    ok = processor._try_add_magnet(stream, "Test Movie")

    assert ok is True
    assert ("add_magnet", 1) not in calls, calls
    assert ("wait_until_ready", 1) not in calls, calls
    assert not any(name in ("add_magnet", "wait_until_ready") for name, _ in calls), \
        "already ready on account 2: no add, no wait on either account"


def test_hash_unready_on_another_account_adds_and_waits_there_not_on_the_chosen_one(monkeypatch):
    """The hash sits on account 2 but is still downloading: the add target
    must still be account 2 (so the re-add answers DUPLICATE_ITEM and the
    poll watches the right account), never the account choose_for_add()
    would have picked for a brand new torrent."""
    stream = _Stream(_H)
    monkeypatch.setattr(pool, "choose_for_add", lambda: pool.account(1))

    calls = []
    unready = {"id": 9, "hash": _H, "download_state": "downloading", "download_finished": False}

    def fake_find_by_hash(account_id, info_hash, **k):
        calls.append(("find_by_hash", account_id))
        return dict(unready) if account_id == 2 else None

    def fake_add_magnet(account_id, magnet, **k):
        calls.append(("add_magnet", account_id))
        return {"id": 1}

    def fake_wait_until_ready(account_id, info_hash, **k):
        calls.append(("wait_until_ready", account_id))
        return {"id": 1, "download_state": "cached", "download_finished": True}

    monkeypatch.setattr(torbox, "find_by_hash", fake_find_by_hash)
    monkeypatch.setattr(torbox, "add_magnet", fake_add_magnet)
    monkeypatch.setattr(torbox, "wait_until_ready", fake_wait_until_ready)

    ok = processor._try_add_magnet(stream, "Test Movie")

    assert ok is True
    assert ("add_magnet", 1) not in calls and ("wait_until_ready", 1) not in calls, calls
    assert ("add_magnet", 2) in calls and ("wait_until_ready", 2) in calls, calls


def test_hash_nowhere_falls_back_to_choose_for_add(monkeypatch):
    """No account holds the hash yet: the normal choose_for_add() pick is
    used, unchanged from before this fix."""
    stream = _Stream(_H)
    monkeypatch.setattr(pool, "choose_for_add", lambda: pool.account(2))

    calls = []

    def fake_find_by_hash(account_id, info_hash, **k):
        calls.append(("find_by_hash", account_id))
        return None

    def fake_add_magnet(account_id, magnet, **k):
        calls.append(("add_magnet", account_id))
        return {"id": 1}

    def fake_wait_until_ready(account_id, info_hash, **k):
        calls.append(("wait_until_ready", account_id))
        return {"id": 1, "download_state": "cached", "download_finished": True}

    monkeypatch.setattr(torbox, "find_by_hash", fake_find_by_hash)
    monkeypatch.setattr(torbox, "add_magnet", fake_add_magnet)
    monkeypatch.setattr(torbox, "wait_until_ready", fake_wait_until_ready)

    ok = processor._try_add_magnet(stream, "Test Movie")

    assert ok is True
    assert ("add_magnet", 2) in calls and ("wait_until_ready", 2) in calls, calls
