"""TorBox enforces monthly bandwidth floors with a three-warning then
permanent-ban policy that includes API key revocation. Mycelium proxies the
bytes, so it can measure egress exactly; without this the only
account-ending risk in the system is invisible.
"""
import os
import re
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db

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


def test_recorded_bytes_accumulate():
    db.record_egress("a" * 16, 1_000)
    db.record_egress("b" * 16, 2_500)

    assert db.egress_this_month() == 3_500


def test_a_fresh_database_reports_zero():
    assert db.egress_this_month() == 0


def test_zero_and_negative_counts_are_ignored():
    """A client that hangs up before any byte, or a malformed report, must
    not create rows or skew the total."""
    db.record_egress("a" * 16, 0)
    db.record_egress("a" * 16, -5)

    assert db.egress_this_month() == 0


def test_last_month_is_excluded():
    db.record_egress("a" * 16, 900)
    with db._connect() as conn:
        conn.execute("UPDATE egress_log SET created_at = datetime('now', '-45 days')")
        conn.commit()

    assert db.egress_this_month() == 0


def test_the_report_endpoint_is_loopback_only():
    src = open(os.path.join(_ROOT, "app.py"), encoding="utf-8").read()
    m = re.search(r'@app\.post\(["\']/internal/stream-report/<token>["\']\)(.{0,600})',
                  src, re.S)
    assert m, "no /internal/stream-report route"
    body = m.group(1)
    assert '"127.0.0.1"' in body, "the report endpoint is not loopback gated"
    assert "403" in body


def test_the_go_front_reports_bytes():
    src = open(os.path.join(_ROOT, "spore-stream", "stream.go"), encoding="utf-8").read()
    assert "/internal/stream-report/" in src, "the front never reports what it sent"


# -- estimated egress for the MKV redirect path ------------------------------

def test_estimated_rows_are_summed_apart_from_proxied_rows():
    db.record_egress("tok", 1_000)
    db.record_egress_estimate("tok", 5_000)
    db.record_egress_estimate("tok", 0)
    assert db.egress_this_month() == 1_000
    assert db.egress_estimated_this_month() == 5_000


def test_an_existing_egress_log_gains_the_estimated_column():
    import sqlite3
    _drop_cached_conn()
    with sqlite3.connect(db.DB_PATH) as conn:
        conn.execute("DROP TABLE egress_log")
        conn.execute("CREATE TABLE egress_log (id INTEGER PRIMARY KEY AUTOINCREMENT, token TEXT NOT NULL, "
                     "bytes INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S', 'now')))")
        conn.execute("INSERT INTO egress_log (token, bytes) VALUES ('old', 700)")
        conn.commit()
    db.init()
    assert db.egress_this_month() == 700, "pre-migration rows count as proxied"
    assert db.egress_estimated_this_month() == 0


def test_a_redirect_counts_the_file_once_per_play():
    import egress_estimate as ee
    ee._reset()
    assert ee.note_redirect("tok", 4_000, now=100.0) is True
    assert ee.note_redirect("tok", 4_000, now=100.0 + ee.PLAY_GAP_SEC - 1) is False, "same play"
    assert ee.note_redirect("tok", 4_000, now=100.0 + ee.PLAY_GAP_SEC - 1 + 30) is False, "gap measures the last request"
    assert db.egress_estimated_this_month() == 4_000
    assert ee.note_redirect("tok", 4_000, now=100.0 + 3 * ee.PLAY_GAP_SEC) is True, "a new play after the gap"
    assert db.egress_estimated_this_month() == 8_000


def test_a_redirect_with_an_unknown_size_writes_nothing_but_marks_the_play():
    import egress_estimate as ee
    ee._reset()
    assert ee.note_redirect("tok", 0, now=50.0) is False
    assert ee.note_redirect("tok", 9_000, now=60.0) is False, "still the same play"
    assert db.egress_estimated_this_month() == 0


def test_stale_tokens_are_pruned_from_the_play_map():
    import egress_estimate as ee
    ee._reset()
    ee.note_redirect("a", 1, now=0.0)
    ee.note_redirect("b", 1, now=10.0)
    ee.note_redirect("c", 1, now=10.0 + 2 * ee.PLAY_GAP_SEC)
    assert set(ee._last_seen) == {"c"}


def test_the_redirect_branch_records_an_estimate_and_stats_reports_it():
    src = open(os.path.join(_ROOT, "app.py"), encoding="utf-8").read()
    branch = src.split('return {"mode": "redirect", "url": cdn_url}', 1)[0][-600:]
    assert 'egress_estimate.note_redirect(token, info["cdn_size"])' in branch
    stats = open(os.path.join(_ROOT, "stats.py"), encoding="utf-8").read()
    assert '"egress_estimated_bytes_month": db.egress_estimated_this_month()' in stats
