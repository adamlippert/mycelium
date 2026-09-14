"""release_idle deletes through the item's home account, not a fixed one,
and never calls TorBox for an item whose home is disabled or unknown."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
_prior_torbox = sys.modules.get("torbox")
sys.modules.pop("torbox", None)
import torbox  # noqa: E402
if _prior_torbox is not None:
    sys.modules["torbox"] = _prior_torbox
else:
    sys.modules.pop("torbox", None)

import catbox  # noqa: E402
import db  # noqa: E402
import overview  # noqa: E402
import torbox_pool as pool  # noqa: E402


def _db_modules():
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
    import settings
    settings.set("TORBOX_API_KEY", "k1")
    pool.invalidate()
    pool._health.clear()
    catbox.invalidate_url_cache()
    with catbox._reconcile_lock:
        catbox._last_reconcile = None
    yield
    _drop_cached_conn()


def test_release_idle_deletes_through_the_items_home_and_clears_both_columns(monkeypatch):
    db.insert_torbox_account("second", "k2"); pool.invalidate()
    with db._connect() as conn:
        conn.execute("INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, torbox_id, torbox_account, last_played) "
                     "VALUES ('old', 'h', 'm', 'Old', 'movie', 7, 2, '2000-01-01 00:00:00')")
        conn.commit()
    deleted = []
    monkeypatch.setattr(catbox.torbox, "delete_torrent", lambda acct, tid, **k: (deleted.append((acct, tid)), True)[1])
    assert catbox.release_idle() == 1
    assert deleted == [(2, 7)]
    it = db.get_virtual_item("old")
    assert (it["torbox_id"], it["torbox_account"]) == (None, None)


def test_release_idle_on_a_disabled_home_clears_locally_without_calling_torbox(monkeypatch):
    second = db.insert_torbox_account("second", "k2"); pool.invalidate()
    db.update_torbox_account(second, enabled=False); pool.invalidate()
    with db._connect() as conn:
        conn.execute("INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, torbox_id, torbox_account, last_played) "
                     "VALUES ('stuck', 'h', 'm', 'Stuck', 'movie', 9, ?, '2000-01-01 00:00:00')", (second,))
        conn.commit()
    calls = []
    monkeypatch.setattr(catbox.torbox, "delete_torrent", lambda acct, tid, **k: calls.append((acct, tid)) or True)
    monkeypatch.setattr(catbox.torbox, "find_by_id", lambda acct, tid, **k: calls.append((acct, tid)) or None)
    assert catbox.release_idle() == 1
    assert calls == [], "a disabled account's torrent is never touched through the client"
    it = db.get_virtual_item("stuck")
    assert (it["torbox_id"], it["torbox_account"]) == (None, None)


def test_release_idle_with_no_home_at_all_clears_without_calling_torbox(monkeypatch):
    with db._connect() as conn:
        conn.execute("INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, torbox_id, torbox_account, last_played) "
                     "VALUES ('orphan', 'h', 'm', 'Orphan', 'movie', 5, NULL, '2000-01-01 00:00:00')")
        conn.commit()
    calls = []
    monkeypatch.setattr(catbox.torbox, "delete_torrent", lambda acct, tid, **k: calls.append((acct, tid)) or True)
    assert catbox.release_idle() == 1
    assert calls == []
    it = db.get_virtual_item("orphan")
    assert (it["torbox_id"], it["torbox_account"]) == (None, None)
