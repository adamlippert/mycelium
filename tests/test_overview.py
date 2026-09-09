"""Aggregated Overview payload (overview.py) and its helpers."""
import os
import re
import time

import pytest

import db
import egress_estimate
import overview
import torbox

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
    egress_estimate._reset()
    overview._cache["data"] = None
    yield
    _drop_cached_conn()


def _src(name):
    return open(os.path.join(_ROOT, name), encoding="utf-8").read()


def _egress(token, estimated, created_at):
    with db._connect() as conn:
        conn.execute("INSERT INTO egress_log (token, bytes, estimated, created_at) VALUES (?, 10, ?, ?)",
                     (token, 1 if estimated else 0, created_at))
        conn.commit()


def test_play_counts_follow_the_documented_rule():
    today = time.strftime("%Y-%m-%d", time.gmtime())
    two_days = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 2 * 86400))
    # Three MKV plays of one title today: three plays.
    for h in ("01", "02", "03"):
        _egress("tokA", True, f"{today} 10:{h}:00")
    # Four proxied range rows for another title, two days: two plays.
    _egress("tokB", False, f"{today} 11:00:00")
    _egress("tokB", False, f"{today} 11:01:00")
    _egress("tokB", False, f"{two_days} 09:00:00")
    _egress("tokB", False, f"{two_days} 09:05:00")
    assert db.play_counts(0) == {"plays": 4, "titles": 2}
    assert db.play_counts(7) == {"plays": 5, "titles": 2}


def test_play_counts_on_an_empty_log_are_zero():
    assert db.play_counts(0) == {"plays": 0, "titles": 0}


def test_mirrored_requests_are_counted_over_success_rows():
    a = db.insert_request("A", "tt1", "movie")
    b = db.insert_request("B", "tt2", "movie")
    db.insert_request("C", "tt3", "movie")  # stays pending
    db.update_request(a, "success")
    db.update_request(b, "success")
    with db._connect() as conn:
        conn.execute("UPDATE requests SET arr_mirrored_at = '2026-09-01 00:00:00' WHERE id = ?", (a,))
        conn.commit()
    assert db.count_requests_mirrored() == (1, 2)


def test_oldest_pending_approval_age():
    assert db.oldest_pending_user_request_age_sec() is None
    uid = db.create_user("anna", "pw", role="user")
    rid = db.create_user_request(uid, "tt1", 1, "movie", "A", None)
    with db._connect() as conn:
        conn.execute("UPDATE user_requests SET created_at = datetime('now', '-3 hours') WHERE id = ?", (rid,))
        conn.commit()
    age = db.oldest_pending_user_request_age_sec()
    assert 3 * 3600 - 60 <= age <= 3 * 3600 + 60
    db.update_user_request_status(rid, "approved")
    assert db.oldest_pending_user_request_age_sec() is None


def test_recent_streams_counts_tokens_seen_inside_the_window(monkeypatch):
    monkeypatch.setattr(egress_estimate, "_now", lambda: 1000.0)
    egress_estimate.note_redirect("a", 1)
    egress_estimate.note_redirect("b", 1)
    monkeypatch.setattr(egress_estimate, "_now", lambda: 1000.0 + 20 * 60)
    egress_estimate.note_redirect("c", 1)
    assert egress_estimate.recent(900) == 1
    assert egress_estimate.recent(30 * 60) == 3


def test_last_429_is_recorded_by_add_magnet(monkeypatch):
    class _Resp:
        status_code = 429
        headers = {"Retry-After": "5"}

    monkeypatch.setattr(torbox, "_last_429_at", None)
    monkeypatch.setattr(torbox, "_CREATETORRENT_LIMIT_MIN", 10_000)
    monkeypatch.setattr(torbox, "_headers", lambda: {})
    monkeypatch.setattr(torbox, "_base_url", lambda: "http://torbox.test")
    monkeypatch.setattr(torbox.requests, "post", lambda *a, **k: _Resp())
    assert torbox.last_429_at() is None
    with pytest.raises(torbox.RateLimited):
        torbox.add_magnet("magnet:?xt=urn:btih:" + "a" * 40, reason="test")
    assert torbox.last_429_at() is not None and time.time() - torbox.last_429_at() < 5


def test_build_has_the_documented_shape(monkeypatch):
    import library_sync
    import scrapers
    monkeypatch.setattr(scrapers, "health_rows", lambda: [
        {"name": "torrentio", "state": "ok", "latency_ms": 640.0, "samples": 3},
        {"name": "comet", "state": "down", "latency_ms": None, "samples": 0}])
    monkeypatch.setattr(torbox, "createtorrent_usage", lambda window_sec=3600: {
        "count": 3, "cached_count": 41, "limit": 60, "resets_in_sec": 2520, "by_reason": {"processor": 3}})
    monkeypatch.setattr(library_sync, "orphans", lambda: {
        "strm_count": 300, "db_count": 295, "strm_without_db": 5, "db_without_strm": 0})
    monkeypatch.setattr(torbox, "_last_429_at", None)
    rid = db.insert_request("Heat", "tt1", "movie")
    db.update_request(rid, "success", quality="1080p")
    out = overview.build()
    s = out["status"]
    assert s["scrapers"] == [{"name": "torrentio", "state": "ok", "latency_ms": 640.0},
                             {"name": "comet", "state": "down", "latency_ms": None}]
    assert s["torbox_adds"] == {"uncached": 3, "cached": 41, "limit": 60, "resets_in_sec": 2520}
    assert s["failures_7d"] == 0 and s["queue"] == {"retry": 0, "wanted": 0}
    assert s["attention"] == 0 and s["approvals"] == {"pending": 0, "oldest_age_sec": None}
    a = out["activity"]
    assert a["plays"] == {"today": 0, "week": 0, "titles_today": 0, "titles_week": 0}
    assert a["requests_7d"] == {"total": 1, "succeeded": 1, "failed": 0, "success_rate": 100.0}
    assert a["egress"] == {"proxied_bytes": 0, "estimated_bytes": 0}
    lib = out["library"]
    assert set(lib) >= {"movies", "episodes", "series", "wanted", "upcoming", "qualities", "consistency"}
    assert lib["qualities"] == {"1080p": 1}
    assert lib["consistency"] == {"db_items": 295, "strm_without_db": 5, "db_without_strm": 0,
                                  "arr_mirrored": 0, "arr_total": 1, "last_cleanup": None}
    assert out["torbox"] == {"recent_streams": 0, "last_429_at": None}


def test_build_survives_a_failing_source(monkeypatch):
    import scrapers
    monkeypatch.setattr(scrapers, "health_rows", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    out = overview.build()
    assert out["status"]["scrapers"] == []


def test_build_survives_stats_build_overview_failing(monkeypatch):
    import stats
    monkeypatch.setattr(stats, "_build_overview", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    out = overview.build()
    s = out["status"]
    assert s["failures_7d"] == 0 and s["queue"] == {"retry": 0, "wanted": 0}
    a = out["activity"]
    assert a["requests_7d"] == {"total": 0, "succeeded": 0, "failed": 0, "success_rate": 0.0}
    assert a["egress"] == {"proxied_bytes": 0, "estimated_bytes": 0}
    lib = out["library"]
    assert lib["movies"] == 0 and lib["episodes"] == 0 and lib["series"] == 0
    assert lib["wanted"] == 0 and lib["upcoming"] == 0 and lib["qualities"] == {}
    assert "consistency" in lib


def test_consistency_reports_the_last_cleanup_run():
    run_id = db.insert_cleanup_run()
    db.update_cleanup_run(run_id, scanned=10, repaired=2, deleted=3, unfixable=0)
    out = overview._consistency()
    assert out["last_cleanup"] == {"ran_at": db.get_last_cleanup_run()["ran_at"], "deleted": 3}


def test_get_caches_for_the_ttl(monkeypatch):
    calls = []
    monkeypatch.setattr(overview, "build", lambda: calls.append(1) or {"x": len(calls)})
    overview.get()
    overview.get()
    assert len(calls) == 1
    overview.get(force=True)
    assert len(calls) == 2


def test_route_is_admin_only_and_served_from_the_cache():
    src = _src("app.py")
    m = re.search(r'@app\.get\("/ui/api/overview"\)\s*\ndef (\w+)\(\):(.*?)\n\n', src, re.S)
    assert m and "auth.is_admin()" in m.group(2) and "overview.get()" in m.group(2)
