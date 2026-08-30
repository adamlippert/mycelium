"""The Requests page shows 'N of M requests, resets in X days'.

limit comes from users.quota_monthly, where 0 has always meant 'no cap';
the endpoint surfaces that as unlimited=true rather than a zero limit the
UI would render as '14 of 0'.
"""
import os
import sys
from datetime import datetime, timezone

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db
import quota


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


def _user(quota_monthly=25):
    uid = db.create_user("adam", "x" * 32, role="user", quota_monthly=quota_monthly)
    return {"id": uid, "quota_monthly": quota_monthly}


def test_shape_for_a_capped_user_with_no_requests():
    d = quota.get_quota(_user(25))
    assert d["used"] == 0
    assert d["limit"] == 25
    assert d["unlimited"] is False


def test_used_counts_only_this_users_rows_this_month():
    u = _user(25)
    other = db.create_user("someone", "y" * 32, role="user")
    db.create_user_request(u["id"], "tt0000001", None, "A", "movie")
    db.create_user_request(u["id"], "tt0000002", None, "B", "movie")
    db.create_user_request(other, "tt0000003", None, "C", "movie")

    assert quota.get_quota(u)["used"] == 2


def test_zero_quota_means_unlimited_not_a_zero_cap():
    d = quota.get_quota(_user(0))
    assert d["unlimited"] is True
    assert d["limit"] == 0


def test_resets_at_is_the_first_of_next_month_utc():
    d = quota.get_quota(_user(25))
    resets = datetime.fromisoformat(d["resets_at"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    assert resets > now
    assert resets.day == 1
    assert resets.hour == 0 and resets.minute == 0
    assert (resets.year, resets.month) in {
        (now.year, now.month % 12 + 1),
        (now.year + 1, 1),
    }


def test_a_userless_session_gets_the_unlimited_shape():
    """Trusted-proxy logins can have no user row. The card hides itself on
    unlimited, which is the right rendering for 'we cannot attribute you'."""
    d = quota.get_quota(None)
    assert d == {"used": 0, "limit": 0, "resets_at": d["resets_at"], "unlimited": True}


def test_the_endpoint_is_registered():
    with open(os.path.join(os.path.dirname(__file__), "..", "app.py"), encoding="utf-8") as f:
        src = f.read()
    assert '@app.get("/ui/api/me/quota")' in src
    assert "quota.get_quota(" in src
