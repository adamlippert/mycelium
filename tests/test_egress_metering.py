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
