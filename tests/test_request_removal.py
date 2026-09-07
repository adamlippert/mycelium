"""What the two removal buttons leave behind.

Delete forgets the request and keeps the files; Remove from library purges.
Neither cleared the per-user request rows that feed the poster badges, and
purge never told Seerr, so a removed title stayed "Available" there until
Seerr's own sync noticed hours later.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _src(name):
    with open(os.path.join(_ROOT, name), encoding="utf-8") as f:
        return f.read()


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


class FakeResp:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body or {}
        self.text = ""

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


@pytest.fixture
def seerr_env(monkeypatch):
    import seerr
    import settings
    values = {"SEERR_URL": "http://seerr.test", "SEERR_API_KEY": "k", "SEERR_REPORT_STATUS": True}
    monkeypatch.setattr(settings, "get", lambda k, d=None: values.get(k, d))
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(("POST", url, json))
        return FakeResp(200, {"id": 1})

    def fake_get(url, headers=None, timeout=None):
        calls.append(("GET", url, None))
        if "/request/" in url:
            return FakeResp(200, {"id": 42, "status": 2, "media": {"id": 7, "tmdbId": 949}})
        if url.endswith("/movie/949"):
            return FakeResp(200, {"mediaInfo": {"id": 7, "status": 5, "requests": [{"id": 42, "status": 2}]}})
        return FakeResp(200, {"mediaInfo": None})

    def fake_delete(url, headers=None, timeout=None):
        calls.append(("DELETE", url, None))
        return FakeResp(204)

    monkeypatch.setattr(seerr.requests, "post", fake_post)
    monkeypatch.setattr(seerr.requests, "get", fake_get)
    monkeypatch.setattr(seerr.requests, "delete", fake_delete)
    return values, calls


def _user_id():
    with db._connect() as conn:
        conn.execute("INSERT INTO users (username, password_hash, role) VALUES ('u', 'x', 'user')")
        conn.commit()
        return conn.execute("SELECT id FROM users WHERE username='u'").fetchone()["id"]


# -- per-user request rows ------------------------------------------------------

def test_clear_user_requests_removes_every_row_for_the_title():
    uid = _user_id()
    db.create_user_request(uid, "tt0113277", 949, "movie", "Heat", status="approved")
    db.create_user_request(uid, "tt0113277", 949, "movie", "Heat", status="pending")
    db.create_user_request(uid, "tt0078748", 348, "movie", "Alien", status="approved")
    assert db.clear_user_requests("tt0113277") == 2
    left = [r["imdb_id"] for r in db.get_user_requests(user_id=uid)]
    assert left == ["tt0078748"]


def test_delete_button_clears_the_per_user_rows_too():
    """Delete drops the request row; the user_requests row it left behind
    kept feeding the poster badge and the detail-modal button."""
    uid = _user_id()
    row_id = db.insert_request("Heat", "tt0113277", "movie", tmdb_id=949)
    db.create_user_request(uid, "tt0113277", 949, "movie", "Heat", status="pending")
    assert db.delete_request(row_id) is True
    assert db.get_user_requests(user_id=uid) == []


def test_purge_clears_the_per_user_rows_even_without_a_request_row():
    src = _src("cleanup.py")
    body = src.split("def purge_title(", 1)[1]
    assert "db.clear_user_requests(imdb_id)" in body


# -- telling Seerr about a purge -------------------------------------------------

def test_purge_deletes_the_seerr_media_record(seerr_env):
    """Measured against Seerr 3.4.1: the 'deleted' media status is accepted
    and ignored, so a purge removes the record the way Seerr's own "clear
    media data" does; the title is requestable again at once."""
    import seerr_report
    assert seerr_report.on_purged("tt0113277", 949, "movie") is True
    assert seerr_env[1] == [
        ("GET", "http://seerr.test/api/v1/movie/949", None),
        ("DELETE", "http://seerr.test/api/v1/media/7", None),
    ]


def test_purge_falls_back_to_the_request_id_without_a_tmdb(seerr_env):
    import seerr_report
    db.upsert_media_item("tt0113277", "Heat", "movie", seerr_request_id=42)
    assert seerr_report.on_purged("tt0113277") is True
    assert seerr_env[1] == [
        ("GET", "http://seerr.test/api/v1/request/42", None),
        ("DELETE", "http://seerr.test/api/v1/media/7", None),
    ]


def test_purge_of_a_title_seerr_never_saw_is_silent(seerr_env):
    import seerr_report
    assert seerr_report.on_purged("tt0113277") is False
    assert seerr_env[1] == []


def test_purge_reporting_respects_the_switch(seerr_env):
    import seerr_report
    seerr_env[0]["SEERR_REPORT_STATUS"] = False
    db.upsert_media_item("tt0113277", "Heat", "movie", seerr_request_id=42)
    assert seerr_report.on_purged("tt0113277") is False
    assert seerr_env[1] == []


def test_a_seerr_outage_during_purge_never_raises(seerr_env, monkeypatch):
    import seerr
    import seerr_report

    def boom(*a, **k):
        raise ConnectionError("down")

    monkeypatch.setattr(seerr.requests, "get", boom)
    db.upsert_media_item("tt0113277", "Heat", "movie", seerr_request_id=42)
    assert seerr_report.on_purged("tt0113277") is False


def test_purge_title_reports_to_seerr_but_delete_does_not():
    cleanup_src = _src("cleanup.py")
    assert "seerr_report.on_purged(imdb_id, tmdb_id, media_type)" in cleanup_src.split("def purge_title(", 1)[1]
    app_src = _src("app.py")
    delete_route = app_src.split("def ui_api_delete_request(", 1)[1].split("\n@app.", 1)[0]
    assert "seerr_report" not in delete_route, "Delete keeps the files, so Seerr must not be told"


# -- the Delete confirmation says where the files go ----------------------------

def test_delete_confirmations_point_at_remove_from_library():
    for page in ("frontend/src/pages/Requests.tsx", "frontend/src/pages/admin/Requests.tsx"):
        src = _src(page)
        assert "use Remove from library instead" in src, page
