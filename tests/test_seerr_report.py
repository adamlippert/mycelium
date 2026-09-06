"""Seerr shows "Processing" until something tells it otherwise. Mycelium
knew the outcome and kept it to itself.
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
    values = {"SEERR_URL": "http://seerr.test", "SEERR_API_KEY": "k",
              "SEERR_REPORT_STATUS": True, "SEERR_DECLINE_WANTED_AFTER_DAYS": 30}
    monkeypatch.setattr(settings, "get", lambda k, d=None: values.get(k, d))
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(("POST", url, json))
        return FakeResp(200, {"id": 1})

    def fake_get(url, headers=None, timeout=None):
        calls.append(("GET", url, None))
        return FakeResp(200, {"id": 42, "status": 2, "media": {"id": 7, "tmdbId": 949}})

    monkeypatch.setattr(seerr.requests, "post", fake_post)
    monkeypatch.setattr(seerr.requests, "get", fake_get)
    return values, calls


# -- db ----------------------------------------------------------------------

def test_seerr_request_id_round_trips_through_media_items():
    db.upsert_media_item("tt0113277", "Heat", "movie", seerr_request_id=42)
    assert db.get_seerr_request_id("tt0113277") == 42
    assert db.get_seerr_request_id("tt0000000") is None


def test_stale_wanted_movies_are_listed_once():
    db.upsert_wanted_movie("tt0113277", 949, "Heat", "nothing acceptable")
    with db._connect() as conn:
        conn.execute("UPDATE wanted_movies SET added_at = datetime('now', '-40 days')")
        conn.commit()
    db.upsert_wanted_movie("tt0078748", 348, "Alien", "nothing acceptable")
    stale = db.get_stale_wanted_movies(30)
    assert [r["imdb_id"] for r in stale] == ["tt0113277"]
    db.mark_wanted_seerr_reported("tt0113277")
    assert db.get_stale_wanted_movies(30) == []


# -- seerr client ------------------------------------------------------------

def test_decline_posts_to_the_status_endpoint(seerr_env):
    import seerr
    assert seerr.decline_request(42) is True
    assert seerr_env[1] == [("POST", "http://seerr.test/api/v1/request/42/decline", None)]


def test_set_media_status_resolves_the_media_id_first(seerr_env):
    import seerr
    assert seerr.set_media_status(42, "available") is True
    assert seerr_env[1] == [
        ("GET", "http://seerr.test/api/v1/request/42", None),
        ("POST", "http://seerr.test/api/v1/media/7/available", {"is4k": False}),
    ]


def test_set_media_status_rejects_unknown_states(seerr_env):
    import seerr
    with pytest.raises(ValueError):
        seerr.set_media_status(42, "failed")


# -- reporter ----------------------------------------------------------------

def test_success_marks_available(seerr_env):
    import seerr_report
    db.upsert_media_item("tt0113277", "Heat", "movie", seerr_request_id=42)
    assert seerr_report.on_success("tt0113277") is True
    assert seerr_env[1][-1][1] == "http://seerr.test/api/v1/media/7/available"


def test_failed_declines(seerr_env):
    import seerr_report
    db.upsert_media_item("tt0113277", "Heat", "movie", seerr_request_id=42)
    assert seerr_report.on_failed("tt0113277", "no suitable stream found") is True
    assert seerr_env[1] == [("POST", "http://seerr.test/api/v1/request/42/decline", None)]


def test_failed_decline_clears_the_webhook_dedup_key(seerr_env):
    """Seerr has no un-decline, but a decline should not leave the 24h dedup
    key behind either, or a later re-request for the same title is silently
    swallowed as a duplicate until the key expires on its own."""
    import seerr_report
    db.upsert_media_item("tt0113277", "Heat", "movie", seerr_request_id=42)
    key = "tt0113277:movie:"
    assert db.webhook_seen(key) is False
    assert db.webhook_seen(key) is True
    assert seerr_report.on_failed("tt0113277", "no suitable stream found") is True
    assert db.webhook_seen(key) is False


def test_titles_without_a_seerr_request_are_skipped(seerr_env):
    import seerr_report
    assert seerr_report.on_success("tt0113277") is False
    assert seerr_report.on_failed("tt0113277", "x") is False
    assert seerr_env[1] == []


def test_reporting_can_be_switched_off(seerr_env):
    import seerr_report
    seerr_env[0]["SEERR_REPORT_STATUS"] = False
    db.upsert_media_item("tt0113277", "Heat", "movie", seerr_request_id=42)
    assert seerr_report.on_failed("tt0113277", "x") is False
    assert seerr_env[1] == []


def test_stale_wanted_is_declined_once(seerr_env):
    import seerr_report
    db.upsert_media_item("tt0113277", "Heat", "movie", seerr_request_id=42)
    db.upsert_wanted_movie("tt0113277", 949, "Heat", "nothing acceptable")
    with db._connect() as conn:
        conn.execute("UPDATE wanted_movies SET added_at = datetime('now', '-40 days')")
        conn.commit()
    assert seerr_report.report_stale_wanted() == 1
    assert seerr_report.report_stale_wanted() == 0
    assert seerr_env[1] == [("POST", "http://seerr.test/api/v1/request/42/decline", None)]
    assert db.get_wanted_movies()[0]["imdb_id"] == "tt0113277", "Mycelium keeps searching"


def test_a_seerr_outage_leaves_the_stale_decline_for_the_next_sweep(seerr_env, monkeypatch):
    import seerr
    import seerr_report
    db.upsert_media_item("tt0113277", "Heat", "movie", seerr_request_id=42)
    db.upsert_wanted_movie("tt0113277", 949, "Heat", "nothing acceptable")
    with db._connect() as conn:
        conn.execute("UPDATE wanted_movies SET added_at = datetime('now', '-40 days')")
        conn.commit()

    def boom(*a, **k):
        raise ConnectionError("down")

    monkeypatch.setattr(seerr.requests, "post", boom)
    assert seerr_report.report_stale_wanted() == 0

    def fake_post(url, headers=None, json=None, timeout=None):
        seerr_env[1].append(("POST", url, json))
        return FakeResp(200, {"id": 1})

    monkeypatch.setattr(seerr.requests, "post", fake_post)
    assert seerr_report.report_stale_wanted() == 1


def test_stale_wanted_without_a_seerr_id_is_marked_and_not_rescanned(seerr_env):
    import seerr_report
    db.upsert_wanted_movie("tt0113277", 949, "Heat", "nothing acceptable")
    with db._connect() as conn:
        conn.execute("UPDATE wanted_movies SET added_at = datetime('now', '-40 days')")
        conn.commit()
    assert seerr_report.report_stale_wanted() == 0
    assert db.get_stale_wanted_movies(30) == []


def test_stale_wanted_is_off_at_zero_days(seerr_env):
    import seerr_report
    seerr_env[0]["SEERR_DECLINE_WANTED_AFTER_DAYS"] = 0
    db.upsert_media_item("tt0113277", "Heat", "movie", seerr_request_id=42)
    db.upsert_wanted_movie("tt0113277", 949, "Heat", "x")
    with db._connect() as conn:
        conn.execute("UPDATE wanted_movies SET added_at = datetime('now', '-400 days')")
        conn.commit()
    assert seerr_report.report_stale_wanted() == 0


def test_a_seerr_outage_never_raises(seerr_env, monkeypatch):
    import seerr
    import seerr_report

    def boom(*a, **k):
        raise ConnectionError("down")

    monkeypatch.setattr(seerr.requests, "post", boom)
    monkeypatch.setattr(seerr.requests, "get", boom)
    db.upsert_media_item("tt0113277", "Heat", "movie", seerr_request_id=42)
    assert seerr_report.on_success("tt0113277") is False
    assert seerr_report.on_failed("tt0113277", "x") is False


# -- wiring ------------------------------------------------------------------

def test_media_request_carries_the_seerr_request_id():
    from webhook_parser import MediaRequest
    req = MediaRequest(title="Heat", media_type="movie", imdb_id="tt0113277")
    assert req.seerr_request_id is None
    src = _src("webhook_parser.py")
    assert "seerr_request_id=" in src.split("def parse(", 1)[1]


def test_failed_is_reported_only_when_no_retry_remains():
    """Seerr has no un-decline: on_failed must run only once retry_queue.schedule
    says no further attempt will fire, or a later successful retry leaves the
    request declined forever."""
    src = _src("processor.py")
    locked = src.split("def _process_locked(", 1)[1]
    failed = locked.split('db.update_request(row_id, "failed", error=reason)', 1)[1][:1100]
    assert "will_retry = retry_queue.schedule(req, _retry_attempt)" in failed
    assert "if not will_retry:" in failed
    assert failed.index("retry_queue.schedule(req, _retry_attempt)") < \
        failed.index("seerr_report.on_failed(req.imdb_id, reason)")


def test_processor_persists_the_id_and_reports_both_outcomes():
    src = _src("processor.py")
    locked = src.split("def _process_locked(", 1)[1]
    assert "seerr_request_id=req.seerr_request_id" in locked.split("db.insert_request(", 1)[1][:600]
    success = locked.split("jellyfin.refresh_library()", 1)[1][:1500]
    assert "seerr_report.on_success(req.imdb_id)" in success
    failed = locked.split('db.update_request(row_id, "failed", error=reason)', 1)[1][:1100]
    assert "seerr_report.on_failed(req.imdb_id, reason)" in failed


def test_wanted_job_reports_success_and_sweeps_stale():
    src = _src("upgrader.py")
    block = src.split("db.remove_wanted_movie(w[\"imdb_id\"])", 1)[1][:800]
    assert "seerr_report.on_success(w[\"imdb_id\"])" in block
    assert "seerr_report.report_stale_wanted()" in src


def test_settings_are_registered():
    src = _src("settings.py")
    assert '"SEERR_REPORT_STATUS"' in src.split("_BOOL_KEYS = {", 1)[1].split("}", 1)[0]
    assert '"SEERR_DECLINE_WANTED_AFTER_DAYS"' in src.split("_INT_KEYS = {", 1)[1].split("}", 1)[0]
    env = _src(".env.example")
    assert "\nSEERR_REPORT_STATUS=" in env and "\nSEERR_DECLINE_WANTED_AFTER_DAYS=" in env
