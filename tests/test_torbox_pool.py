"""Accounts table, migrations and torbox_pool: account 1 mirrors
TORBOX_API_KEY, extra accounts live in the table, choose_for_add picks the
least loaded healthy account and never fails outright."""
import os
import sqlite3
import time

import pytest

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
    monkeypatch.setenv("TORBOX_API_KEY", "k1")
    _drop_cached_conn()
    db.init()
    settings.set("TORBOX_API_KEY", "k1")
    pool.invalidate()
    pool._health.clear()
    yield
    _drop_cached_conn()


def _item(token, account_id, torbox_id=5):
    with db._connect() as conn:
        conn.execute("INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, torbox_id, torbox_account) "
                     "VALUES (?, 'h', 'm', ?, 'movie', ?, ?)", (token, token, torbox_id, account_id))
        conn.commit()


# migration and table

def test_init_seeds_account_1_from_the_configured_key_once():
    rows = db.list_torbox_accounts()
    assert [(r["id"], r["label"], r["api_key"], r["enabled"]) for r in rows] == [(1, "main", "k1", 1)]
    db.init()
    assert len(db.list_torbox_accounts()) == 1, "idempotent"


def test_migration_marks_homed_items_and_budget_rows_as_account_1(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE virtual_items (token TEXT PRIMARY KEY, info_hash TEXT, magnet TEXT, title TEXT,
            media_type TEXT, torbox_id INTEGER, last_played TEXT);
        INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, torbox_id) VALUES ('a', 'h', 'm', 'A', 'movie', 7);
        INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, torbox_id) VALUES ('b', 'h', 'm', 'B', 'movie', NULL);
        CREATE TABLE createtorrent_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
            reason TEXT NOT NULL DEFAULT '', cached INTEGER NOT NULL DEFAULT 0);
        INSERT INTO createtorrent_log (ts, reason) VALUES (1.0, 'x');
    """)
    conn.commit(); conn.close()
    _drop_cached_conn()
    monkeypatch.setattr(db, "DB_PATH", str(path))
    db.init()
    assert db.get_virtual_item("a")["torbox_account"] == 1
    assert db.get_virtual_item("b")["torbox_account"] is None
    assert db.get_createtorrent_log(0.0) == [(1.0, "x", False, 1)]


def test_account_crud_and_key_mirroring():
    two = db.insert_torbox_account("second", "k2")
    assert two == 2
    db.update_torbox_account(2, enabled=False)
    assert db.get_torbox_account(2)["enabled"] == 0
    db.update_torbox_account(2, label="backup", api_key="k2b", enabled=True)
    assert db.get_torbox_account(2)["label"] == "backup" and db.get_torbox_account(2)["api_key"] == "k2b"
    settings.set("TORBOX_API_KEY", "k1-new")
    assert db.get_torbox_account(1)["api_key"] == "k1-new"
    db.delete_torbox_account(2)
    assert db.get_torbox_account(2) is None
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_torbox_account("main", "dup")


def test_set_virtual_torbox_writes_and_clears_both_columns():
    _item("t", None, torbox_id=None)
    db.set_virtual_torbox("t", 9, 2)
    it = db.get_virtual_item("t")
    assert (it["torbox_id"], it["torbox_account"]) == (9, 2)
    db.set_virtual_torbox("t", None, None)
    it = db.get_virtual_item("t")
    assert (it["torbox_id"], it["torbox_account"]) == (None, None)
    db.set_virtual_torbox("t", 9, 2)
    db.update_virtual_item_upgrade("t", "h2", "m2", None, None)
    it = db.get_virtual_item("t")
    assert (it["torbox_id"], it["torbox_account"]) == (None, None), "an upgrade clears the home too"


def test_budget_is_counted_per_account():
    now = time.time()
    for _ in range(3):
        db.reserve_createtorrent_slot(now, "x", 60, 10, account_id=1)
    db.reserve_createtorrent_slot(now, "x", 60, 10, account_id=2)
    assert db.reserve_createtorrent_slot(now, "x", 60, 10, account_id=2)["hour_count"] == 2
    assert len(db.get_createtorrent_log(now - 1, account_id=1)) == 3
    assert len(db.get_createtorrent_log(now - 1)) == 5
    assert db.count_items_by_account() == {}
    _item("a", 1); _item("b", 1); _item("c", 2)
    assert db.count_items_by_account() == {1: 2, 2: 1}


# pool

def test_accounts_reads_the_table_with_account_1_from_settings(monkeypatch):
    db.insert_torbox_account("second", "k2")
    db.insert_torbox_account("off", "k3")
    db.update_torbox_account(3, enabled=False)
    settings.set("TORBOX_API_KEY", "k1-live")
    pool.invalidate()
    assert [(a.id, a.label, a.api_key, a.enabled) for a in pool.accounts()] == [(1, "main", "k1-live", True), (2, "second", "k2", True)]
    assert [a.id for a in pool.accounts(enabled_only=False)] == [1, 2, 3]
    assert pool.account(3).enabled is False and pool.account(9) is None
    assert pool.any_key() == "k1-live"


def test_accounts_cache_is_sixty_seconds_and_invalidate_drops_it(monkeypatch):
    pool.accounts()
    db.insert_torbox_account("second", "k2")
    assert [a.id for a in pool.accounts()] == [1], "cached"
    pool.invalidate()
    assert [a.id for a in pool.accounts()] == [1, 2]
    db.insert_torbox_account("third", "k3")
    real_monotonic = time.monotonic
    monkeypatch.setattr(pool.time, "monotonic", lambda: real_monotonic() + 61)
    assert [a.id for a in pool.accounts()] == [1, 2, 3]


def test_choose_for_add_picks_fewest_torrents_then_budget_then_lowest_id(monkeypatch):
    db.insert_torbox_account("second", "k2")
    db.insert_torbox_account("third", "k3")
    pool.invalidate()
    _item("a", 1); _item("b", 1); _item("c", 2)
    assert pool.choose_for_add().id == 3, "holds nothing"
    _item("d", 3); _item("e", 3)
    assert pool.choose_for_add().id == 2, "one item beats two"
    now = time.time()
    for _ in range(5):
        db.reserve_createtorrent_slot(now, "x", 60, 10, account_id=2)
    _item("f", 2)
    _item("h", 1)  # keeps account 1 (full budget) out of the 2-vs-3 tie below
    # 2 and 3 tie on two items each; 3 has more budget left
    assert pool.choose_for_add().id == 3
    _item("g", 3)
    # 2 (two items, budget 55) vs 3 (three items): fewest torrents wins first
    assert pool.choose_for_add().id == 2


def test_choose_for_add_excludes_limited_failed_and_exhausted_accounts_then_falls_back(monkeypatch):
    db.insert_torbox_account("second", "k2")
    pool.invalidate()
    _item("a", 1)
    pool.mark_429(2)
    assert pool.choose_for_add().id == 1, "2 answered 429 within the window"
    with pytest.MonkeyPatch.context() as mp:
        real_time = time.time
        mp.setattr(pool.time, "time", lambda: real_time() + pool.EXCLUDE_WINDOW_SEC + 1)
        assert pool.choose_for_add().id == 2, "window over"
        pool.mark_auth_failure(2)
        assert pool.choose_for_add().id == 1
    pool._health.clear()
    # reserve_createtorrent_slot keeps its own 2-slot safety margin against
    # hour_limit, so it can never itself drive the log low enough to hit
    # MIN_BUDGET_LEFT; seed the log directly to simulate a near-exhausted hour.
    now = time.time()
    with db._connect() as conn:
        for i in range(59):
            conn.execute(
                "INSERT INTO createtorrent_log (ts, reason, cached, account) VALUES (?, 'x', 0, 2)",
                (now - i,))
        conn.commit()
    assert pool.choose_for_add().id == 1, "2 has fewer than two uncached adds left"
    pool.mark_429(1)
    chosen = pool.choose_for_add()
    assert chosen.id in (1, 2), "every account excluded: still returns one"
    db.update_torbox_account(1, enabled=False)
    pool.invalidate()
    assert pool.choose_for_add().id == 2, "disabled accounts never chosen"


def test_health_reports_marks_budget_and_torrents():
    _item("a", 1)
    h = pool.health(1)
    assert h["torrents"] == 1 and h["budget_left"] == 60 and h["rate_limited_until"] is None and h["auth_failed_at"] is None
    pool.mark_429(1)
    assert pool.health(1)["rate_limited_until"] > time.time()
