"""Stored TorBox ids against TorBox's own list: gone ids are cleared so the
next play re-adds cleanly, a hash living under another id is repointed,
nothing on TorBox is ever deleted, and an empty list changes nothing."""
import os

import pytest

import catbox
import catbox_jobs
import overview

db = catbox.db
_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _db_modules():
    """test_catbox_cache_sweep.py imports catbox against a fresh db module
    object; overview may be bound to another one. Isolate every one."""
    mods = []
    for m in (db, overview.db, catbox.db):
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
    import torbox_pool
    torbox_pool.invalidate()
    torbox_pool._health.clear()
    catbox.invalidate_url_cache()
    with catbox_jobs._reconcile_lock:
        catbox_jobs._last_reconcile = None
    yield
    _drop_cached_conn()


def _item(token, torbox_id, h, account=1):
    with db._connect() as conn:
        conn.execute("INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, torbox_id, torbox_account) "
                     "VALUES (?, ?, 'm', ?, 'movie', ?, ?)", (token, h, token, torbox_id, account))
        conn.commit()


HA, HB, HC, HD = "a" * 40, "b" * 40, "c" * 40, "d" * 40


@pytest.fixture
def seeded(monkeypatch):
    _item("keep", 1, HA)      # still on TorBox under its id
    _item("moved", 2, HB)     # id gone, hash lives under id 22
    _item("gone", 3, HC)      # id gone, hash gone
    _item("busy", 4, HD)      # id gone but a play holds its token lock
    deleted = []
    monkeypatch.setattr(catbox.torbox, "delete_torrent", lambda account_id, tid, **k: deleted.append(tid))
    monkeypatch.setattr(catbox.torbox, "list_torrents",
                        lambda account_id, **k: [{"id": 1, "hash": HA.upper()}, {"id": 22, "hash": HB}, {"id": 99, "hash": "f" * 40}])
    return deleted


def test_reconcile_clears_gone_ids_repoints_moved_ones_and_deletes_nothing(seeded):
    with catbox._url_cache_lock:
        catbox._url_cache["gone"] = ("http://cdn/x", 0)
    lock = catbox._token_lock("busy")
    lock.acquire()
    try:
        out = catbox.reconcile_torbox_ids()
    finally:
        lock.release()
    assert (out["checked"], out["cleared"], out["repointed"], out["skipped"]) == (4, 1, 1, None)
    assert db.get_virtual_item("keep")["torbox_id"] == 1
    assert db.get_virtual_item("moved")["torbox_id"] == 22
    assert db.get_virtual_item("gone")["torbox_id"] is None
    assert db.get_virtual_item("busy")["torbox_id"] == 4, "a materializing item is left alone"
    with catbox._url_cache_lock:
        assert "gone" not in catbox._url_cache, "its cached CDN url is stale too"
    assert seeded == [], "never deletes on TorBox"
    assert catbox.last_reconcile()["cleared"] == 1


def test_an_empty_or_failing_list_changes_nothing(seeded, monkeypatch):
    monkeypatch.setattr(catbox.torbox, "list_torrents", lambda account_id, **k: [])
    out = catbox.reconcile_torbox_ids()
    assert out["cleared"] == 0 and out["repointed"] == 0 and out["skipped"]
    assert db.get_virtual_item("gone")["torbox_id"] == 3

    def boom(account_id, **k):
        raise RuntimeError("torbox down")
    monkeypatch.setattr(catbox.torbox, "list_torrents", boom)
    out = catbox.reconcile_torbox_ids()
    assert out["cleared"] == 0 and out["skipped"]
    assert db.get_virtual_item("gone")["torbox_id"] == 3


def test_nothing_stored_means_no_torbox_call(monkeypatch):
    calls = []
    monkeypatch.setattr(catbox.torbox, "list_torrents", lambda account_id, **k: calls.append(1) or [])
    out = catbox.reconcile_torbox_ids()
    assert out["checked"] == 0 and calls == []


def test_overview_consistency_reports_the_last_reconcile(seeded, monkeypatch):
    monkeypatch.setattr(overview, "_cached_orphans", lambda: {"db_count": 4, "strm_without_db": 0, "db_without_strm": 0})
    assert overview._consistency()["torbox_ids"] is None
    catbox.reconcile_torbox_ids()
    rec = overview._consistency()["torbox_ids"]
    assert rec["checked"] == 4 and rec["cleared"] == 2 and rec["repointed"] == 1 and rec["skipped"] is None


def test_the_reconcile_is_scheduled_hourly_in_catbox_mode():
    src = open(os.path.join(_ROOT, "app.py")).read()
    block = src.split("catbox.reconcile_torbox_ids,")[1].split(")")[0]
    assert 'trigger="interval", minutes=60' in block and 'id="torbox_reconcile"' in block
    loop = src.split("for jid in (")[1].split("):")[0]
    assert '"torbox_reconcile"' in loop, "the overlap guard (max_instances=1) covers it"


def test_reconcile_checks_each_item_against_its_own_accounts_list_and_re_homes_by_hash(monkeypatch):
    import torbox_pool as pool
    db.insert_torbox_account("second", "k2"); pool.invalidate()
    _item("on1", 1, HA, account=1)         # present in 1
    _item("moved", 2, HB, account=1)       # gone from 1, hash lives in account 2 under id 22
    _item("gone", 3, HC, account=2)        # gone everywhere
    lists = {1: [{"id": 1, "hash": HA}], 2: [{"id": 22, "hash": HB}]}
    monkeypatch.setattr(catbox.torbox, "list_torrents", lambda acct, **k: list(lists[acct]))
    out = catbox.reconcile_torbox_ids()
    assert (out["checked"], out["cleared"], out["repointed"]) == (3, 1, 1)
    m = db.get_virtual_item("moved")
    assert (m["torbox_id"], m["torbox_account"]) == (22, 2)
    g = db.get_virtual_item("gone")
    assert (g["torbox_id"], g["torbox_account"]) == (None, None)
    assert out["accounts"]["second"]["cleared"] == 1 and out["accounts"]["main"]["repointed"] == 1


def test_reconcile_skips_an_account_whose_list_fails_and_leaves_its_items(monkeypatch):
    import torbox_pool as pool
    db.insert_torbox_account("second", "k2"); pool.invalidate()
    _item("a", 1, HA, account=1)
    _item("b", 2, HB, account=2)
    def lists(acct, **k):
        if acct == 2:
            raise RuntimeError("down")
        return [{"id": 1, "hash": HA}]
    monkeypatch.setattr(catbox.torbox, "list_torrents", lists)
    out = catbox.reconcile_torbox_ids()
    assert out["accounts"]["second"]["skipped"] and db.get_virtual_item("b")["torbox_id"] == 2
    assert out["accounts"]["main"]["skipped"] is None


def test_reconcile_leaves_a_homeless_item_alone_when_every_account_is_down(monkeypatch):
    import torbox_pool as pool
    db.insert_torbox_account("second", "k2")
    third = db.insert_torbox_account("third", "k3")
    pool.invalidate()
    db.update_torbox_account(third, enabled=False)
    pool.invalidate()
    _item("stuck", 9, HA, account=third)  # homeless: its account is disabled
    def boom(acct, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(catbox.torbox, "list_torrents", boom)
    out = catbox.reconcile_torbox_ids()
    it = db.get_virtual_item("stuck")
    assert (it["torbox_id"], it["torbox_account"]) == (9, third)
    assert "main" in out["skipped"] and "second" in out["skipped"]
