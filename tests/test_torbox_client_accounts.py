"""torbox.py builds every header from the account it is given, keeps its
mylist cache and 429 marks per account, records the account on the budget
log, and never builds a header without an account."""
import os
import re
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import torbox  # noqa: E402
import db  # noqa: E402
import settings  # noqa: E402
import torbox_pool as pool  # noqa: E402

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
    monkeypatch.setenv("TORBOX_API_KEY", "k1")
    _drop_cached_conn()
    db.init()
    settings.set("TORBOX_API_KEY", "k1")
    db.insert_torbox_account("second", "k2")
    pool.invalidate()
    pool._health.clear()
    torbox.invalidate_mylist_cache()
    torbox._last_429.clear()
    yield
    _drop_cached_conn()


class Resp:
    def __init__(self, code=200, body=None, headers=None):
        self.status_code = code
        self._body = body if body is not None else {"success": True, "data": []}
        self.headers = headers or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))


def test_headers_carry_the_given_accounts_key():
    assert torbox._headers(1) == {"Authorization": "Bearer k1"}
    assert torbox._headers(2) == {"Authorization": "Bearer k2"}
    with pytest.raises(RuntimeError):
        torbox._headers(9)


def test_mylist_cache_is_per_account(monkeypatch):
    seen = []

    def fake_get(url, headers=None, timeout=None, params=None):
        seen.append(headers["Authorization"])
        acct = headers["Authorization"][-2:]
        return Resp(body={"data": [{"id": 1 if acct == "k1" else 2, "hash": "h" * 40}]})
    monkeypatch.setattr(torbox.requests, "get", fake_get)
    assert [t["id"] for t in torbox.list_torrents(1)] == [1]
    assert [t["id"] for t in torbox.list_torrents(2)] == [2]
    assert [t["id"] for t in torbox.list_torrents(1)] == [1], "served from account 1's cache"
    assert seen == ["Bearer k1", "Bearer k2"]
    torbox.invalidate_mylist_cache(2)
    torbox.list_torrents(1); torbox.list_torrents(2)
    assert seen == ["Bearer k1", "Bearer k2", "Bearer k2"]
    assert torbox.find_by_hash(2, "H" * 40)["id"] == 2 and torbox.find_by_hash(1, "x" * 40) is None


def test_add_magnet_records_the_account_and_marks_a_429_on_it_only(monkeypatch):
    calls = []

    def fake_post(url, headers=None, data=None, json=None, timeout=None):
        calls.append(headers["Authorization"])
        if headers["Authorization"].endswith("k2"):
            return Resp(429, headers={"Retry-After": "30"})
        return Resp(body={"success": True, "detail": "Found cached torrent", "data": {"torrent_id": 77}})
    monkeypatch.setattr(torbox.requests, "post", fake_post)
    monkeypatch.setattr(torbox.requests, "get", lambda *a, **k: Resp(body={"data": []}))
    out = torbox.add_magnet(1, "magnet:?xt=urn:btih:" + "a" * 40, reason="t")
    assert out["id"] == 77
    assert db.get_createtorrent_log(0.0, account_id=1)[0][3] == 1
    with pytest.raises(torbox.RateLimited):
        torbox.add_magnet(2, "magnet:?xt=urn:btih:" + "b" * 40, reason="t")
    assert torbox.last_429_at(2) is not None and torbox.last_429_at(1) is None
    assert torbox.last_429_at() == torbox.last_429_at(2)
    assert pool.health(2)["rate_limited_until"] is not None and pool.health(1)["rate_limited_until"] is None
    assert db.get_createtorrent_log(0.0, account_id=2) == [], "a refused add gives its slot back"
    assert calls == ["Bearer k1", "Bearer k2"]


def test_an_auth_failure_raises_and_marks_the_account(monkeypatch):
    monkeypatch.setattr(torbox.requests, "get", lambda *a, **k: Resp(403, body={"data": None}))
    with pytest.raises(torbox.AuthFailed):
        torbox.list_torrents(2, force_refresh=True)
    assert pool.health(2)["auth_failed_at"] is not None and pool.health(1)["auth_failed_at"] is None
    with pytest.raises(torbox.AuthFailed):
        torbox.find_by_id(2, 5)
    assert torbox.delete_torrent(2, 5) is False


def test_createtorrent_usage_sums_accounts_when_none_is_given():
    now = time.time()
    db.reserve_createtorrent_slot(now, "a", 60, 10, account_id=1)
    db.reserve_createtorrent_slot(now, "b", 60, 10, account_id=2)
    db.reserve_createtorrent_slot(now, "b", 60, 10, account_id=2)
    assert torbox.createtorrent_usage(1)["count"] == 1
    assert torbox.createtorrent_usage(2)["by_reason"] == {"b": 2}
    assert torbox.createtorrent_usage()["count"] == 3


def test_reserve_createtorrent_slot_logs_under_the_given_account():
    entry = torbox._reserve_createtorrent_slot(2, "t")
    logged = db.get_createtorrent_log(0.0, account_id=2)
    assert len(logged) == 1 and logged[0][1:] == ("t", False, 2)
    assert db.get_createtorrent_log(0.0, account_id=1) == []
    torbox._release_createtorrent_slot(entry)


def test_request_download_link_uses_the_accounts_key(monkeypatch):
    seen = {}

    def fake_get(url, params=None, timeout=None, headers=None):
        seen.update(params or {})
        return Resp(body={"data": "https://cdn/x"})
    monkeypatch.setattr(torbox.requests, "get", fake_get)
    assert torbox.request_download_link(2, 77, 0) == "https://cdn/x"
    assert seen["token"] == "k2" and seen["torrent_id"] == 77 and seen["file_id"] == 0


def test_request_download_link_never_logs_the_key_on_failure(monkeypatch, caplog):
    """Important 3: a non-auth failure here used to str(exc) a requests
    exception, and requests exceptions stringify with the full request URL
    -  which carries the API key in `token=`. The log must name the
    exception type (and status code, when there is one) instead."""
    import requests as _requests

    def boom(url, params=None, timeout=None):
        raise _requests.ConnectionError(
            f"https://api.torbox.app/v1/api/torrents/requestdl?token={params['token']}&torrent_id=1")
    monkeypatch.setattr(torbox.requests, "get", boom)
    import logging
    with caplog.at_level(logging.WARNING):
        result = torbox.request_download_link(2, 77, 0)
    assert result is None
    assert "k2" not in caplog.text
    assert "ConnectionError" in caplog.text


def test_cache_checks_use_any_enabled_key(monkeypatch):
    seen = []
    monkeypatch.setattr(torbox.requests, "get", lambda url, headers=None, params=None, timeout=None: (seen.append(headers["Authorization"]), Resp(body={"data": {}}))[1])
    torbox.check_cached(["a" * 40])
    db.update_torbox_account(1, enabled=False)
    pool.invalidate()
    torbox.check_cached_files(["a" * 40])
    assert seen == ["Bearer k1", "Bearer k2"]


def test_no_header_is_built_without_an_account():
    src = open(os.path.join(_ROOT, "torbox.py")).read()
    bearer_lines = [l for l in src.splitlines() if "Bearer" in l]
    assert len(bearer_lines) == 1 and "def _headers(account_id" in src.split("Bearer")[0][-400:]
    for path in ("strm_generator.py", "health.py", "plugins/webplayer/web_player.py", "cleanup.py"):
        body = open(os.path.join(_ROOT, path)).read()
        assert "TORBOX_API_KEY" not in body and "requestdl" not in body.replace("request_download_link", ""), path
    assert not re.search(r"def _get_stream_url", src + open(os.path.join(_ROOT, "strm_generator.py")).read())


def test_check_quota_and_warn_skips_an_account_whose_usage_check_fails(monkeypatch):
    """A revoked key on one account must not stop the quota check from
    reaching the healthy accounts after it."""
    checked = []

    def fake_usage(account_id):
        if account_id == 1:
            raise torbox.AuthFailed("account 1: 403")
        checked.append(account_id)
        return {"torrent_count": 1, "total_gb": 1.0, "states": {}}

    monkeypatch.setattr(torbox, "get_usage_summary", fake_usage)
    torbox.check_quota_and_warn()
    assert checked == [2], "account 1's auth failure must not stop account 2 from being checked"


def test_materialize_locked_catches_auth_failed_from_the_homed_lookups():
    """A revoked key must degrade play to the existing 403/cooldown path
    (catbox.py's old behaviour) instead of unwinding out of the play path
    as an unhandled 500."""
    src = open(os.path.join(_ROOT, "catbox.py")).read()
    body = src.split("def _materialize_locked(")[1].split("\ndef _metrics_inc(")[0]
    assert body.count("except torbox.AuthFailed:") >= 3
    assert "_auth_failed(token" in body
