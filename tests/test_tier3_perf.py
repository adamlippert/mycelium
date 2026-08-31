"""Tier 3 performance fixes: for when concurrent users actually arrive.

From the 2026-08-31 performance review:
1. The serving thread pool is the hard ceiling on simultaneous open streams
   (each proxied stream holds its thread for the whole transfer). Threads go
   from 16 to 64 (GUNICORN_THREADS overridable); workers stay pinned at 1
   because a documented list of in-process state (single-flight locks, the
   scan-burst detector, the login rate limiter) is only correct in one
   process.
2. The TorBox createtorrent budget is enforced through the database in one
   immediate transaction, so the local 60/hour guard holds across threads
   AND across processes; a future --workers bump cannot multiply it into N
   independent counters that stampede TorBox's real limit.
3. torbox.list_torrents refreshes single-flight: at TTL expiry one caller
   pays the up-to-20-page fetch while concurrent callers wait for its result
   or serve the barely-stale copy, instead of all fetching independently.
4. The admin all-requests table renders one 50-row page instead of mounting
   up to 5,000 <tr> nodes, and the frontend is code-split per route with the
   vendor stack and hls.js in their own long-cached chunks.
"""
import os
import re
import sys
import threading
import time

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

# test_strm_generator.py may leave a MagicMock in sys.modules["torbox"];
# grab the real module the same way test_torbox_ratelimit.py does.
_prior_torbox = sys.modules.get("torbox")
sys.modules.pop("torbox", None)
import torbox  # noqa: E402
if _prior_torbox is not None:
    sys.modules["torbox"] = _prior_torbox
else:
    sys.modules.pop("torbox", None)

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _src(relpath):
    with open(os.path.join(_ROOT, relpath), encoding="utf-8") as f:
        return f.read()


@pytest.fixture(autouse=True)
def _fresh_mylist_cache():
    torbox.invalidate_mylist_cache()
    yield
    torbox.invalidate_mylist_cache()


# -- 1. gunicorn shape --------------------------------------------------------

def test_gunicorn_runs_one_worker_with_more_threads():
    src = _src("Dockerfile")
    assert "--workers 1" in src
    m = re.search(r"--threads \$\{GUNICORN_THREADS:-(\d+)\}", src)
    assert m, "thread count is not env-overridable"
    assert int(m.group(1)) >= 64


def test_the_single_worker_pin_is_documented_at_the_cmd():
    """A future 'add workers for throughput' change must trip over the list
    of in-process state that makes workers>1 incorrect."""
    src = _src("Dockerfile")
    assert "--workers MUST stay 1" in src


def test_the_login_limiter_documents_its_memory_storage():
    src = _src("app.py")
    m = re.search(r"(.{0,500})storage_uri=\"memory://\"", src, re.S)
    assert m and "--workers 1" in m.group(1)


# -- 2. createtorrent budget lives in the database ----------------------------

def test_torbox_no_longer_keeps_an_in_memory_quota_log():
    src = _src("torbox.py")
    assert "_CREATETORRENT_LOG" not in src
    assert "deque" not in src


def test_reserve_and_release_round_trip(tmp_path, monkeypatch):
    import db
    conn = getattr(db._tls, "conn", None)
    if conn is not None:
        conn.close()
        db._tls.conn = None
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "t.db"))
    db._tls.conn = None
    db.init()

    res = db.reserve_createtorrent_slot(time.time(), "play", 60, 10)
    assert res["id"] is not None
    assert res["hour_count"] == 1

    db.release_createtorrent_slot(res["id"])
    assert db.get_createtorrent_log(0) == []

    db._tls.conn.close()
    db._tls.conn = None


def test_reserve_refuses_when_the_hour_budget_is_gone(tmp_path, monkeypatch):
    import db
    conn = getattr(db._tls, "conn", None)
    if conn is not None:
        conn.close()
        db._tls.conn = None
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "t.db"))
    db._tls.conn = None
    db.init()

    now = time.time()
    for _ in range(58):  # limit 60, guard is limit - 2
        assert db.reserve_createtorrent_slot(now, "x", 60, 10_000)["id"] is not None
    blocked = db.reserve_createtorrent_slot(now, "x", 60, 10_000)
    assert blocked["id"] is None
    assert blocked["hour_count"] == 58

    db._tls.conn.close()
    db._tls.conn = None


# -- 3. mylist single-flight --------------------------------------------------

def test_concurrent_expiry_triggers_exactly_one_fetch(monkeypatch):
    calls = {"n": 0}

    def fake_fetch(timeout):
        calls["n"] += 1
        time.sleep(0.05)
        items = [{"id": 1}]
        with torbox._mylist_lock:
            torbox._mylist_cache["items"] = items
            torbox._mylist_cache["ts"] = time.monotonic()
        return items

    monkeypatch.setattr(torbox, "_fetch_mylist", fake_fetch)

    results = []
    threads = [threading.Thread(target=lambda: results.append(torbox.list_torrents()))
               for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert calls["n"] == 1
    assert all(r == [{"id": 1}] for r in results)


def test_stale_copy_is_served_while_a_refresh_is_in_flight(monkeypatch):
    stale = [{"id": 99}]
    with torbox._mylist_lock:
        torbox._mylist_cache["items"] = stale
        torbox._mylist_cache["ts"] = time.monotonic() - 10_000  # long expired

    def must_not_run(timeout):
        raise AssertionError("a second fetch ran during an in-flight refresh")
    monkeypatch.setattr(torbox, "_fetch_mylist", must_not_run)

    assert torbox._mylist_refresh_lock.acquire(blocking=False)
    try:
        assert torbox.list_torrents() == stale
    finally:
        torbox._mylist_refresh_lock.release()


# -- 4. frontend ---------------------------------------------------------------

def test_routes_are_code_split():
    src = _src("frontend/src/App.tsx")
    assert "lazy(() => import('./pages/admin/AdminLayout'))" in src
    assert "Suspense" in src


def test_vendor_and_hls_have_their_own_chunks():
    src = _src("frontend/vite.config.ts")
    assert "manualChunks" in src
    assert "'hls.js'" in src


def test_admin_requests_table_renders_one_page():
    src = _src("frontend/src/pages/admin/Requests.tsx")
    assert "ALL_REQUESTS_PAGE_SIZE" in src
    m = re.search(r"filtered\.slice\(", src)
    assert m, "the table still mounts every filtered row"
