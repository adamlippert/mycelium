"""Important 2, the web player: _find_in_any_account checks every enabled
account (delegating to torbox_pool.find_hash_anywhere), and _get_cdn_url
uses the account the hit was found on instead of choosing a fresh one and
missing the existing copy."""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db
import torbox_pool as pool
import plugins.webplayer.web_player as wp

# web_player.py does a plain `import torbox`; alias to that exact object so
# monkeypatching here reaches every call it (and torbox_pool.py's own lazy
# `import torbox`) makes.
torbox = wp.torbox


def _db_modules():
    mods = []
    for m in (db, pool.db):
        if not any(m is x for x in mods):
            mods.append(m)
    return mods


def _drop_cached_conn():
    for m in _db_modules():
        conn = getattr(m._tls, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            m._tls.conn = None


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    _drop_cached_conn()
    for m in _db_modules():
        monkeypatch.setattr(m, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("TORBOX_API_KEY", "k1")
    _drop_cached_conn()
    db.init()
    db.insert_torbox_account("second", "k2")
    pool.invalidate()
    pool._health.clear()
    yield
    _drop_cached_conn()


_H = "b" * 40


def test_find_in_any_account_checks_every_enabled_account(monkeypatch):
    calls = []

    def fake_find_by_hash(account_id, info_hash, **k):
        calls.append(account_id)
        return {"id": 5, "files": []} if account_id == 2 else None

    monkeypatch.setattr(torbox, "find_by_hash", fake_find_by_hash)
    hit = wp._find_in_any_account(_H)
    assert hit == (2, {"id": 5, "files": []})
    assert calls == [1, 2]


def test_get_cdn_url_uses_the_hit_account_instead_of_choosing_again(monkeypatch):
    def _no_choose():
        raise AssertionError("must not choose a fresh account when a hit is given")
    monkeypatch.setattr(pool, "choose_for_add", _no_choose)

    item = {"id": 42, "files": [{"id": 0, "name": "Movie.mkv", "size": 100}]}
    monkeypatch.setattr(torbox, "_is_ready", lambda i: True)
    calls = []
    monkeypatch.setattr(torbox, "request_download_link",
                        lambda account_id, torrent_id, file_id, **k: calls.append(account_id) or "https://cdn/x")

    stream = SimpleNamespace(info_hash=_H, magnet=f"magnet:?xt=urn:btih:{_H}")
    url, torrent_id, file_id = wp._get_cdn_url(stream, hit=(2, item))

    assert url == "https://cdn/x"
    assert torrent_id == 42 and file_id == 0
    assert calls == [2], "the download link must be requested on the account the hit came from"


def test_get_cdn_url_with_no_hit_still_chooses_and_adds(monkeypatch):
    monkeypatch.setattr(pool, "choose_for_add", lambda: pool.account(1))
    calls = []

    def fake_find_by_hash(account_id, info_hash, **k):
        calls.append(("find_by_hash", account_id))
        return None

    def fake_add_magnet(account_id, magnet, **k):
        calls.append(("add_magnet", account_id))
        return {"id": 7}

    def fake_wait_until_ready(account_id, info_hash, **k):
        calls.append(("wait_until_ready", account_id))
        return {"id": 7, "files": [{"id": 0, "name": "Movie.mkv", "size": 100}]}

    monkeypatch.setattr(torbox, "find_by_hash", fake_find_by_hash)
    monkeypatch.setattr(torbox, "add_magnet", fake_add_magnet)
    monkeypatch.setattr(torbox, "wait_until_ready", fake_wait_until_ready)
    monkeypatch.setattr(torbox, "request_download_link", lambda *a, **k: "https://cdn/y")

    stream = SimpleNamespace(info_hash=_H, magnet=f"magnet:?xt=urn:btih:{_H}")
    url, torrent_id, file_id = wp._get_cdn_url(stream)

    assert url == "https://cdn/y"
    assert ("find_by_hash", 1) in calls and ("add_magnet", 1) in calls and ("wait_until_ready", 1) in calls
