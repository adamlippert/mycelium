"""The repair overview behind the admin Maintenance tab.

Originally these lived in test_admin_refresh.py alongside tests for the
Jinja dashboard's two-minute self-reload fix; the Jinja UI is gone, but the
JSON endpoint it introduced (/ui/api/repair) is what the React Maintenance
tab polls, so the payload and endpoint halves live on here.
"""
import os
import re
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db
import stats

_ROOT = os.path.join(os.path.dirname(__file__), "..")


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


def _app_py():
    with open(os.path.join(_ROOT, "app.py"), encoding="utf-8") as f:
        return f.read()


# ── the payload ───────────────────────────────────────────────────────────────

def test_repair_overview_on_a_fresh_database():
    """Nothing has run yet. The Maintenance tab must be able to render that
    state, so the keys are always present and last_cleanup is explicitly
    None."""
    d = stats.get_repair_overview()
    assert d == {"items": [], "last_cleanup": None}


def test_repair_overview_returns_the_last_run_and_its_items():
    run_id = db.insert_cleanup_run()
    db.update_cleanup_run(run_id, scanned=12, repaired=3, deleted=1, unfixable=2)
    db.insert_repair_item(run_id, "/media/movies/Dune (2021)/Dune (2021).strm",
                          "Dune", "movie", "old-1", "a" * 40, "repaired", None)

    d = stats.get_repair_overview()

    assert d["last_cleanup"]["scanned"] == 12
    assert d["last_cleanup"]["repaired"] == 3
    assert d["last_cleanup"]["unfixable"] == 2
    assert [i["title"] for i in d["items"]] == ["Dune"]


def test_repair_overview_returns_only_the_most_recent_run():
    """The summary block shows one run. A second run must replace the first,
    not sit behind it."""
    first = db.insert_cleanup_run()
    db.update_cleanup_run(first, scanned=1, repaired=0, deleted=0, unfixable=0)
    second = db.insert_cleanup_run()
    db.update_cleanup_run(second, scanned=99, repaired=0, deleted=0, unfixable=0)

    assert stats.get_repair_overview()["last_cleanup"]["scanned"] == 99


def test_repair_overview_honours_the_limit():
    run_id = db.insert_cleanup_run()
    for n in range(5):
        db.insert_repair_item(run_id, f"/media/movies/M{n}/M{n}.strm",
                              f"M{n}", "movie", None, None, "repaired", None)

    assert len(stats.get_repair_overview(limit=2)["items"]) == 2


# ── the endpoint ──────────────────────────────────────────────────────────────

def test_the_repair_endpoint_is_registered():
    assert re.search(r'@app\.get\(["\']/ui/api/repair["\']\)', _app_py())


def test_the_repair_endpoint_is_admin_only():
    """Repair items carry filesystem paths. The Maintenance tab is admin
    gated; the endpoint behind it must be too, or the gate is decorative."""
    src = _app_py()
    m = re.search(r'@app\.get\(["\']/ui/api/repair["\']\)(.{0,400})', src, re.S)
    assert m, "no /ui/api/repair route"
    assert "auth.is_admin()" in m.group(1)
    assert "403" in m.group(1)
