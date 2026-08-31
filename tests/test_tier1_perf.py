"""Tier 1 performance fixes.

Five small changes from the 2026-08-31 performance review:
1. /ui/api/library/movies pages through SQL instead of get_recent(10000),
   which silently hid everything past the 10,000 most recent rows.
2. cleanup's repair loop only sleeps when a repair actually made API calls;
   an unconditional sleep(2) per healthy .strm turned a 100k-library run
   into ~55 hours of idle waiting.
3. RealDebrid's on-play wait is capped like TorBox's (45s); it inherited the
   600s request-time timeout and could hold a serving thread for 10 minutes.
4. /ui/api/requests/failed filters in SQL (indexed on status) instead of
   pulling 500 full rows per poll per user and filtering in Python.
5. shell_summary counts wanted episodes with COUNT(*) instead of loading
   the whole wanted_episodes table on every page navigation.
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


def _src(relpath):
    with open(os.path.join(_ROOT, relpath), encoding="utf-8") as f:
        return f.read()


def _insert_request(title, media_type="movie", status="success", created_at=None):
    with db._connect() as conn:
        if created_at:
            conn.execute(
                "INSERT INTO requests (title, imdb_id, media_type, status, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (title, f"tt{abs(hash(title)) % 10**7:07d}", media_type, status, created_at),
            )
        else:
            conn.execute(
                "INSERT INTO requests (title, imdb_id, media_type, status) "
                "VALUES (?, ?, ?, ?)",
                (title, f"tt{abs(hash(title)) % 10**7:07d}", media_type, status),
            )
        conn.commit()


# -- 1. library pagination ----------------------------------------------------

def test_movie_page_respects_limit_and_offset():
    for n in range(5):
        _insert_request(f"Movie {n}", created_at=f"2026-01-0{n + 1} 00:00:00")

    first = db.get_movie_requests_page(limit=2, offset=0)
    second = db.get_movie_requests_page(limit=2, offset=2)

    assert [r["title"] for r in first["items"]] == ["Movie 4", "Movie 3"]
    assert [r["title"] for r in second["items"]] == ["Movie 2", "Movie 1"]
    assert first["total"] == 5


def test_movie_page_excludes_series():
    _insert_request("A Movie", media_type="movie")
    _insert_request("A Show", media_type="series")

    page = db.get_movie_requests_page()

    assert [r["title"] for r in page["items"]] == ["A Movie"]
    assert page["total"] == 1


def test_movie_page_search_is_case_insensitive():
    _insert_request("Dune Part Two")
    _insert_request("Oppenheimer")

    page = db.get_movie_requests_page(search="dune")

    assert [r["title"] for r in page["items"]] == ["Dune Part Two"]
    assert page["total"] == 1


def test_movie_page_status_filter_and_counts():
    _insert_request("Won", status="success")
    _insert_request("Lost", status="wanted")
    _insert_request("Broke", status="failed")

    page = db.get_movie_requests_page(status_filter="wanted")

    assert sorted(r["title"] for r in page["items"]) == ["Broke", "Lost"]
    assert page["total"] == 2
    # Chip counts describe the whole (searched) set, not the active filter
    assert page["counts"] == {"all": 3, "available": 1, "wanted": 2}


def test_movie_page_counts_respect_search():
    """The toolbar shows counts for what the search matches."""
    _insert_request("Dune", status="success")
    _insert_request("Dune Part Two", status="wanted")
    _insert_request("Oppenheimer", status="success")

    page = db.get_movie_requests_page(search="dune")

    assert page["counts"] == {"all": 2, "available": 1, "wanted": 1}


def test_library_movies_route_paginates_not_get_recent():
    """The route must not go back to the truncating get_recent(10000)."""
    src = _src("app.py")
    m = re.search(r"def ui_api_library_movies\(\):(.*?)\n@app\.", src, re.S)
    assert m, "ui_api_library_movies not found"
    body = m.group(1)
    # The docstring mentions the old shape by name; only a call counts.
    assert "db.get_recent(" not in body
    assert "get_movie_requests_page" in body


def test_requests_media_type_index_exists():
    with db._connect() as conn:
        names = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    assert "idx_requests_media_created" in names


# -- 2. cleanup only sleeps when a repair ran ---------------------------------

def test_cleanup_repair_loop_skips_the_sleep_for_healthy_strms():
    src = _src("cleanup.py")
    m = re.search(r"result = _repair_strm.*?if result == \"repaired\"", src, re.S)
    assert m, "repair loop not found"
    loop = m.group(0)
    m2 = re.search(r"if result != \"ok\":\s*\n(?:\s*#.*\n)*\s*time\.sleep\(2\)", loop)
    assert m2, "sleep(2) is not gated on a repair having run"


# -- 3. RealDebrid on-play wait is capped -------------------------------------

def test_realdebrid_wait_accepts_a_timeout():
    import inspect
    import realdebrid
    sig = inspect.signature(realdebrid.wait_until_ready)
    assert "timeout" in sig.parameters


def test_realdebrid_wait_honours_the_timeout(monkeypatch):
    """A short timeout must bound the wait; the default used to be 600s."""
    import realdebrid
    clock = {"now": 0.0}
    monkeypatch.setattr(realdebrid.time, "monotonic", lambda: clock["now"])

    def _sleep(_s):
        clock["now"] += 2.0
    monkeypatch.setattr(realdebrid.time, "sleep", _sleep)
    polls = []
    monkeypatch.setattr(realdebrid, "get_info",
                        lambda rd_id: polls.append(rd_id) or {"status": "downloading"})

    assert realdebrid.wait_until_ready("x", timeout=45) is None
    assert clock["now"] <= 47  # bounded by the cap, not by 600s


def test_catbox_passes_the_on_play_cap_to_realdebrid():
    src = _src("catbox.py")
    bare = re.findall(r"_rd\.wait_until_ready\(rd_id\)", src)
    assert bare == [], "an RD on-play wait still uses the 600s default"
    capped = re.findall(
        r"_rd\.wait_until_ready\(rd_id,\s*timeout=ON_PLAY_READY_TIMEOUT_SEC\)", src)
    assert len(capped) == 3


# -- 4. failed-requests poll --------------------------------------------------

def test_get_failed_requests_filters_in_sql():
    _insert_request("Fine", status="success")
    _insert_request("Broken", status="failed")

    rows = db.get_failed_requests()

    assert [r["title"] for r in rows] == ["Broken"]


def test_failed_requests_route_uses_the_filtered_query():
    src = _src("app.py")
    m = re.search(r"def ui_api_failed_requests\(\):(.*?)\n@app\.", src, re.S)
    assert m
    assert "get_failed_requests" in m.group(1)
    assert "get_recent" not in m.group(1)


def test_failed_requests_poll_is_not_every_ten_seconds():
    src = _src("frontend/src/pages/Requests.tsx")
    m = re.search(r"'failed-requests'.*?refetchInterval:\s*(\d+)", src, re.S)
    assert m, "failed-requests poll not found"
    assert int(m.group(1)) >= 30000


# -- 5. shell summary counts instead of loading the table ---------------------

def test_count_wanted_episodes_counts_only_wanted():
    db.upsert_wanted_episode("tt0000001", 1, "Show", 1, 1, air_date="2026-01-01")
    db.upsert_wanted_episode("tt0000001", 1, "Show", 1, 2, air_date="2026-01-08")
    db.mark_episode_status("tt0000001", 1, 2, "found")

    assert db.count_wanted_episodes() == 1


def test_shell_summary_uses_the_count_not_the_table():
    src = _src("shell_summary.py")
    assert "count_wanted_episodes" in src
    assert "get_all_wanted_episodes" not in src
