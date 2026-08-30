"""The sidebar counts and the topbar TorBox pill render on every page.

Three separate calls for data that is always fetched together is three
round trips per navigation, so they come from one endpoint.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db
import shell_summary


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
    yield
    _drop_cached_conn()


def test_the_shape_is_stable_on_an_empty_install():
    """The sidebar renders before any data exists. Missing keys would render
    'undefined' badges rather than nothing."""
    d = shell_summary.get_shell_summary()
    assert set(d) == {"counts", "torbox"}
    assert set(d["counts"]) == {"watchlist", "requests", "wanted"}
    assert set(d["torbox"]) == {"state", "label"}
    assert d["counts"] == {"watchlist": 0, "requests": 0, "wanted": 0}


def test_torbox_state_is_one_of_three_values(monkeypatch):
    d = shell_summary.get_shell_summary()
    assert d["torbox"]["state"] in {"ok", "degraded", "down"}


def test_a_healthy_torbox_reads_online(monkeypatch):
    monkeypatch.setattr(shell_summary, "_torbox_state", lambda: ("ok", "TorBox online"))
    d = shell_summary.get_shell_summary()
    assert d["torbox"] == {"state": "ok", "label": "TorBox online"}


def test_torbox_failures_never_break_the_sidebar(monkeypatch):
    """The counts are the point of this endpoint. A TorBox outage must not
    take the navigation down with it."""
    def boom():
        raise RuntimeError("torbox unreachable")

    monkeypatch.setattr(shell_summary, "_torbox_state", boom)
    d = shell_summary.get_shell_summary()
    assert d["torbox"]["state"] == "down"
    assert d["counts"] == {"watchlist": 0, "requests": 0, "wanted": 0}


def test_the_endpoint_is_registered_and_authenticated():
    """Auth is a global before_request hook on /ui/api/, so the route needs no
    decorator; this pins that it lives under that prefix."""
    with open(os.path.join(os.path.dirname(__file__), "..", "app.py"), encoding="utf-8") as f:
        src = f.read()
    assert '@app.get("/ui/api/shell-summary")' in src
    assert "shell_summary.get_shell_summary(" in src


def test_counts_failures_never_break_the_sidebar(monkeypatch):
    """A db hiccup while computing counts must not 500 the shell endpoint;
    it must fall back to the stable, empty-install shape."""
    def boom():
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(db, "get_all_wanted_episodes", boom)
    monkeypatch.setattr(shell_summary, "_torbox_state", lambda: ("ok", "TorBox online"))
    d = shell_summary.get_shell_summary()
    assert d["counts"] == {"watchlist": 0, "requests": 0, "wanted": 0}
    assert d["torbox"] == {"state": "ok", "label": "TorBox online"}


def test_per_user_counts_never_leak_across_users():
    """user_id=None must never see another user's watchlist or requests -
    those counts stay 0 unless a user is identified."""
    user_id = db.create_user("alice", "hash")
    db.add_to_watchlist(user_id, "tt0000001", None, "movie", "Some Movie")
    db.add_to_watchlist(user_id, "tt0000002", None, "movie", "Another Movie")

    d_anonymous = shell_summary.get_shell_summary()
    assert d_anonymous["counts"] == {"watchlist": 0, "requests": 0, "wanted": 0}

    d_user = shell_summary.get_shell_summary(user_id)
    assert d_user["counts"]["watchlist"] == 2
    assert d_user["counts"]["requests"] == 0
