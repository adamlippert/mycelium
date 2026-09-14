"""metrics_prom.refresh_gauges(): TorBox gauges are reported per account
(torrent count, total bytes, uncached adds used this hour, active-in-torbox
items, and whether the account is currently excluded by an auth failure),
not summed into one "account 1 for now" figure."""
import os
import sys
import time

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db
import metrics_prom
import settings
import torbox
import torbox_pool


from _helpers import _drop_cached_conn

@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    _drop_cached_conn()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("TORBOX_API_KEY", "k1")
    _drop_cached_conn()
    db.init()
    settings.set("TORBOX_API_KEY", "k1")
    torbox_pool.invalidate()
    torbox_pool._health.clear()
    yield
    _drop_cached_conn()


def _item(token, account_id, torbox_id=5):
    with db._connect() as conn:
        conn.execute("INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, torbox_id, torbox_account) "
                     "VALUES (?, 'h', 'm', ?, 'movie', ?, ?)", (token, token, torbox_id, account_id))
        conn.commit()


_USAGE = {
    1: {"torrent_count": 12, "total_bytes": 1_000_000},
    2: {"torrent_count": 34, "total_bytes": 2_000_000},
}


def test_torrent_count_and_bytes_are_reported_per_account(monkeypatch):
    db.insert_torbox_account("second", "k2")
    torbox_pool.invalidate()
    monkeypatch.setattr(torbox, "get_usage_summary", lambda account_id: _USAGE[account_id])
    metrics_prom.refresh_gauges()
    assert metrics_prom.torbox_torrent_count.labels(account="main")._value.get() == 12
    assert metrics_prom.torbox_torrent_count.labels(account="second")._value.get() == 34
    assert metrics_prom.torbox_total_bytes.labels(account="main")._value.get() == 1_000_000
    assert metrics_prom.torbox_total_bytes.labels(account="second")._value.get() == 2_000_000


def test_createtorrent_used_is_reported_per_account(monkeypatch):
    db.insert_torbox_account("second", "k2")
    torbox_pool.invalidate()
    monkeypatch.setattr(torbox, "get_usage_summary", lambda account_id: _USAGE[account_id])
    now = time.time()
    for i in range(3):
        db.reserve_createtorrent_slot(now + i, "x", 60, 10, account_id=1)
    for i in range(5):
        db.reserve_createtorrent_slot(now + i, "x", 60, 10, account_id=2)
    metrics_prom.refresh_gauges()
    assert metrics_prom.torbox_createtorrent_used.labels(account="main")._value.get() == 3
    assert metrics_prom.torbox_createtorrent_used.labels(account="second")._value.get() == 5


def test_active_in_torbox_is_reported_per_account(monkeypatch):
    db.insert_torbox_account("second", "k2")
    torbox_pool.invalidate()
    monkeypatch.setattr(torbox, "get_usage_summary", lambda account_id: _USAGE[account_id])
    _item("a", 1); _item("b", 1); _item("c", 2)
    metrics_prom.refresh_gauges()
    assert metrics_prom.catbox_active_in_torbox.labels(account="main")._value.get() == 2
    assert metrics_prom.catbox_active_in_torbox.labels(account="second")._value.get() == 1


def test_account_up_reflects_a_recent_auth_failure_only(monkeypatch):
    db.insert_torbox_account("second", "k2")
    torbox_pool.invalidate()
    monkeypatch.setattr(torbox, "get_usage_summary", lambda account_id: _USAGE[account_id])
    torbox_pool.mark_auth_failure(2)
    metrics_prom.refresh_gauges()
    assert metrics_prom.torbox_account_up.labels(account="main")._value.get() == 1
    assert metrics_prom.torbox_account_up.labels(account="second")._value.get() == 0


def test_account_up_recovers_once_the_auth_failure_ages_out(monkeypatch):
    db.insert_torbox_account("second", "k2")
    torbox_pool.invalidate()
    monkeypatch.setattr(torbox, "get_usage_summary", lambda account_id: _USAGE[account_id])
    torbox_pool._health[2] = {"auth_failed_at": time.time() - torbox_pool.EXCLUDE_WINDOW_SEC - 1}
    metrics_prom.refresh_gauges()
    assert metrics_prom.torbox_account_up.labels(account="second")._value.get() == 1


def test_one_account_failing_does_not_stop_the_others_from_being_scraped(monkeypatch):
    """get_usage_summary() raising for one account (AuthFailed on 401/403,
    or a network error) must not abort the scrape for every later account,
    and the failing account's own torbox_account_up must still read 0 -
    computed from torbox_pool.health(), which makes no network call."""
    db.insert_torbox_account("second", "k2")
    torbox_pool.invalidate()

    def fake_summary(account_id):
        if account_id == 1:
            # As the real client does (torbox._check_auth): record the auth
            # failure on the pool before raising.
            torbox_pool.mark_auth_failure(1)
            raise torbox.AuthFailed("account 1: 401")
        return _USAGE[account_id]

    monkeypatch.setattr(torbox, "get_usage_summary", fake_summary)
    metrics_prom.refresh_gauges()
    assert metrics_prom.torbox_torrent_count.labels(account="second")._value.get() == 34
    assert metrics_prom.torbox_account_up.labels(account="main")._value.get() == 0


def test_a_single_account_install_reports_one_labelled_series(monkeypatch):
    monkeypatch.setattr(torbox, "get_usage_summary", lambda account_id: _USAGE[1])
    metrics_prom.refresh_gauges()
    assert metrics_prom.torbox_torrent_count.labels(account="main")._value.get() == 12
