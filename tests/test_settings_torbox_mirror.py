"""settings.set(TORBOX_API_KEY) must always leave the TorBox account pool
in sync with the setting, with no restart needed.

Two failure modes fixed here:
- a fresh install (no env key, empty torbox_accounts table) saving the key
  for the first time through the wizard/Settings never created account 1,
  so the pool stayed empty until a restart;
- editing an existing key left the pool's 60-second cache holding the old
  key for up to a minute.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import config
import db
import settings
import torbox_pool as pool


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
    # A fresh install: no env key at all, so db.init()'s migration (which
    # only seeds torbox_accounts when a key is already configured) seeds
    # nothing.
    monkeypatch.delenv("TORBOX_API_KEY", raising=False)
    monkeypatch.setattr(config, "TORBOX_API_KEY", "")
    _drop_cached_conn()
    db.init()
    pool.invalidate()
    pool._health.clear()
    yield
    _drop_cached_conn()


def test_fresh_install_has_no_accounts_until_a_key_is_saved():
    assert db.list_torbox_accounts() == []
    assert pool.accounts() == []


def test_first_save_on_a_fresh_install_seeds_account_1_immediately():
    settings.set("TORBOX_API_KEY", "k1")
    accts = pool.accounts()
    assert len(accts) == 1
    assert accts[0].id == 1
    assert accts[0].label == "main"
    assert accts[0].api_key == "k1"
    # choose_for_add() must not raise "no enabled TorBox account" right
    # after the wizard save.
    chosen = pool.choose_for_add()
    assert chosen.id == 1


def test_first_save_inserts_the_row_in_the_database_too():
    settings.set("TORBOX_API_KEY", "k1")
    row = db.get_torbox_account(1)
    assert row is not None
    assert row["label"] == "main"
    assert row["api_key"] == "k1"


def test_second_save_is_visible_through_the_pool_with_no_restart():
    settings.set("TORBOX_API_KEY", "k1")
    settings.set("TORBOX_API_KEY", "k1b")
    # No time.sleep(60) and no pool.invalidate() call here: the fix must
    # invalidate the pool's cache itself on every save.
    acct = pool.account(1)
    assert acct is not None
    assert acct.api_key == "k1b"
    assert pool.accounts()[0].api_key == "k1b"


def test_editing_an_existing_row_1_still_mirrors_and_invalidates(monkeypatch):
    # An install that already has account 1 (the common path, covered by
    # test_torbox_pool.py's fixture) must keep working through the same
    # branch: update, not insert.
    settings.set("TORBOX_API_KEY", "k1")
    before_id = db.get_torbox_account(1)["created_at"]
    settings.set("TORBOX_API_KEY", "k2")
    after = db.get_torbox_account(1)
    assert after["api_key"] == "k2"
    assert after["created_at"] == before_id, "editing must not re-insert the row"
    assert len(db.list_torbox_accounts()) == 1
    assert pool.account(1).api_key == "k2"
