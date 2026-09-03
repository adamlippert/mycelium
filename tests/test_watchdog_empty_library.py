"""The deadman switch was silent in the one state it exists to catch.

_last_success_age_hours() returns None when the activity log holds no
successful add, and deadman_check() returned early on None. A database that
has been wiped or is pointed at an unmounted volume therefore produced
silence, indistinguishable from a fresh install. Production lost its entire
database on 2026-09-02 and nothing alerted; it was found by clicking around.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db
import watchdog


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
    watchdog._last_warn.clear()
    yield
    watchdog._last_warn.clear()
    _drop_cached_conn()


@pytest.fixture()
def warnings(monkeypatch):
    fired = []
    monkeypatch.setattr(watchdog, "_warn",
                        lambda metric, title, message: fired.append((metric, title, message)))
    return fired


def test_configured_but_empty_library_alerts(warnings):
    """Setup complete plus nothing in the library is a wiped or unmounted
    database, not a fresh install."""
    db.set_setting("SETUP_COMPLETE", "true")

    watchdog.deadman_check()

    assert warnings, "no alert fired for a configured but empty library"
    metric, title, message = warnings[0]
    assert metric == "empty-library"
    assert "empty" in message.lower()


def test_fresh_install_stays_quiet(warnings):
    """Before setup there is legitimately nothing, and an alert would fire on
    every first boot."""
    watchdog.deadman_check()

    assert warnings == []


def test_a_populated_library_with_recent_activity_stays_quiet(warnings):
    db.set_setting("SETUP_COMPLETE", "true")
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO virtual_items (token, info_hash, magnet, title, media_type) "
            "VALUES ('a' * 16, 'f' * 40, 'magnet:?xt=x', 'Some Movie', 'movie')")
        conn.commit()
    db.log_activity("added", "Some Movie", "ok", True)

    watchdog.deadman_check()

    assert warnings == []


def test_count_virtual_items_counts_rows():
    assert db.count_virtual_items() == 0
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO virtual_items (token, info_hash, magnet, title, media_type) "
            "VALUES ('b' * 16, 'f' * 40, 'magnet:?xt=x', 'Another', 'movie')")
        conn.commit()
    assert db.count_virtual_items() == 1
