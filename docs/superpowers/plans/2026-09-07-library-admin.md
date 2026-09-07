# Library Admin Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the admin Requests tab's flat request list with a title-centric Library tab: a filterable, pageable table with saved views, a per-title drawer that gathers every record about a title with its actions, a bulk action bar and a queue view.

**Architecture:** A new backend module `library_admin.py` answers two questions with SQL over the existing tables: `list_titles(filters)` (one SELECT with correlated subselects, plus a COUNT) and `title_detail(imdb_id)`. Thin admin routes expose them and a set of per-title actions over existing helpers. The frontend adds `pages/admin/Library.tsx` built from the Settings kit (`Card`, `Button`, `Select`, `MultiSelect`, `Pill`): a left rail with views and filters whose state lives in the URL hash, a table with server-side paging, a sticky action bar, and a right-side drawer of cards. The old admin `Requests.tsx` keeps pending approvals and the auto-approve rules until plan 2 rebuilds it; its "All requests" panel is removed here.

**Tech Stack:** Python 3.12 / Flask / SQLite, pytest; React 18 + TypeScript + Vite + Tailwind, `@tanstack/react-query`, vitest + Testing Library. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-07-library-admin-design.md`

## Global Constraints

- Never use em-dashes or `--` in code, comments, copy or docs.
- The repo is public: no passwords, tokens or IP addresses.
- Branch `main`. Commit trailer `Claude-Session: https://claude.ai/code/session_01F7oCy4VPeTT91GtZNTA8px`. No `Co-Authored-By`.
- Tests never import `app.py`; routes are checked on source text via `_src()`. Every DB-touching test file carries its own `_isolated_db` autouse fixture (copy from `tests/test_setup_wizard.py` lines 26 to 45). No `tests/conftest.py`. No test reaches the network.
- Mutation-check each new load-bearing test. Run pytest as `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/ -q -p no:cacheprovider` (856 passed at HEAD f990a95). Frontend: `cd frontend && npx tsc --noEmit && npx vitest run` (199 passed). The built `static/app/` is committed after any frontend change.
- Admin routes use the existing guard shape: `if not auth.is_admin(): return jsonify(error="admin required"), 403`. Action routes return JSON `{ok, message}`.
- Request `status` values are `success, wanted, upcoming, failed, pending`. `media_type` is `movie` or anything else for series (compare with `!= 'movie'`). Playability statuses are `playable, degraded, unknown`; the content key is `imdb_id` for a movie and `imdb_id:SxxEyy` for an episode (`catbox._content_key`).
- Views and their predicates are exactly the spec's table: `all`, `attention` (status failed, or playability degraded, or retry attempt >= 3), `wanted` (status wanted or upcoming), `queue` (status pending, or a retry row, or a wanted-movies row, or missing episodes), `incomplete` (series with missing episodes), `unmirrored` (success and not mirrored).
- Copy: plain English, no code words in labels; card titles are short nouns rendered uppercase by the card style.
- Only data-model change: nullable `activity_log.imdb_id` plus indexes on `activity_log(imdb_id)`, `user_requests(imdb_id, created_at DESC)`, `wanted_episodes(imdb_id, status)`.

## File structure

| File | Responsibility |
|---|---|
| `db.py` | migration and indexes; `log_activity(..., imdb_id=None)`; `get_retry_by_imdb`, `get_activity_for_title`, `get_user_requests_for_title`, `get_hashes_for_title`, `blacklist_hash`, `reset_playability_for_title`, `get_playability_for_title`, `get_monitored_series_by_imdb`, `get_wanted_episodes_for_title`, `get_wanted_movie` |
| `library_admin.py` (new) | `list_titles`, `view_counts`, `title_detail`, `season_episodes`, the view and filter vocabularies |
| `app.py` | `GET /ui/api/library`, `GET /ui/api/library/views`, `GET /ui/api/library/<imdb_id>`, `GET /ui/api/library/<imdb_id>/season/<n>`, the action routes |
| `processor.py`, `upgrader.py`, `disk_sync.py`, `cleanup.py`/`app.py` purge, `retry_queue.py` | pass `imdb_id` to `log_activity` |
| `frontend/src/api.ts` | `LibraryRow`, `LibraryDetail`, `SeasonEpisodes` types; `library*` functions |
| `frontend/src/pages/admin/library/state.ts` | filter state type, hash parse and serialise |
| `frontend/src/pages/admin/library/Rail.tsx`, `TitleTable.tsx`, `ActionBar.tsx`, `TitleDrawer.tsx`, `cards/*.tsx` | the UI |
| `frontend/src/pages/admin/Library.tsx` | the tab shell |
| `frontend/src/pages/admin/AdminLayout.tsx`, `Requests.tsx`, `Overview.tsx`, `Maintenance.tsx`, `Blacklist.tsx` | tab strip, panel removal, links |
| docs | `README.md`, `docs/install-guide.html`, `CHANGELOG.md` |

---

### Task 1: Activity log gains `imdb_id`; db helpers the read model needs

**Files:**
- Modify: `db.py` (migration block near the `requests` migrations; `log_activity`; new helpers appended after `get_activity`)
- Modify: `processor.py:731,761,766`, `upgrader.py:106,148,228,284`, `disk_sync.py:67`, `app.py:2155` (purge), `retry_queue.py` (if it logs), pass `imdb_id=`
- Test: `tests/test_library_db.py` (new)

**Interfaces:**
- Produces (all in `db.py`):
  - `log_activity(event, title=None, message=None, success=True, imdb_id=None)`
  - `get_activity_for_title(imdb_id, title, limit=20, before_id=None) -> list[dict]` (rows with `imdb_id` equal, or `imdb_id IS NULL AND title = ?`, newest first, `before_id` pages)
  - `get_retry_by_imdb(imdb_id) -> dict | None`
  - `get_user_requests_for_title(imdb_id) -> list[dict]` (with `username` and `reviewer` usernames)
  - `get_hashes_for_title(imdb_id) -> list[dict]` (`{info_hash, blacklisted, fail_count, last_error, current}` from `requests.info_hash` and `virtual_items.info_hash` joined to `failed_hashes`, `current` true for the request row's hash)
  - `blacklist_hash(info_hash, note) -> None` (upsert `failed_hashes` with `fail_count = max(existing, 3)` and `last_error = note`)
  - `get_playability_for_title(imdb_id) -> list[dict]` (rows whose key is the id or `id:%`)
  - `reset_playability_for_title(imdb_id) -> int`
  - `get_monitored_series_by_imdb(imdb_id) -> dict | None`
  - `get_wanted_episodes_for_title(imdb_id) -> list[dict]` (all statuses)
  - `get_wanted_movie(imdb_id) -> dict | None`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_library_db.py`:

```python
"""db helpers behind the Library admin tab: per-title reads, the activity
log's imdb_id, and the blacklist and playability helpers the drawer uses.
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


def _item(imdb, token, info_hash, season=None, episode=None, torbox_id=None):
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, strm_path, imdb_id, season, episode, torbox_id) "
            "VALUES (?, ?, 'magnet:?x', 'T', ?, ?, ?, ?, ?, ?)",
            (token, info_hash, "movie" if season is None else "series", f"/media/{token}.strm", imdb, season, episode, torbox_id))
        conn.commit()


def test_activity_log_has_imdb_id_and_the_title_query_falls_back_to_title_text():
    db.log_activity("added", "Heat", "movie", True, imdb_id="tt0113277")
    db.log_activity("failed", "Heat", "old row without an id", False)
    db.log_activity("added", "Alien", "movie", True, imdb_id="tt0078748")
    rows = db.get_activity_for_title("tt0113277", "Heat")
    assert [r["event"] for r in rows] == ["failed", "added"], "newest first, title fallback included"
    assert rows[1]["imdb_id"] == "tt0113277"
    page2 = db.get_activity_for_title("tt0113277", "Heat", limit=1, before_id=rows[0]["id"])
    assert [r["event"] for r in page2] == ["added"]


def test_every_activity_caller_that_knows_the_title_passes_its_id():
    for name in ("processor.py", "upgrader.py", "disk_sync.py"):
        src = _src(name)
        calls = [line for line in src.splitlines() if "log_activity(" in line]
        assert calls, name
        assert all("imdb_id=" in line for line in calls), f"{name}: {[c.strip() for c in calls if 'imdb_id=' not in c]}"
    purge = _src("app.py").split('db.log_activity("purged"', 1)[1][:200]
    assert "imdb_id=" in purge


def test_retry_row_and_wanted_movie_by_imdb():
    assert db.get_retry_by_imdb("tt1") is None
    db.enqueue_retry("tt1", "T", "movie", None, attempt=2, delay_seconds=60)
    assert db.get_retry_by_imdb("tt1")["attempt"] == 2
    assert db.get_wanted_movie("tt1") is None


def test_user_requests_for_title_carry_usernames():
    uid = db.create_user("adam", "scrypt$x$y", role="user")
    admin = db.create_user("root", "scrypt$x$y", role="admin")
    rid = db.create_user_request(uid, "tt0113277", 949, "movie", "Heat", None)
    db.update_user_request_status(rid, "approved", reviewed_by=admin, note="fine")
    rows = db.get_user_requests_for_title("tt0113277")
    assert rows[0]["username"] == "adam" and rows[0]["reviewer"] == "root" and rows[0]["note"] == "fine"


def test_hashes_for_title_join_the_blacklist_and_mark_the_current_one():
    rid = db.insert_request("Heat", "tt0113277", "movie")
    db.update_request(rid, "success", info_hash="b" * 40)
    _item("tt0113277", "tok1", "a" * 40)
    _item("tt0113277", "tok2", "b" * 40, torbox_id=7)
    db.blacklist_hash("a" * 40, "blacklisted by admin")
    rows = {r["info_hash"]: r for r in db.get_hashes_for_title("tt0113277")}
    assert rows["a" * 40]["blacklisted"] is True and rows["a" * 40]["last_error"] == "blacklisted by admin"
    assert rows["b" * 40]["blacklisted"] is False and rows["b" * 40]["current"] is True
    assert ("a" * 40) in db.get_blacklisted_hashes()
    db.clear_failed_hash("a" * 40)
    assert ("a" * 40) not in db.get_blacklisted_hashes()


def test_playability_for_title_covers_movie_and_episode_keys():
    db.update_playability_fail("tt1", "cdn 404")
    db.update_playability_fail("tt2:S01E02", "timeout")
    db.update_playability_ok("tt2:S01E03", "torbox")
    assert [r["content_key"] for r in db.get_playability_for_title("tt1")] == ["tt1"]
    keys = {r["content_key"] for r in db.get_playability_for_title("tt2")}
    assert keys == {"tt2:S01E02", "tt2:S01E03"}
    assert db.reset_playability_for_title("tt2") == 2
    assert all(r["status"] == "unknown" for r in db.get_playability_for_title("tt2"))


def test_series_reads_by_imdb():
    db.upsert_monitored_series("tt2", 100, "Show", [1, 2])
    db.upsert_wanted_episode("tt2", 100, "Show", 1, 2, "2024-01-01")
    assert db.get_monitored_series_by_imdb("tt2")["title"] == "Show"
    assert db.get_wanted_episodes_for_title("tt2")[0]["episode"] == 2
    assert db.get_monitored_series_by_imdb("nope") is None


def test_the_new_indexes_exist():
    with db._connect() as conn:
        names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_activity_imdb", "idx_user_requests_imdb", "idx_wanted_episodes_imdb_status"} <= names
```

The helpers this test uses exist with these signatures: `db.create_user(username, password_hash, role=...)`, `db.create_user_request(user_id, imdb_id, tmdb_id, media_type, title, seasons=None, status="pending")`, `db.update_user_request_status(req_id, status, reviewed_by=None, note=None)`, `db.upsert_monitored_series(imdb_id, tmdb_id, title, seasons, monitor_mode="all")`, `db.upsert_wanted_episode(imdb_id, tmdb_id, title, season, episode, air_date)`, `db.insert_request(title, imdb_id, media_type, seasons=None, tmdb_id=None) -> id`, `db.update_request(row_id, status, quality=None, source=None, info_hash=None, error=None)`, `db.enqueue_retry(imdb_id, title, media_type, seasons, attempt, delay_seconds)`.

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/test_library_db.py -q -p no:cacheprovider`
Expected: FAIL on `imdb_id` keyword, then on missing helpers.

- [ ] **Step 3: Migration, indexes and `log_activity`**

In `db.init()`'s migration section (next to the `requests` column migrations), add:

```python
        act_cols = {r["name"] for r in conn.execute("PRAGMA table_info(activity_log)")}
        if "imdb_id" not in act_cols:
            conn.execute("ALTER TABLE activity_log ADD COLUMN imdb_id TEXT")
            log.info("Migration: added activity_log.imdb_id")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_imdb ON activity_log(imdb_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_requests_imdb ON user_requests(imdb_id, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_wanted_episodes_imdb_status ON wanted_episodes(imdb_id, status)")
```

Replace `log_activity`:

```python
def log_activity(event: str, title: str | None = None, message: str | None = None,
                 success: bool = True, imdb_id: str | None = None) -> None:
    with _connect() as conn:
        conn.execute(
            "INSERT INTO activity_log (event, title, message, success, imdb_id) VALUES (?, ?, ?, ?, ?)",
            (event, title, message, int(success), imdb_id),
        )
        conn.commit()
```

- [ ] **Step 4: The helpers**

Append after `get_activity`:

```python
def get_activity_for_title(imdb_id: str, title: str | None, limit: int = 20,
                           before_id: int | None = None) -> list[dict]:
    """Activity for one title, newest first. Rows written before the
    imdb_id column existed match on title text."""
    sql = "SELECT * FROM activity_log WHERE (imdb_id = ? OR (imdb_id IS NULL AND title = ?))"
    args: list = [imdb_id, title or ""]
    if before_id is not None:
        sql += " AND id < ?"
        args.append(before_id)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with _connect() as conn:
        return [dict(r) for r in conn.execute(sql, args).fetchall()]


def get_retry_by_imdb(imdb_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM retry_queue WHERE imdb_id=?", (imdb_id,)).fetchone()
        return dict(row) if row else None


def get_wanted_movie(imdb_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM wanted_movies WHERE imdb_id=?", (imdb_id,)).fetchone()
        return dict(row) if row else None


def get_user_requests_for_title(imdb_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT ur.*, u.username, rv.username AS reviewer
               FROM user_requests ur
               JOIN users u ON u.id = ur.user_id
               LEFT JOIN users rv ON rv.id = ur.reviewed_by
               WHERE ur.imdb_id = ? ORDER BY ur.created_at DESC""", (imdb_id,)).fetchall()
        return [dict(r) for r in rows]


BLACKLIST_THRESHOLD = 3


def get_hashes_for_title(imdb_id: str) -> list[dict]:
    """Every hash this title has used (request row and virtual items), with
    its blacklist state. `current` marks the request row's hash."""
    with _connect() as conn:
        req = conn.execute("SELECT info_hash FROM requests WHERE imdb_id=?", (imdb_id,)).fetchone()
        current = (req["info_hash"] if req else None) or ""
        rows = conn.execute(
            """SELECT h.info_hash, f.fail_count, f.last_error, f.last_attempt
               FROM (SELECT DISTINCT info_hash FROM virtual_items WHERE imdb_id = ? AND info_hash != ''
                     UNION SELECT info_hash FROM requests WHERE imdb_id = ? AND info_hash IS NOT NULL AND info_hash != '') h
               LEFT JOIN failed_hashes f ON f.info_hash = h.info_hash
               ORDER BY h.info_hash""", (imdb_id, imdb_id)).fetchall()
    return [{"info_hash": r["info_hash"], "fail_count": r["fail_count"] or 0,
             "blacklisted": (r["fail_count"] or 0) >= BLACKLIST_THRESHOLD,
             "last_error": r["last_error"], "last_attempt": r["last_attempt"],
             "current": r["info_hash"] == current} for r in rows]


def blacklist_hash(info_hash: str, note: str) -> None:
    """Put a hash on the blacklist by hand: its fail count jumps to the
    threshold, so get_blacklisted_hashes() reports it from now on."""
    with _connect() as conn:
        conn.execute(
            """INSERT INTO failed_hashes (info_hash, fail_count, last_error)
               VALUES (?, ?, ?)
               ON CONFLICT(info_hash) DO UPDATE SET
                 fail_count = MAX(fail_count, excluded.fail_count),
                 last_error = excluded.last_error,
                 last_attempt = strftime('%Y-%m-%d %H:%M:%S', 'now')""",
            (info_hash, BLACKLIST_THRESHOLD, note))
        conn.commit()


def get_playability_for_title(imdb_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM playability_state WHERE content_key = ? OR content_key LIKE ? ORDER BY content_key",
            (imdb_id, f"{imdb_id}:%")).fetchall()
        return [dict(r) for r in rows]


def reset_playability_for_title(imdb_id: str) -> int:
    with _connect() as conn:
        cur = conn.execute(
            """UPDATE playability_state SET status='unknown', consecutive_failures=0,
               last_fail_reason=NULL, updated_at=strftime('%Y-%m-%d %H:%M:%S', 'now')
               WHERE content_key = ? OR content_key LIKE ?""", (imdb_id, f"{imdb_id}:%"))
        conn.commit()
        return cur.rowcount


def get_monitored_series_by_imdb(imdb_id: str) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM monitored_series WHERE imdb_id=?", (imdb_id,)).fetchone()
        return dict(row) if row else None


def get_wanted_episodes_for_title(imdb_id: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM wanted_episodes WHERE imdb_id=? ORDER BY season, episode", (imdb_id,)).fetchall()
        return [dict(r) for r in rows]
```

Check `get_blacklisted_hashes(threshold=3)`'s default equals `BLACKLIST_THRESHOLD`; if the code uses a settings value (`BLACKLIST_FAIL_THRESHOLD`), have `blacklist_hash` read that through `settings.get("BLACKLIST_FAIL_THRESHOLD", 3)` instead of the constant, and say so in the report.

- [ ] **Step 5: Pass `imdb_id` from the callers**

`processor.py` lines 731, 761, 766: add `imdb_id=req.imdb_id`. `upgrader.py` 106 and 148: the item/row has `imdb_id` (`item["imdb_id"]`, `row["imdb_id"]`); 228 (consolidation) and 284 (found): use the variable in scope that carries the id (`imdb_id`, `w["imdb_id"]`); read the surrounding lines. `disk_sync.py` 67: `imdb_id=imdb_id`. `app.py` 2155 (purge): `imdb_id=imdb_id`. `retry_queue.py`, `watchdog.py`, `torbox.py`, `recovery.py`, `library_sync.py` have no title id; leave them.

- [ ] **Step 6: Run, mutation-check, commit**

Run the new file, then the full suite. Mutation: make `get_activity_for_title` drop the title fallback (`imdb_id = ?` only): the first test must fail. Restore. Delete `__pycache__`.

```bash
git add db.py processor.py upgrader.py disk_sync.py app.py tests/test_library_db.py
git commit -m "feat(db): per-title reads for the Library tab, activity log carries imdb_id

Claude-Session: https://claude.ai/code/session_01F7oCy4VPeTT91GtZNTA8px"
```

---

### Task 2: `library_admin.list_titles`, views, and the list endpoints

**Files:**
- Create: `library_admin.py`
- Modify: `app.py` (two routes next to `ui_api_settings_schema`)
- Test: `tests/test_library_admin.py` (new)

**Interfaces:**
- Produces: `library_admin.VIEWS`, `PROBLEMS`, `SORTS`; `list_titles(filters: dict) -> tuple[list[dict], int]` where `filters` keys are `view, q, status (list), type, problem, requester, added, sort, order, page, per_page`; `view_counts() -> dict[str, int]`; `GET /ui/api/library` and `GET /ui/api/library/views`.
- Row shape: `id, imdb_id, tmdb_id, title, media_type, status, error, quality, source, info_hash, seasons, created_at, updated_at, requester (str, "auto" when none), requester_id (int|None), requested_at, playability ({status, last_fail_reason}|None), missing_episodes (int), retry ({attempt, next_retry_at}|None), arr_mirrored (bool), in_torbox (bool), in_wanted_movies (bool)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_library_admin.py`:

```python
"""library_admin: the read model behind the Library tab. One query with
subselects, filters and views resolved in SQL, server-side paging."""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db
import library_admin as la

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


def _req(title, imdb, media_type="movie", status="success", **cols):
    rid = db.insert_request(title, imdb, media_type)
    db.update_request(rid, status, **cols)
    return rid


@pytest.fixture
def seeded():
    """Six titles covering every view."""
    uid = db.create_user("adam", "scrypt$x$y", role="user")
    _req("Heat", "tt1")                                   # plain success, requested by adam, mirrored, in torbox
    _req("Alien", "tt2", status="failed", error="no release")
    _req("Dune", "tt3", status="wanted")
    _req("Loki", "tt4", media_type="series")               # missing episodes
    _req("Fargo", "tt5", media_type="series", status="pending")
    _req("Tenet", "tt6")                                   # unplayable, in retry queue, unmirrored
    db.create_user_request(uid, "tt1", 949, "movie", "Heat", None)
    db.mark_arr_mirrored("tt1")
    with db._connect() as conn:
        conn.execute("INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, strm_path, imdb_id, torbox_id) "
                     "VALUES ('t1', 'h', 'm', 'Heat', 'movie', '/m/h.strm', 'tt1', 5)")
        conn.execute("UPDATE requests SET created_at = datetime('now', '-40 days') WHERE imdb_id = 'tt2'")
        conn.commit()
    db.upsert_wanted_episode("tt4", 100, "Loki", 2, 3, "2024-01-01")
    db.update_playability_fail("tt6", "cdn 404")
    db.enqueue_retry("tt6", "Tenet", "movie", None, attempt=3, delay_seconds=3600)
    return uid


def _ids(rows):
    return [r["imdb_id"] for r in rows]


def test_default_listing_is_every_title_newest_first_with_the_computed_columns(seeded):
    rows, total = la.list_titles({})
    assert total == 6 and len(rows) == 6
    by = {r["imdb_id"]: r for r in rows}
    assert by["tt1"]["requester"] == "adam" and by["tt1"]["arr_mirrored"] is True and by["tt1"]["in_torbox"] is True
    assert by["tt2"]["requester"] == "auto" and by["tt2"]["error"] == "no release"
    assert by["tt4"]["missing_episodes"] == 1
    assert by["tt6"]["playability"] == {"status": "degraded", "last_fail_reason": "cdn 404"}
    assert by["tt6"]["retry"]["attempt"] == 3 and by["tt6"]["arr_mirrored"] is False
    assert by["tt1"]["playability"] is None and by["tt1"]["retry"] is None


@pytest.mark.parametrize("view,expected", [
    ("attention", {"tt2", "tt6"}),
    ("wanted", {"tt3"}),
    ("queue", {"tt4", "tt5", "tt6"}),
    ("incomplete", {"tt4"}),
    ("unmirrored", {"tt6"}),
    ("all", {"tt1", "tt2", "tt3", "tt4", "tt5", "tt6"}),
])
def test_views_select_exactly_their_titles(seeded, view, expected):
    rows, total = la.list_titles({"view": view})
    assert set(_ids(rows)) == expected and total == len(expected)


def test_view_counts_match_the_views(seeded):
    counts = la.view_counts()
    assert counts == {"all": 6, "attention": 2, "wanted": 1, "queue": 3, "incomplete": 1, "unmirrored": 1}


@pytest.mark.parametrize("filters,expected", [
    ({"q": "ali"}, {"tt2"}),
    ({"q": "tt4"}, {"tt4"}),
    ({"status": ["failed", "wanted"]}, {"tt2", "tt3"}),
    ({"type": "series"}, {"tt4", "tt5"}),
    ({"type": "movie", "status": ["success"]}, {"tt1", "tt6"}),
    ({"problem": "unplayable"}, {"tt6"}),
    ({"problem": "missing_episodes"}, {"tt4"}),
    ({"problem": "in_retry_queue"}, {"tt6"}),
    ({"problem": "no_requester"}, {"tt2", "tt3", "tt4", "tt5", "tt6"}),
    ({"problem": "not_mirrored"}, {"tt6"}),
    ({"requester": "auto"}, {"tt2", "tt3", "tt4", "tt5", "tt6"}),
    ({"added": "30d"}, {"tt1", "tt3", "tt4", "tt5", "tt6"}),
])
def test_filters(seeded, filters, expected):
    rows, _ = la.list_titles(filters)
    assert set(_ids(rows)) == expected


def test_requester_filter_by_user_id(seeded):
    rows, _ = la.list_titles({"requester": str(seeded)})
    assert _ids(rows) == ["tt1"]


def test_sorting_and_paging(seeded):
    rows, total = la.list_titles({"sort": "title", "order": "asc", "per_page": 2, "page": 2})
    assert total == 6 and _ids(rows) == ["tt5", "tt1"], "Alien, Dune | Fargo, Heat | Loki, Tenet"
    rows, _ = la.list_titles({"sort": "title", "order": "desc", "per_page": 4})
    assert _ids(rows) == ["tt6", "tt4", "tt1", "tt5"]
    rows, _ = la.list_titles({"per_page": 1000})
    assert len(rows) == 6, "per_page is capped, not rejected"


def test_unknown_values_are_ignored_not_errors(seeded):
    rows, total = la.list_titles({"view": "bogus", "sort": "DROP TABLE", "status": ["nope"], "page": "x"})
    assert total == 0 and rows == []
    rows, total = la.list_titles({"view": "bogus"})
    assert total == 0


def test_the_routes_exist_and_are_admin_only():
    src = _src("app.py")
    for route in ('@app.get("/ui/api/library")', '@app.get("/ui/api/library/views")'):
        assert route in src
        body = src.split(route, 1)[1].split("\n\n\n", 1)[0]
        assert "auth.is_admin()" in body and "library_admin" in body
    body = src.split('@app.get("/ui/api/library")', 1)[1].split("\n\n\n", 1)[0]
    assert 'request.args.getlist("status")' in body
```

`test_unknown_values_are_ignored_not_errors` expects an unknown view to yield nothing and an unknown status to match nothing; an unknown sort falls back to the default. Helper signatures are listed in Task 1.

- [ ] **Step 2: Run to verify it fails**

Expected: `ModuleNotFoundError: No module named 'library_admin'`.

- [ ] **Step 3: Write `library_admin.py`**

```python
"""The read model behind the admin Library tab.

One SELECT over requests with correlated subselects for everything the
table shows (requester, playability, missing episodes, retry queue, arr
mirror, TorBox), wrapped so filters and views can reference the computed
columns, plus a COUNT with the same WHERE. Views are named filter sets so
the rail counts and the table agree by construction.
"""
from __future__ import annotations

import db

VIEWS = ("all", "attention", "wanted", "queue", "incomplete", "unmirrored")
PROBLEMS = ("failed", "wanted", "unplayable", "missing_episodes", "in_retry_queue", "no_requester", "not_mirrored")
STATUSES = ("success", "wanted", "upcoming", "failed", "pending")
SORTS = {
    "title": "t.title COLLATE NOCASE",
    "status": "t.status",
    "requester": "t.requester",
    "updated": "t.updated_at",
    "created": "t.created_at",
}
MAX_PER_PAGE = 200
DEFAULT_PER_PAGE = 50

_BASE = """
SELECT r.id, r.imdb_id, r.tmdb_id, r.title, r.media_type, r.status, r.error, r.quality, r.source,
       r.info_hash, r.seasons, r.created_at, r.updated_at, r.arr_mirrored_at,
       (SELECT u.username FROM user_requests ur JOIN users u ON u.id = ur.user_id
         WHERE ur.imdb_id = r.imdb_id ORDER BY ur.created_at DESC, ur.id DESC LIMIT 1) AS requester,
       (SELECT ur.user_id FROM user_requests ur WHERE ur.imdb_id = r.imdb_id
         ORDER BY ur.created_at DESC, ur.id DESC LIMIT 1) AS requester_id,
       (SELECT ur.created_at FROM user_requests ur WHERE ur.imdb_id = r.imdb_id
         ORDER BY ur.created_at DESC, ur.id DESC LIMIT 1) AS requested_at,
       (SELECT p.status FROM playability_state p
         WHERE p.content_key = r.imdb_id OR p.content_key LIKE r.imdb_id || ':%'
         ORDER BY CASE p.status WHEN 'degraded' THEN 0 WHEN 'unknown' THEN 1 ELSE 2 END LIMIT 1) AS play_status,
       (SELECT p.last_fail_reason FROM playability_state p
         WHERE (p.content_key = r.imdb_id OR p.content_key LIKE r.imdb_id || ':%') AND p.status = 'degraded'
         ORDER BY p.updated_at DESC LIMIT 1) AS play_reason,
       (SELECT COUNT(*) FROM wanted_episodes w WHERE w.imdb_id = r.imdb_id AND w.status = 'wanted') AS missing_episodes,
       (SELECT q.attempt FROM retry_queue q WHERE q.imdb_id = r.imdb_id) AS retry_attempt,
       (SELECT q.next_retry_at FROM retry_queue q WHERE q.imdb_id = r.imdb_id) AS retry_next,
       (SELECT 1 FROM wanted_movies wm WHERE wm.imdb_id = r.imdb_id) AS in_wanted_movies,
       (SELECT 1 FROM virtual_items v WHERE v.imdb_id = r.imdb_id AND v.torbox_id IS NOT NULL LIMIT 1) AS in_torbox
FROM requests r
"""

_VIEW_WHERE = {
    "all": "1=1",
    "attention": "(t.status = 'failed' OR t.play_status = 'degraded' OR t.retry_attempt >= 3)",
    "wanted": "t.status IN ('wanted', 'upcoming')",
    "queue": "(t.status = 'pending' OR t.retry_attempt IS NOT NULL OR t.in_wanted_movies = 1 OR t.missing_episodes > 0)",
    "incomplete": "(t.media_type != 'movie' AND t.missing_episodes > 0)",
    "unmirrored": "(t.status = 'success' AND t.arr_mirrored_at IS NULL)",
}
_VIEW_ORDER = {
    "wanted": "t.updated_at ASC",
    "queue": "t.retry_next IS NULL, t.retry_next ASC, t.updated_at DESC",
}
_PROBLEM_WHERE = {
    "failed": "t.status = 'failed'",
    "wanted": "t.status IN ('wanted', 'upcoming')",
    "unplayable": "t.play_status = 'degraded'",
    "missing_episodes": "t.missing_episodes > 0",
    "in_retry_queue": "t.retry_attempt IS NOT NULL",
    "no_requester": "t.requester IS NULL",
    "not_mirrored": "(t.status = 'success' AND t.arr_mirrored_at IS NULL)",
}
_ADDED = {"24h": "-1 day", "7d": "-7 days", "30d": "-30 days"}


def _where(filters: dict) -> tuple[str, list]:
    clauses: list[str] = []
    args: list = []
    view = filters.get("view") or "all"
    clauses.append(_VIEW_WHERE.get(view, "0=1"))
    q = (filters.get("q") or "").strip()
    if q:
        like = f"%{q}%"
        clauses.append("(t.title LIKE ? OR t.imdb_id LIKE ? OR t.info_hash LIKE ?)")
        args += [like, like, like]
    statuses = [s for s in (filters.get("status") or []) if s in STATUSES]
    if filters.get("status"):
        if statuses:
            clauses.append("t.status IN (%s)" % ",".join("?" * len(statuses)))
            args += statuses
        else:
            clauses.append("0=1")
    kind = filters.get("type")
    if kind == "movie":
        clauses.append("t.media_type = 'movie'")
    elif kind == "series":
        clauses.append("t.media_type != 'movie'")
    problem = filters.get("problem")
    if problem in _PROBLEM_WHERE:
        clauses.append(_PROBLEM_WHERE[problem])
    requester = filters.get("requester")
    if requester == "auto":
        clauses.append("t.requester IS NULL")
    elif requester and str(requester).isdigit():
        clauses.append("t.requester_id = ?")
        args.append(int(requester))
    added = _ADDED.get(filters.get("added") or "")
    if added:
        clauses.append("t.created_at >= datetime('now', ?)")
        args.append(added)
    return " AND ".join(clauses), args


def _order(filters: dict) -> str:
    sort = filters.get("sort")
    if sort in SORTS:
        direction = "ASC" if (filters.get("order") or "").lower() == "asc" else "DESC"
        return f"{SORTS[sort]} {direction}, t.id DESC"
    view = filters.get("view") or "all"
    return _VIEW_ORDER.get(view, "t.updated_at DESC, t.id DESC")


def _int(value, default: int, lo: int, hi: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _row(r: dict) -> dict:
    return {
        "id": r["id"], "imdb_id": r["imdb_id"], "tmdb_id": r["tmdb_id"], "title": r["title"],
        "media_type": r["media_type"], "status": r["status"], "error": r["error"],
        "quality": r["quality"], "source": r["source"], "info_hash": r["info_hash"], "seasons": r["seasons"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
        "requester": r["requester"] or "auto", "requester_id": r["requester_id"],
        "requested_at": r["requested_at"],
        "playability": ({"status": r["play_status"], "last_fail_reason": r["play_reason"]}
                        if r["play_status"] and r["play_status"] != "playable" else None),
        "missing_episodes": r["missing_episodes"] or 0,
        "retry": ({"attempt": r["retry_attempt"], "next_retry_at": r["retry_next"]}
                  if r["retry_attempt"] is not None else None),
        "arr_mirrored": r["arr_mirrored_at"] is not None,
        "in_torbox": bool(r["in_torbox"]),
        "in_wanted_movies": bool(r["in_wanted_movies"]),
    }


def list_titles(filters: dict) -> tuple[list[dict], int]:
    where, args = _where(filters)
    per_page = _int(filters.get("per_page"), DEFAULT_PER_PAGE, 1, MAX_PER_PAGE)
    page = _int(filters.get("page"), 1, 1, 10_000_000)
    order = _order(filters)
    with db._connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM ({_BASE}) t WHERE {where}", args).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM ({_BASE}) t WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
            args + [per_page, (page - 1) * per_page]).fetchall()
    return [_row(dict(r)) for r in rows], total


def view_counts() -> dict[str, int]:
    out = {}
    with db._connect() as conn:
        for view in VIEWS:
            out[view] = conn.execute(f"SELECT COUNT(*) FROM ({_BASE}) t WHERE {_VIEW_WHERE[view]}").fetchone()[0]
    return out
```

Note `"playable"` is reported as `None` playability (nothing to flag); `degraded` and `unknown` are reported. If the tests want `unknown` hidden too, keep the code as written: the seeded test only asserts a `degraded` row and a `None` for a title with no record.

- [ ] **Step 4: Routes in `app.py`**

After `ui_api_settings_schema`:

```python
@app.get("/ui/api/library")
def ui_api_library():
    """The Library tab's table: filters, views, sort and paging in SQL."""
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import library_admin
    a = request.args
    filters = {
        "view": a.get("view"), "q": a.get("q"), "status": a.getlist("status"),
        "type": a.get("type"), "problem": a.get("problem"), "requester": a.get("requester"),
        "added": a.get("added"), "sort": a.get("sort"), "order": a.get("order"),
        "page": a.get("page"), "per_page": a.get("per_page"),
    }
    rows, total = library_admin.list_titles(filters)
    page = library_admin._int(a.get("page"), 1, 1, 10_000_000)
    per_page = library_admin._int(a.get("per_page"), library_admin.DEFAULT_PER_PAGE, 1, library_admin.MAX_PER_PAGE)
    return jsonify(rows=rows, total=total, page=page, per_page=per_page)


@app.get("/ui/api/library/views")
def ui_api_library_views():
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import library_admin
    return jsonify(library_admin.view_counts())
```

- [ ] **Step 5: Run, mutation-check, commit**

Full suite green. Mutation: change `attention`'s `>= 3` to `>= 4`: the parametrised attention case must fail. Restore. Delete `__pycache__`.

```bash
git add library_admin.py app.py tests/test_library_admin.py
git commit -m "feat(library): title read model with views, filters and paging

Claude-Session: https://claude.ai/code/session_01F7oCy4VPeTT91GtZNTA8px"
```

---

### Task 3: `title_detail`, `season_episodes` and their endpoints

**Files:**
- Modify: `library_admin.py`, `app.py`
- Test: `tests/test_library_admin.py` (append)

**Interfaces:**
- Produces: `library_admin.title_detail(imdb_id) -> dict | None` with keys `request, items, playability, episodes, monitored, retry, wanted_movie, user_requests, seerr_request_id, override, hashes, activity, arr`; `season_episodes(imdb_id, season) -> list[dict]` (`{season, episode, present, strm_path, token, wanted_status, attempt_count, air_date, last_attempted}`); routes `GET /ui/api/library/<imdb_id>`, `GET /ui/api/library/<imdb_id>/season/<int:season>`, `GET /ui/api/library/<imdb_id>/activity?before=<id>`.

- [ ] **Step 1: Failing tests** (append to `tests/test_library_admin.py`)

```python
def test_title_detail_gathers_every_record(seeded):
    db.log_activity("added", "Heat", "movie", True, imdb_id="tt1")
    db.upsert_show_override("tt1", "1080p", True, False, "keep small")
    d = la.title_detail("tt1")
    assert d["request"]["imdb_id"] == "tt1"
    assert d["items"][0]["token"] == "t1" and d["items"][0]["torbox_id"] == 5
    assert d["user_requests"][0]["username"] == "adam"
    assert d["override"]["quality_preference"] == "1080p"
    assert d["hashes"][0]["info_hash"] == "h" and d["hashes"][0]["blacklisted"] is False
    assert d["activity"][0]["event"] == "added"
    assert d["arr"]["mirrored_at"] is not None
    assert d["retry"] is None and d["playability"] == [] and d["episodes"] is None
    assert la.title_detail("tt404") is None


def test_series_detail_summarises_seasons_and_lists_episodes(seeded):
    with db._connect() as conn:
        for ep in (1, 2):
            conn.execute("INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, strm_path, imdb_id, season, episode) "
                         "VALUES (?, 'h', 'm', 'Loki', 'series', ?, 'tt4', 2, ?)", (f"e{ep}", f"/s/e{ep}.strm", ep))
        conn.commit()
    d = la.title_detail("tt4")
    assert d["episodes"] == [{"season": 2, "present": 2, "wanted": 1}]
    eps = la.season_episodes("tt4", 2)
    assert [(e["episode"], e["present"], e["wanted_status"]) for e in eps] == [(1, True, None), (2, True, None), (3, False, "wanted")]
    assert eps[2]["air_date"] == "2024-01-01"


def test_detail_routes_exist():
    src = _src("app.py")
    for route in ('@app.get("/ui/api/library/<imdb_id>")', '@app.get("/ui/api/library/<imdb_id>/season/<int:season>")',
                  '@app.get("/ui/api/library/<imdb_id>/activity")'):
        assert route in src, route
        body = src.split(route, 1)[1].split("\n\n\n", 1)[0]
        assert "auth.is_admin()" in body
```

- [ ] **Step 2: Run, verify failure** (`AttributeError: title_detail`).

- [ ] **Step 3: Implement** (append to `library_admin.py`)

```python
def _seasons_summary(imdb_id: str) -> list[dict]:
    with db._connect() as conn:
        present = {r["season"]: r["n"] for r in conn.execute(
            "SELECT season, COUNT(*) AS n FROM virtual_items WHERE imdb_id = ? AND season IS NOT NULL GROUP BY season",
            (imdb_id,))}
        wanted = {r["season"]: r["n"] for r in conn.execute(
            "SELECT season, COUNT(*) AS n FROM wanted_episodes WHERE imdb_id = ? AND status = 'wanted' GROUP BY season",
            (imdb_id,))}
    return [{"season": s, "present": present.get(s, 0), "wanted": wanted.get(s, 0)}
            for s in sorted(set(present) | set(wanted))]


def title_detail(imdb_id: str) -> dict | None:
    req = db.get_request_by_imdb(imdb_id)
    if not req:
        return None
    is_series = req["media_type"] != "movie"
    items = db.get_virtual_items_by_imdb(imdb_id)
    return {
        "request": req,
        "items": [{k: i.get(k) for k in ("token", "info_hash", "strm_path", "torbox_id", "last_played",
                                         "play_count", "season", "episode", "debrid_provider", "quality")}
                  for i in items],
        "playability": db.get_playability_for_title(imdb_id),
        "episodes": _seasons_summary(imdb_id) if is_series else None,
        "monitored": db.get_monitored_series_by_imdb(imdb_id) if is_series else None,
        "retry": db.get_retry_by_imdb(imdb_id),
        "wanted_movie": None if is_series else db.get_wanted_movie(imdb_id),
        "user_requests": db.get_user_requests_for_title(imdb_id),
        "seerr_request_id": db.get_seerr_request_id(imdb_id),
        "override": db.get_show_override(imdb_id),
        "hashes": db.get_hashes_for_title(imdb_id),
        "activity": db.get_activity_for_title(imdb_id, req.get("title")),
        "arr": {"mirrored_at": req.get("arr_mirrored_at")},
    }


def season_episodes(imdb_id: str, season: int) -> list[dict]:
    with db._connect() as conn:
        present = {r["episode"]: dict(r) for r in conn.execute(
            "SELECT episode, token, strm_path FROM virtual_items WHERE imdb_id = ? AND season = ? AND episode IS NOT NULL",
            (imdb_id, season))}
    wanted = {w["episode"]: w for w in db.get_wanted_episodes_for_title(imdb_id) if w["season"] == season}
    out = []
    for ep in sorted(set(present) | set(wanted)):
        p, w = present.get(ep), wanted.get(ep)
        out.append({"season": season, "episode": ep, "present": p is not None,
                    "strm_path": p["strm_path"] if p else None, "token": p["token"] if p else None,
                    "wanted_status": w["status"] if w else None,
                    "attempt_count": w["attempt_count"] if w else 0,
                    "air_date": w["air_date"] if w else None,
                    "last_attempted": w["last_attempted"] if w else None})
    return out
```

Routes after the list routes:

```python
@app.get("/ui/api/library/<imdb_id>")
def ui_api_library_detail(imdb_id: str):
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import library_admin
    d = library_admin.title_detail(imdb_id)
    if d is None:
        return jsonify(error="not found"), 404
    return jsonify(d)


@app.get("/ui/api/library/<imdb_id>/season/<int:season>")
def ui_api_library_season(imdb_id: str, season: int):
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import library_admin
    return jsonify(episodes=library_admin.season_episodes(imdb_id, season))


@app.get("/ui/api/library/<imdb_id>/activity")
def ui_api_library_activity(imdb_id: str):
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    req = db.get_request_by_imdb(imdb_id)
    before = request.args.get("before", type=int)
    return jsonify(activity=db.get_activity_for_title(imdb_id, (req or {}).get("title"), limit=20, before_id=before))
```

- [ ] **Step 4: Run, commit**

```bash
git add library_admin.py app.py tests/test_library_admin.py
git commit -m "feat(library): per-title detail and season endpoints

Claude-Session: https://claude.ai/code/session_01F7oCy4VPeTT91GtZNTA8px"
```

---

### Task 4: Action routes

**Files:**
- Create: `library_actions.py` (the helpers behind the routes, testable without Flask)
- Modify: `app.py` (routes)
- Test: `tests/test_library_actions.py` (new)

**Interfaces:**
- Produces in `library_actions.py`: `mirror(imdb_id) -> dict`, `unmirror(imdb_id)`, `drop_retry(imdb_id)`, `retry_now(imdb_id)` (drops the retry row and starts `processor.process` in a thread, sets status pending), `recheck_series(imdb_id)` (runs `monitor._check_one_series` in a thread), `retry_episode(imdb_id, season, episode)` (`monitor.search_episode_now` in a thread), `blacklist(info_hash, note="blacklisted by admin")`, `unblacklist(info_hash)`, `reset_playability(imdb_id)`, `save_override(imdb_id, body)`, `clear_override(imdb_id)`. Every one returns `{"ok": bool, "message": str}` and never raises. Threads are started through `_spawn(target, name)` so tests can replace it.
- Routes: `POST /ui/api/library/<imdb_id>/mirror|unmirror|drop-retry|retry-now|recheck-series|playability/reset`, `POST /ui/api/library/<imdb_id>/episodes/<int:s>/<int:e>/retry`, `POST /ui/api/library/hash/<info_hash>/blacklist|unblacklist`, `POST|DELETE /ui/api/library/<imdb_id>/override`.

- [ ] **Step 1: Failing tests**

```python
"""Per-title actions behind the Library drawer. Thin wrappers over existing
helpers; each returns {ok, message} and never raises."""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db
import library_actions as act

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


@pytest.fixture
def spawned(monkeypatch):
    calls = []
    monkeypatch.setattr(act, "_spawn", lambda target, name: calls.append((target, name)))
    return calls


def test_mirror_and_unmirror_go_through_arr_sync(monkeypatch):
    import arr_sync
    rid = db.insert_request("Heat", "tt1", "movie")
    seen = []
    monkeypatch.setattr(arr_sync, "mirror_add", lambda imdb, mt, tmdb_id=None, title="": seen.append(("add", imdb, mt, title)) or True)
    monkeypatch.setattr(arr_sync, "mirror_remove", lambda imdb, mt, tmdb_id=None: seen.append(("remove", imdb, mt)) or True)
    assert act.mirror("tt1")["ok"] is True
    assert act.unmirror("tt1")["ok"] is True
    assert seen == [("add", "tt1", "movie", "Heat"), ("remove", "tt1", "movie")]
    assert act.mirror("tt404") == {"ok": False, "message": "unknown title"}


def test_drop_retry_and_retry_now(spawned):
    rid = db.insert_request("Tenet", "tt6", "movie")
    db.update_request(rid, "failed", error="x")
    db.enqueue_retry("tt6", "Tenet", "movie", None, attempt=2, delay_seconds=3600)
    assert act.drop_retry("tt6")["ok"] is True and db.get_retry_by_imdb("tt6") is None
    assert act.drop_retry("tt6")["ok"] is False
    db.enqueue_retry("tt6", "Tenet", "movie", None, attempt=2, delay_seconds=3600)
    out = act.retry_now("tt6")
    assert out["ok"] is True and db.get_retry_by_imdb("tt6") is None
    assert db.get_request_by_imdb("tt6")["status"] == "pending"
    assert spawned and spawned[0][1] == "retry-tt6"


def test_series_actions_spawn_the_monitor(spawned):
    db.insert_request("Loki", "tt4", "series")
    db.upsert_monitored_series("tt4", 100, "Loki", [1])
    assert act.recheck_series("tt4")["ok"] is True and spawned[-1][1] == "recheck-tt4"
    assert act.retry_episode("tt4", 1, 3)["ok"] is True and spawned[-1][1] == "episode-tt4-S01E03"
    assert act.recheck_series("tt404")["ok"] is False


def test_blacklist_playability_and_override():
    db.insert_request("Heat", "tt1", "movie")
    assert act.blacklist("a" * 40)["ok"] is True and ("a" * 40) in db.get_blacklisted_hashes()
    assert act.unblacklist("a" * 40)["ok"] is True and ("a" * 40) not in db.get_blacklisted_hashes()
    assert act.blacklist("short") == {"ok": False, "message": "not a valid info hash"}
    db.update_playability_fail("tt1", "x")
    assert act.reset_playability("tt1") == {"ok": True, "message": "1 record(s) reset"}
    assert act.save_override("tt1", {"quality_preference": "1080p", "allow_4k": False, "prefer_hevc": True, "notes": "n"})["ok"]
    assert db.get_show_override("tt1")["prefer_hevc"] == 1
    assert act.clear_override("tt1")["ok"] is True and db.get_show_override("tt1") is None


def test_the_routes_exist_and_delegate():
    src = _src("app.py")
    for route in ('@app.post("/ui/api/library/<imdb_id>/mirror")', '@app.post("/ui/api/library/<imdb_id>/unmirror")',
                  '@app.post("/ui/api/library/<imdb_id>/drop-retry")', '@app.post("/ui/api/library/<imdb_id>/retry-now")',
                  '@app.post("/ui/api/library/<imdb_id>/recheck-series")',
                  '@app.post("/ui/api/library/<imdb_id>/episodes/<int:season>/<int:episode>/retry")',
                  '@app.post("/ui/api/library/hash/<info_hash>/blacklist")', '@app.post("/ui/api/library/hash/<info_hash>/unblacklist")',
                  '@app.post("/ui/api/library/<imdb_id>/playability/reset")',
                  '@app.route("/ui/api/library/<imdb_id>/override", methods=["POST", "DELETE"])'):
        assert route in src, route
        body = src.split(route, 1)[1].split("\n\n\n", 1)[0]
        assert "_lib_action(" in body, route
    helper = src.split("def _lib_action", 1)[1][:400]
    assert "auth.is_admin()" in helper and "library_actions" in helper
```

- [ ] **Step 2: Run, verify failure.**

- [ ] **Step 3: `library_actions.py`**

```python
"""Per-title actions behind the Library drawer and the bulk bar. Thin
wrappers over existing helpers; each returns {ok, message}, never raises,
and starts long work on a thread through _spawn so a request returns at
once."""
from __future__ import annotations

import logging
import re
import threading

import db

log = logging.getLogger(__name__)
_HASH = re.compile(r"^[0-9a-fA-F]{40}$")


def _spawn(target, name: str) -> None:
    threading.Thread(target=target, name=name, daemon=True).start()


def _req(imdb_id: str) -> dict | None:
    return db.get_request_by_imdb(imdb_id)


def _guard(fn):
    def wrapped(*a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as exc:
            log.warning("Library action %s failed: %s", fn.__name__, exc)
            return {"ok": False, "message": f"{fn.__name__} failed: {exc.__class__.__name__}"}
    wrapped.__name__ = fn.__name__
    return wrapped


@_guard
def mirror(imdb_id: str) -> dict:
    import arr_sync
    r = _req(imdb_id)
    if not r:
        return {"ok": False, "message": "unknown title"}
    ok = arr_sync.mirror_add(imdb_id, r["media_type"], r.get("tmdb_id"), r.get("title") or "")
    return {"ok": bool(ok), "message": "mirrored into the arr" if ok else "the arr did not accept it; see the log"}


@_guard
def unmirror(imdb_id: str) -> dict:
    import arr_sync
    r = _req(imdb_id)
    if not r:
        return {"ok": False, "message": "unknown title"}
    ok = arr_sync.mirror_remove(imdb_id, r["media_type"], r.get("tmdb_id"))
    return {"ok": bool(ok), "message": "removed from the arr" if ok else "the arr did not remove it; see the log"}


@_guard
def drop_retry(imdb_id: str) -> dict:
    row = db.get_retry_by_imdb(imdb_id)
    if not row:
        return {"ok": False, "message": "not in the retry queue"}
    db.remove_retry(row["id"])
    return {"ok": True, "message": "dropped from the retry queue"}


@_guard
def retry_now(imdb_id: str) -> dict:
    import processor
    from webhook_parser import MediaRequest
    r = _req(imdb_id)
    if not r:
        return {"ok": False, "message": "unknown title"}
    row = db.get_retry_by_imdb(imdb_id)
    if row:
        db.remove_retry(row["id"])
    seasons = [int(s) for s in (r.get("seasons") or "").split(",") if s.strip().isdigit()]
    req = MediaRequest(title=r["title"], media_type=r["media_type"], imdb_id=imdb_id, seasons=seasons,
                       tmdb_id=r.get("tmdb_id"))
    db.update_request(r["id"], "pending")
    _spawn(lambda: processor.process(req), f"retry-{imdb_id}")
    return {"ok": True, "message": "retry started"}


@_guard
def recheck_series(imdb_id: str) -> dict:
    import monitor
    series = db.get_monitored_series_by_imdb(imdb_id)
    if not series:
        return {"ok": False, "message": "not a monitored series"}
    _spawn(lambda: monitor._check_one_series(series), f"recheck-{imdb_id}")
    return {"ok": True, "message": "series check started"}


@_guard
def retry_episode(imdb_id: str, season: int, episode: int) -> dict:
    import monitor
    r = _req(imdb_id)
    if not r:
        return {"ok": False, "message": "unknown title"}
    _spawn(lambda: monitor.search_episode_now(imdb_id, r["title"], season, episode),
           f"episode-{imdb_id}-S{season:02d}E{episode:02d}")
    return {"ok": True, "message": f"searching S{season:02d}E{episode:02d}"}


@_guard
def blacklist(info_hash: str, note: str = "blacklisted by admin") -> dict:
    if not _HASH.match(info_hash or ""):
        return {"ok": False, "message": "not a valid info hash"}
    db.blacklist_hash(info_hash.lower(), note)
    return {"ok": True, "message": "hash blacklisted"}


@_guard
def unblacklist(info_hash: str) -> dict:
    if not _HASH.match(info_hash or ""):
        return {"ok": False, "message": "not a valid info hash"}
    db.clear_failed_hash(info_hash.lower())
    return {"ok": True, "message": "hash cleared"}


@_guard
def reset_playability(imdb_id: str) -> dict:
    n = db.reset_playability_for_title(imdb_id)
    return {"ok": True, "message": f"{n} record(s) reset"}


@_guard
def save_override(imdb_id: str, body: dict) -> dict:
    if not _req(imdb_id):
        return {"ok": False, "message": "unknown title"}
    def _b(v):
        return None if v is None else bool(v)
    db.upsert_show_override(imdb_id, (body.get("quality_preference") or None), _b(body.get("allow_4k")),
                            _b(body.get("prefer_hevc")), (body.get("notes") or None))
    return {"ok": True, "message": "override saved"}


@_guard
def clear_override(imdb_id: str) -> dict:
    db.delete_show_override(imdb_id)
    return {"ok": True, "message": "override cleared"}
```

`MediaRequest` is a dataclass in `webhook_parser.py` (`title, media_type, imdb_id, seasons=[], episode=None, tmdb_id=None, seerr_request_id=None`); `processor.process(req, _retry_attempt=0)`. `arr_sync.mirror_add(imdb_id, media_type, tmdb_id=None, title="") -> bool` and `mirror_remove(imdb_id, media_type, tmdb_id=None) -> bool` exist. `monitor._check_one_series(series: dict)` and `monitor.search_episode_now(imdb_id, title, season, episode) -> bool` exist. Check whether the rest of the code lower-cases hashes before `db.blacklist_hash`; keep the `.lower()` if so.

- [ ] **Step 4: Routes** (after the detail routes)

```python
def _lib_action(fn, *args):
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import library_actions
    return jsonify(**getattr(library_actions, fn)(*args))


@app.post("/ui/api/library/<imdb_id>/mirror")
def ui_api_library_mirror(imdb_id: str):
    return _lib_action("mirror", imdb_id)


@app.post("/ui/api/library/<imdb_id>/unmirror")
def ui_api_library_unmirror(imdb_id: str):
    return _lib_action("unmirror", imdb_id)


@app.post("/ui/api/library/<imdb_id>/drop-retry")
def ui_api_library_drop_retry(imdb_id: str):
    return _lib_action("drop_retry", imdb_id)


@app.post("/ui/api/library/<imdb_id>/retry-now")
def ui_api_library_retry_now(imdb_id: str):
    return _lib_action("retry_now", imdb_id)


@app.post("/ui/api/library/<imdb_id>/recheck-series")
def ui_api_library_recheck_series(imdb_id: str):
    return _lib_action("recheck_series", imdb_id)


@app.post("/ui/api/library/<imdb_id>/episodes/<int:season>/<int:episode>/retry")
def ui_api_library_retry_episode(imdb_id: str, season: int, episode: int):
    return _lib_action("retry_episode", imdb_id, season, episode)


@app.post("/ui/api/library/hash/<info_hash>/blacklist")
def ui_api_library_blacklist(info_hash: str):
    return _lib_action("blacklist", info_hash)


@app.post("/ui/api/library/hash/<info_hash>/unblacklist")
def ui_api_library_unblacklist(info_hash: str):
    return _lib_action("unblacklist", info_hash)


@app.post("/ui/api/library/<imdb_id>/playability/reset")
def ui_api_library_reset_playability(imdb_id: str):
    return _lib_action("reset_playability", imdb_id)


@app.route("/ui/api/library/<imdb_id>/override", methods=["POST", "DELETE"])
def ui_api_library_override(imdb_id: str):
    if request.method == "DELETE":
        return _lib_action("clear_override", imdb_id)
    return _lib_action("save_override", imdb_id, request.get_json(silent=True) or {})
```

- [ ] **Step 5: Run, mutation-check, commit**

Mutation: make `blacklist()` skip the hash validity check: its test must fail. Restore.

```bash
git add library_actions.py app.py tests/test_library_actions.py
git commit -m "feat(library): per-title action routes

Claude-Session: https://claude.ai/code/session_01F7oCy4VPeTT91GtZNTA8px"
```

---

### Task 5: Frontend: types, API, rail, filters, table, paging, hash state

**Files:**
- Modify: `frontend/src/api.ts`, `frontend/src/pages/admin/AdminLayout.tsx` (hash parsing and the Library tab)
- Create: `frontend/src/pages/admin/library/state.ts`, `Rail.tsx`, `TitleTable.tsx`, `frontend/src/pages/admin/Library.tsx`
- Test: `frontend/src/pages/admin/library/state.test.ts`, `frontend/src/pages/admin/Library.test.tsx`

**Interfaces:**
- `api.ts`: `LibraryRow` (the Task 2 row shape), `LibraryPage {rows, total, page, per_page}`, `api.library(params: Record<string,string|string[]>)`, `api.libraryViews(): Promise<Record<string, number>>`.
- `state.ts`: `type LibraryState = { view: string; q: string; status: string[]; type: string; problem: string; requester: string; added: string; sort: string; order: 'asc'|'desc'; page: number; perPage: number; open: string | null }`; `DEFAULT_STATE`; `parseHash(hash: string): LibraryState`; `toHash(s: LibraryState): string` (`#library?view=...&q=...`); `toQuery(s): Record<string, string|string[]>`.
- `AdminLayout.tsx`: the active tab is the hash up to `?`: `location.hash.replace(/^#/, '').split('?')[0]`.
- `Library.tsx` default export; `Rail({ state, counts, users, onChange })`; `TitleTable({ rows, sort, order, onSort, selected, onSelect, onOpen })`.

- [ ] **Step 1: `api.ts`**

```ts
export interface LibraryRow {
  id: number; imdb_id: string; tmdb_id: number | null; title: string; media_type: string;
  status: string; error: string | null; quality: string | null; source: string | null;
  info_hash: string | null; seasons: string | null; created_at: string; updated_at: string;
  requester: string; requester_id: number | null; requested_at: string | null;
  playability: { status: string; last_fail_reason: string | null } | null;
  missing_episodes: number; retry: { attempt: number; next_retry_at: string } | null;
  arr_mirrored: boolean; in_torbox: boolean; in_wanted_movies: boolean;
}
export interface LibraryPage { rows: LibraryRow[]; total: number; page: number; per_page: number }
```

and in the `api` object:

```ts
  library: (params: Record<string, string | string[]>) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => (Array.isArray(v) ? v : [v]).forEach((x) => x !== '' && qs.append(k, x)));
    return http<LibraryPage>(`/ui/api/library?${qs.toString()}`);
  },
  libraryViews: () => http<Record<string, number>>('/ui/api/library/views'),
```

- [ ] **Step 2: Failing `state.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import { DEFAULT_STATE, parseHash, toHash, toQuery } from './state';

describe('library hash state', () => {
  it('round-trips through the hash and drops defaults', () => {
    const s = { ...DEFAULT_STATE, view: 'attention', q: 'heat', status: ['failed', 'wanted'], page: 3, open: 'tt1' };
    const h = toHash(s);
    expect(h).toBe('#library?view=attention&q=heat&status=failed%2Cwanted&page=3&open=tt1');
    expect(parseHash(h)).toEqual(s);
    expect(toHash(DEFAULT_STATE)).toBe('#library');
    expect(parseHash('#library')).toEqual(DEFAULT_STATE);
    expect(parseHash('#settings')).toEqual(DEFAULT_STATE);
  });
  it('ignores junk and clamps the page', () => {
    expect(parseHash('#library?view=bogus&page=-2&order=sideways').view).toBe('all');
    expect(parseHash('#library?page=-2').page).toBe(1);
    expect(parseHash('#library?order=sideways').order).toBe('desc');
  });
  it('turns state into query params with statuses repeated', () => {
    expect(toQuery({ ...DEFAULT_STATE, status: ['failed', 'wanted'], q: 'x' })).toEqual({
      view: 'all', q: 'x', status: ['failed', 'wanted'], type: '', problem: '', requester: '', added: '',
      sort: '', order: 'desc', page: '1', per_page: '50',
    });
  });
});
```

- [ ] **Step 3: `state.ts`**

```ts
export const VIEWS = ['all', 'attention', 'wanted', 'queue', 'incomplete', 'unmirrored'] as const;
export const STATUSES = ['success', 'wanted', 'upcoming', 'failed', 'pending'] as const;
export const PROBLEMS = ['failed', 'wanted', 'unplayable', 'missing_episodes', 'in_retry_queue', 'no_requester', 'not_mirrored'] as const;
export const SORTS = ['title', 'status', 'requester', 'updated', 'created'] as const;

export type LibraryState = {
  view: string; q: string; status: string[]; type: string; problem: string; requester: string; added: string;
  sort: string; order: 'asc' | 'desc'; page: number; perPage: number; open: string | null;
};

export const DEFAULT_STATE: LibraryState = {
  view: 'all', q: '', status: [], type: '', problem: '', requester: '', added: '',
  sort: '', order: 'desc', page: 1, perPage: 50, open: null,
};

export function parseHash(hash: string): LibraryState {
  const [tab, query = ''] = hash.replace(/^#/, '').split('?');
  if (tab !== 'library') return { ...DEFAULT_STATE };
  const p = new URLSearchParams(query);
  const pick = (k: string, allowed: readonly string[]) => (allowed.includes(p.get(k) || '') ? (p.get(k) as string) : '');
  const page = parseInt(p.get('page') || '1', 10);
  const perPage = parseInt(p.get('per_page') || '50', 10);
  return {
    view: pick('view', VIEWS) || 'all',
    q: p.get('q') || '',
    status: (p.get('status') || '').split(',').filter((s) => (STATUSES as readonly string[]).includes(s)),
    type: pick('type', ['movie', 'series']),
    problem: pick('problem', PROBLEMS),
    requester: p.get('requester') || '',
    added: pick('added', ['24h', '7d', '30d']),
    sort: pick('sort', SORTS),
    order: p.get('order') === 'asc' ? 'asc' : 'desc',
    page: Number.isFinite(page) && page > 0 ? page : 1,
    perPage: [25, 50, 100, 200].includes(perPage) ? perPage : 50,
    open: p.get('open') || null,
  };
}

export function toHash(s: LibraryState): string {
  const p = new URLSearchParams();
  if (s.view !== 'all') p.set('view', s.view);
  if (s.q) p.set('q', s.q);
  if (s.status.length) p.set('status', s.status.join(','));
  if (s.type) p.set('type', s.type);
  if (s.problem) p.set('problem', s.problem);
  if (s.requester) p.set('requester', s.requester);
  if (s.added) p.set('added', s.added);
  if (s.sort) { p.set('sort', s.sort); if (s.order !== 'desc') p.set('order', s.order); }
  if (s.page !== 1) p.set('page', String(s.page));
  if (s.perPage !== 50) p.set('per_page', String(s.perPage));
  if (s.open) p.set('open', s.open);
  const q = p.toString();
  return q ? `#library?${q}` : '#library';
}

export function toQuery(s: LibraryState): Record<string, string | string[]> {
  return {
    view: s.view, q: s.q, status: s.status, type: s.type, problem: s.problem, requester: s.requester,
    added: s.added, sort: s.sort, order: s.order, page: String(s.page), per_page: String(s.perPage),
  };
}
```

- [ ] **Step 4: Failing `Library.test.tsx`**

```tsx
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { LibraryRow } from '../../api';
import Library from './Library';

const apiMocks = vi.hoisted(() => ({
  library: vi.fn(), libraryViews: vi.fn(), users: vi.fn(), libraryDetail: vi.fn(),
}));
vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return { ...actual, api: { ...actual.api, ...apiMocks } };
});

const row = (over: Partial<LibraryRow>): LibraryRow => ({
  id: 1, imdb_id: 'tt1', tmdb_id: null, title: 'Heat', media_type: 'movie', status: 'success', error: null,
  quality: '1080p', source: 'WEB-DL', info_hash: 'a'.repeat(40), seasons: null, created_at: '2026-09-01 10:00:00',
  updated_at: '2026-09-02 10:00:00', requester: 'adam', requester_id: 1, requested_at: '2026-09-01 09:00:00',
  playability: null, missing_episodes: 0, retry: null, arr_mirrored: true, in_torbox: true, in_wanted_movies: false,
  ...over,
});

function renderIt(hash = '#library') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter initialEntries={[`/admin${hash}`]}>
      <QueryClientProvider client={qc}><Library /></QueryClientProvider>
    </MemoryRouter>,
  );
}

describe('Library tab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.libraryViews.mockResolvedValue({ all: 2, attention: 1, wanted: 0, queue: 1, incomplete: 0, unmirrored: 0 });
    apiMocks.users.mockResolvedValue({ users: [{ id: 1, username: 'adam' }] });
    apiMocks.library.mockResolvedValue({
      rows: [row({}), row({ id: 2, imdb_id: 'tt2', title: 'Alien', status: 'failed', error: 'no release', requester: 'auto',
        playability: { status: 'degraded', last_fail_reason: 'cdn 404' }, retry: { attempt: 3, next_retry_at: '2026-09-03 00:00:00' },
        arr_mirrored: false, in_torbox: false })],
      total: 2, page: 1, per_page: 50,
    });
  });

  it('renders views with counts, the table with badges, and requests the default query', async () => {
    renderIt();
    const nav = await screen.findByRole('navigation', { name: 'Library views' });
    expect(within(nav).getByRole('button', { name: /Needs attention/ })).toHaveTextContent('1');
    expect(await screen.findByText('Heat')).toBeInTheDocument();
    expect(screen.getByText('no release')).toBeInTheDocument();
    const alien = screen.getByText('Alien').closest('tr')!;
    expect(within(alien).getByTitle('cdn 404')).toBeInTheDocument();
    expect(within(alien).getByTitle('retry attempt 3')).toBeInTheDocument();
    expect(within(screen.getByText('Heat').closest('tr')!).getByTitle('mirrored in the arr')).toBeInTheDocument();
    expect(apiMocks.library).toHaveBeenCalledWith(expect.objectContaining({ view: 'all', page: '1', per_page: '50' }));
  });

  it('a view click and a filter change re-query and update the hash', async () => {
    renderIt();
    await userEvent.click(await screen.findByRole('button', { name: /Needs attention/ }));
    await waitFor(() => expect(apiMocks.library).toHaveBeenLastCalledWith(expect.objectContaining({ view: 'attention' })));
    expect(window.location.hash || screen.getByTestId('library-hash').textContent).toContain('view=attention');
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Type' }), 'series');
    await waitFor(() => expect(apiMocks.library).toHaveBeenLastCalledWith(expect.objectContaining({ view: 'attention', type: 'series', page: '1' })));
  });

  it('restores state from the hash and pages', async () => {
    apiMocks.library.mockResolvedValue({ rows: [row({})], total: 120, page: 2, per_page: 50 });
    renderIt('#library?view=wanted&page=2');
    await waitFor(() => expect(apiMocks.library).toHaveBeenCalledWith(expect.objectContaining({ view: 'wanted', page: '2' })));
    expect(await screen.findByText(/51 to 100 of 120/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Next page' }));
    await waitFor(() => expect(apiMocks.library).toHaveBeenLastCalledWith(expect.objectContaining({ page: '3' })));
  });

  it('sorts by clicking a header and selects rows', async () => {
    renderIt();
    await screen.findByText('Heat');
    await userEvent.click(screen.getByRole('button', { name: 'Sort by title' }));
    await waitFor(() => expect(apiMocks.library).toHaveBeenLastCalledWith(expect.objectContaining({ sort: 'title', order: 'asc' })));
    await userEvent.click(screen.getByRole('checkbox', { name: 'Select Heat' }));
    expect(screen.getByText('1 selected')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Select all on this page' }));
    expect(screen.getByText('2 selected')).toBeInTheDocument();
  });
});
```

The hash assertion uses a `data-testid="library-hash"` hidden span that renders the current `toHash(state)`, so the test does not depend on `MemoryRouter`'s hash handling. Keep that span in `Library.tsx` (it is also handy when debugging).

- [ ] **Step 5: Components**

`Rail.tsx`:

```tsx
import { Button, MultiSelect, Select } from '../../../components/primitives';
import { PROBLEMS, STATUSES, VIEWS } from './state';
import type { LibraryState } from './state';

const VIEW_LABEL: Record<string, string> = {
  all: 'All', attention: 'Needs attention', wanted: 'Wanted', queue: 'Queue', incomplete: 'Incomplete series', unmirrored: 'Unmirrored',
};
const STATUS_LABEL: Record<string, string> = { success: 'In library', wanted: 'Wanted', upcoming: 'Upcoming', failed: 'Failed', pending: 'Processing' };
const PROBLEM_LABEL: Record<string, string> = {
  failed: 'Failed', wanted: 'Wanted', unplayable: 'Unplayable', missing_episodes: 'Missing episodes',
  in_retry_queue: 'In retry queue', no_requester: 'No requester', not_mirrored: 'Not mirrored',
};

export function Rail({ state, counts, users, mirrorOn, onChange }: {
  state: LibraryState; counts: Record<string, number>; users: { id: number; username: string }[];
  mirrorOn: boolean; onChange: (patch: Partial<LibraryState>) => void;
}) {
  const views = VIEWS.filter((v) => v !== 'unmirrored' || mirrorOn);
  return (
    <aside className="space-y-4">
      <nav aria-label="Library views" className="space-y-0.5">
        {views.map((v) => (
          <button key={v} type="button" onClick={() => onChange({ view: v, page: 1 })} aria-current={state.view === v ? 'page' : undefined}
            className={`flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-sm ${state.view === v ? 'bg-white/[0.08] text-white' : 'text-muted hover:text-body'}`}>
            <span>{VIEW_LABEL[v]}</span>
            <span className="text-xs text-muted">{counts[v] ?? ''}</span>
          </button>
        ))}
      </nav>
      <div className="space-y-2">
        <input type="search" aria-label="Search titles" placeholder="Title, imdb id or hash" value={state.q}
          onChange={(e) => onChange({ q: e.target.value, page: 1 })} className="w-full rounded border border-border bg-bg px-2 py-1.5 text-xs" />
        <Select label="Type" value={state.type} placeholder="Any type" onChange={(v) => onChange({ type: v, page: 1 })}
          options={[{ value: 'movie', label: 'Movies' }, { value: 'series', label: 'Series' }]} className="w-full" />
        <MultiSelect label="Status" value={state.status} onChange={(v) => onChange({ status: v, page: 1 })}
          options={STATUSES.map((s) => ({ value: s, label: STATUS_LABEL[s] }))} />
        <Select label="Problem" value={state.problem} placeholder="Any problem" onChange={(v) => onChange({ problem: v, page: 1 })}
          options={PROBLEMS.map((p) => ({ value: p, label: PROBLEM_LABEL[p] }))} className="w-full" />
        <Select label="Requester" value={state.requester} placeholder="Anyone" onChange={(v) => onChange({ requester: v, page: 1 })}
          options={[{ value: 'auto', label: 'Automatic' }, ...users.map((u) => ({ value: String(u.id), label: u.username }))]} className="w-full" />
        <Select label="Added" value={state.added} placeholder="Any time" onChange={(v) => onChange({ added: v, page: 1 })}
          options={[{ value: '24h', label: 'Last 24 hours' }, { value: '7d', label: 'Last 7 days' }, { value: '30d', label: 'Last 30 days' }]} className="w-full" />
        {(state.q || state.type || state.status.length || state.problem || state.requester || state.added) ? (
          <Button variant="ghost" onClick={() => onChange({ q: '', type: '', status: [], problem: '', requester: '', added: '', page: 1 })}>Clear filters</Button>
        ) : null}
      </div>
    </aside>
  );
}
```

`TitleTable.tsx`:

```tsx
import type { LibraryRow } from '../../../api';
import { Pill, statusLabel, statusToPillState } from '../../../components/primitives';

function Badge({ title, tone, children }: { title: string; tone: 'danger' | 'warn' | 'ok' | 'muted'; children: React.ReactNode }) {
  const cls = { danger: 'bg-danger/20 text-danger', warn: 'bg-warn/20 text-warn', ok: 'bg-ok/20 text-ok', muted: 'bg-white/10 text-muted' }[tone];
  return <span title={title} className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${cls}`}>{children}</span>;
}

export function TitleTable({ rows, sort, order, onSort, selected, onSelect, onSelectAll, onOpen, loading }: {
  rows: LibraryRow[]; sort: string; order: 'asc' | 'desc'; onSort: (col: string) => void;
  selected: Set<string>; onSelect: (imdb: string, on: boolean) => void; onSelectAll: (on: boolean) => void;
  onOpen: (imdb: string) => void; loading: boolean;
}) {
  const header = (key: string, label: string) => (
    <th className="px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wider text-muted">
      <button type="button" aria-label={`Sort by ${label.toLowerCase()}`} onClick={() => onSort(key)} className="hover:text-body">
        {label}{sort === key ? (order === 'asc' ? ' ↑' : ' ↓') : ''}
      </button>
    </th>
  );
  const allOn = rows.length > 0 && rows.every((r) => selected.has(r.imdb_id));
  return (
    <div className={`overflow-x-auto rounded-xl border border-border ${loading ? 'opacity-60' : ''}`}>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border">
            <th className="px-3 py-2"><input type="checkbox" aria-label="Select all on this page" checked={allOn} onChange={(e) => onSelectAll(e.target.checked)} /></th>
            {header('title', 'Title')}{header('status', 'Status')}
            <th className="px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wider text-muted">Release</th>
            {header('requester', 'Requester')}
            <th className="px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wider text-muted">Flags</th>
            {header('updated', 'Updated')}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.imdb_id} className="cursor-pointer border-b border-border last:border-0 hover:bg-white/[0.03]" onClick={() => onOpen(r.imdb_id)}>
              <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                <input type="checkbox" aria-label={`Select ${r.title}`} checked={selected.has(r.imdb_id)} onChange={(e) => onSelect(r.imdb_id, e.target.checked)} />
              </td>
              <td className="px-3 py-2">
                <div className="font-medium">{r.media_type === 'movie' ? '\u{1F3AC}' : '\u{1F4FA}'} {r.title}</div>
                <div className="font-mono text-[10px] text-muted">{r.imdb_id}</div>
              </td>
              <td className="px-3 py-2">
                <Pill state={statusToPillState(r.status)}>{statusLabel(r.status)}</Pill>
                {r.error && <div className="mt-1 max-w-xs truncate text-[11px] text-muted" title={r.error}>{r.error}</div>}
              </td>
              <td className="px-3 py-2 font-mono text-[11px] text-muted">{[r.quality, r.source].filter(Boolean).join(' ')}</td>
              <td className="px-3 py-2 text-xs">{r.requester}</td>
              <td className="space-x-1 px-3 py-2">
                {r.playability && <Badge title={r.playability.last_fail_reason || r.playability.status} tone={r.playability.status === 'degraded' ? 'danger' : 'warn'}>play</Badge>}
                {r.missing_episodes > 0 && <Badge title={`${r.missing_episodes} missing episodes`} tone="warn">{r.missing_episodes} missing</Badge>}
                {r.retry && <Badge title={`retry attempt ${r.retry.attempt}`} tone="warn">retry {r.retry.attempt}</Badge>}
                {r.arr_mirrored && <Badge title="mirrored in the arr" tone="ok">arr</Badge>}
                {r.in_torbox && <Badge title="in TorBox" tone="muted">tb</Badge>}
              </td>
              <td className="px-3 py-2 text-xs text-muted">{r.updated_at.slice(0, 16)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

`Library.tsx`:

```tsx
import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api';
import { Button, Select } from '../../components/primitives';
import { Rail } from './library/Rail';
import { TitleTable } from './library/TitleTable';
import { parseHash, toHash, toQuery } from './library/state';
import type { LibraryState } from './library/state';

export default function Library() {
  const location = useLocation();
  const navigate = useNavigate();
  const [state, setState] = useState<LibraryState>(() => parseHash(location.hash));
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const query = useMemo(() => toQuery(state), [state]);
  const page = useQuery({ queryKey: ['library', query], queryFn: () => api.library(query), placeholderData: (p) => p });
  const counts = useQuery({ queryKey: ['library-views'], queryFn: api.libraryViews });
  const users = useQuery({ queryKey: ['users'], queryFn: api.users });

  useEffect(() => { navigate({ hash: toHash(state) }, { replace: true }); }, [state, navigate]);
  const update = (patch: Partial<LibraryState>) => setState((s) => ({ ...s, ...patch }));
  const onSort = (col: string) => update({ sort: col, order: state.sort === col && state.order === 'asc' ? 'desc' : 'asc', page: 1 });

  const rows = page.data?.rows || [];
  const total = page.data?.total || 0;
  const first = (state.page - 1) * state.perPage + 1;
  const last = Math.min(total, state.page * state.perPage);
  const mirrorOn = (counts.data?.unmirrored ?? 0) > 0 || rows.some((r) => r.arr_mirrored);

  return (
    <div className="grid gap-6 pb-24 md:grid-cols-[14rem_1fr]">
      <span data-testid="library-hash" hidden>{toHash(state)}</span>
      <Rail state={state} counts={counts.data || {}} users={users.data?.users || []} mirrorOn={mirrorOn} onChange={update} />
      <main className="space-y-3">
        <TitleTable rows={rows} sort={state.sort} order={state.order} onSort={onSort} selected={selected} loading={page.isFetching}
          onSelect={(id, on) => setSelected((s) => { const n = new Set(s); on ? n.add(id) : n.delete(id); return n; })}
          onSelectAll={(on) => setSelected(on ? new Set(rows.map((r) => r.imdb_id)) : new Set())}
          onOpen={(id) => update({ open: id })} />
        {!rows.length && !page.isFetching && (
          <p className="text-sm text-muted">Nothing here. {EMPTY[state.view] || ''}</p>
        )}
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
          <span>{total ? `${first} to ${last} of ${total}` : ''}</span>
          <div className="flex items-center gap-2">
            <Select label="Rows per page" value={String(state.perPage)} onChange={(v) => update({ perPage: Number(v), page: 1 })}
              options={[25, 50, 100, 200].map((n) => ({ value: String(n), label: `${n} per page` }))} />
            <Button aria-label="Previous page" disabled={state.page <= 1} onClick={() => update({ page: state.page - 1 })}>Prev</Button>
            <Button aria-label="Next page" disabled={last >= total} onClick={() => update({ page: state.page + 1 })}>Next</Button>
          </div>
        </div>
        {selected.size > 0 && <div className="fixed inset-x-0 bottom-0 z-10 border-t border-border bg-bg/95 px-4 py-3 text-sm backdrop-blur">{selected.size} selected</div>}
      </main>
    </div>
  );
}

const EMPTY: Record<string, string> = {
  attention: 'Titles land here when they failed, stopped playing, or retried three times.',
  wanted: 'Released titles with no release yet, and titles not out yet.',
  queue: 'Titles the processor is working on, waiting to retry, or still hunting episodes for.',
  incomplete: 'Series with episodes still wanted.',
  unmirrored: 'Titles in the library that Radarr or Sonarr do not have yet.',
};
```

The `selected` action bar is a placeholder line here; Task 8 replaces it with `ActionBar`. `api.users()` returns `{ users: UserRecord[] }` (the Users tab uses it under the `users` query key).

`AdminLayout.tsx`: change `const hashId = location.hash.replace(/^#/, '');` to `const hashId = location.hash.replace(/^#/, '').split('?')[0];` and add `{ id: 'library', label: 'Library', component: Library }` after Overview.

- [ ] **Step 6: Run, build, commit**

`npx tsc --noEmit && npx vitest run && npm run build`; commit source plus `static/app/`.

```bash
git add frontend/src static/app
git commit -m "feat(ui): Library tab with views, filters, sortable table and paging

Claude-Session: https://claude.ai/code/session_01F7oCy4VPeTT91GtZNTA8px"
```

---

### Task 6: Drawer shell with Status, Release and Playability cards

**Files:**
- Modify: `frontend/src/api.ts` (`LibraryDetail`, `libraryDetail`, `libraryAction`), `frontend/src/pages/admin/Library.tsx` (mount the drawer when `state.open`)
- Create: `frontend/src/pages/admin/library/TitleDrawer.tsx`, `library/cards/DrawerCard.tsx`, `cards/StatusCard.tsx`, `cards/ReleaseCard.tsx`, `cards/PlayabilityCard.tsx`, `library/actions.ts`
- Test: `frontend/src/pages/admin/library/TitleDrawer.test.tsx`

**Interfaces:**
- `api.ts`: `LibraryDetail` typed after Task 3's payload; `api.libraryDetail(imdb)`, `api.libraryAction(path: string, method?: 'POST'|'DELETE', body?: unknown): Promise<{ok: boolean; message: string}>`, `api.retryRequest(id)` (exists), `api.purgeRequest(id)` (exists), `api.reResolve(token)` (exists or add).
- `actions.ts`: `ACTIONS` map name to `{ label, run(detail): Promise<{ok, message}>, confirm?: string }` for `retry, reresolve, mirror, purge, blacklistCurrent, dropRetry, retryNow, resetPlayability`.
- `DrawerCard({ title, description?, children, actions? })`: uppercase small title, muted description, children, and an inline result line component `ActionButton({ label, run, onDone })` that shows the `{ok, message}` result next to the button.
- `TitleDrawer({ imdb, onClose, onChanged })`.

- [ ] **Step 1: Failing test**

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { TitleDrawer } from './TitleDrawer';

const apiMocks = vi.hoisted(() => ({ libraryDetail: vi.fn(), libraryAction: vi.fn(), retryRequest: vi.fn(), purgeRequest: vi.fn(), reResolve: vi.fn() }));
vi.mock('../../../api', async () => {
  const actual = await vi.importActual<typeof import('../../../api')>('../../../api');
  return { ...actual, api: { ...actual.api, ...apiMocks } };
});

const detail = (over: Record<string, unknown> = {}) => ({
  request: { id: 1, imdb_id: 'tt1', title: 'Heat', media_type: 'movie', status: 'failed', error: 'no release', quality: null, source: null,
    info_hash: 'a'.repeat(40), seasons: null, created_at: '2026-09-01 10:00:00', updated_at: '2026-09-02 10:00:00', tmdb_id: 949, arr_mirrored_at: null },
  items: [{ token: 'tok', info_hash: 'a'.repeat(40), strm_path: '/media/movies/Heat (1995)/Heat (1995).strm', torbox_id: 5, last_played: null, play_count: 0, season: null, episode: null, debrid_provider: 'torbox', quality: '1080p' }],
  playability: [{ content_key: 'tt1', status: 'degraded', last_ok_provider: null, last_ok_at: null, last_fail_reason: 'cdn 404', consecutive_failures: 2, updated_at: '2026-09-02 10:00:00' }],
  episodes: null, monitored: null, retry: { id: 3, attempt: 2, next_retry_at: '2026-09-03 00:00:00' }, wanted_movie: null,
  user_requests: [], seerr_request_id: null, override: null, hashes: [], activity: [], arr: { mirrored_at: null },
  ...over,
});

function renderIt() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onClose = vi.fn(); const onChanged = vi.fn();
  render(<QueryClientProvider client={qc}><TitleDrawer imdb="tt1" onClose={onClose} onChanged={onChanged} /></QueryClientProvider>);
  return { onClose, onChanged };
}

describe('TitleDrawer', () => {
  beforeEach(() => { vi.clearAllMocks(); apiMocks.libraryDetail.mockResolvedValue(detail()); });

  it('shows the header, the status, release and playability cards, and hides empty ones', async () => {
    renderIt();
    expect(await screen.findByRole('heading', { name: /Heat/ })).toBeInTheDocument();
    expect(screen.getByText('no release')).toBeInTheDocument();
    expect(screen.getByText(/attempt 2/)).toBeInTheDocument();
    expect(screen.getByText('/media/movies/Heat (1995)/Heat (1995).strm')).toBeInTheDocument();
    expect(screen.getByText('cdn 404')).toBeInTheDocument();
    expect(screen.queryByText('Requests')).not.toBeInTheDocument();
    expect(screen.queryByText('Preferences')).not.toBeInTheDocument();
  });

  it('runs an action, shows its message and refetches', async () => {
    apiMocks.libraryAction.mockResolvedValue({ ok: true, message: 'dropped from the retry queue' });
    const { onChanged } = renderIt();
    await userEvent.click(await screen.findByRole('button', { name: 'Drop from queue' }));
    await waitFor(() => expect(apiMocks.libraryAction).toHaveBeenCalledWith('/ui/api/library/tt1/drop-retry'));
    expect(await screen.findByText('dropped from the retry queue')).toBeInTheDocument();
    await waitFor(() => expect(apiMocks.libraryDetail).toHaveBeenCalledTimes(2));
    expect(onChanged).toHaveBeenCalled();
  });

  it('Retry uses the request route, Purge asks first, Escape closes', async () => {
    apiMocks.retryRequest.mockResolvedValue({ ok: true, title: 'Heat' });
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    const { onClose } = renderIt();
    await userEvent.click(await screen.findByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(apiMocks.retryRequest).toHaveBeenCalledWith(1));
    await userEvent.click(screen.getByRole('button', { name: 'Purge' }));
    expect(apiMocks.purgeRequest).not.toHaveBeenCalled();
    await userEvent.keyboard('{Escape}');
    expect(onClose).toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Implement**

`api.ts` additions:

```ts
export interface LibraryDetail {
  request: RequestRow & { tmdb_id: number | null; arr_mirrored_at: string | null };
  items: { token: string; info_hash: string; strm_path: string | null; torbox_id: number | null; last_played: string | null;
    play_count: number; season: number | null; episode: number | null; debrid_provider: string | null; quality: string | null }[];
  playability: { content_key: string; status: string; last_ok_provider: string | null; last_ok_at: string | null;
    last_fail_reason: string | null; consecutive_failures: number; updated_at: string }[];
  episodes: { season: number; present: number; wanted: number }[] | null;
  monitored: { status: string; last_checked: string | null; seasons: string | null } | null;
  retry: { id: number; attempt: number; next_retry_at: string } | null;
  wanted_movie: { reason: string | null; attempts: number; last_checked: string | null } | null;
  user_requests: { id: number; username: string; status: string; reviewer: string | null; note: string | null; created_at: string; reviewed_at: string | null }[];
  seerr_request_id: number | null;
  override: { quality_preference: string | null; allow_4k: number | null; prefer_hevc: number | null; notes: string | null } | null;
  hashes: { info_hash: string; blacklisted: boolean; fail_count: number; last_error: string | null; current: boolean }[];
  activity: { id: number; event: string; title: string | null; message: string | null; success: number; created_at: string }[];
  arr: { mirrored_at: string | null };
}
export interface SeasonEpisode { season: number; episode: number; present: boolean; strm_path: string | null; token: string | null;
  wanted_status: string | null; attempt_count: number; air_date: string | null; last_attempted: string | null }
```

and in `api`:

```ts
  libraryDetail: (imdb: string) => http<LibraryDetail>(`/ui/api/library/${imdb}`),
  librarySeason: (imdb: string, season: number) => http<{ episodes: SeasonEpisode[] }>(`/ui/api/library/${imdb}/season/${season}`),
  libraryActivity: (imdb: string, before: number) => http<{ activity: LibraryDetail['activity'] }>(`/ui/api/library/${imdb}/activity?before=${before}`),
  libraryAction: (path: string, method: 'POST' | 'DELETE' = 'POST', body?: unknown) =>
    http<{ ok: boolean; message: string }>(path, { method, body: body === undefined ? undefined : JSON.stringify(body) }),
```

`api.retryRequest(id) -> {ok, title?}`, `api.purgeRequest(id) -> {ok, strms}` and `api.reResolve(token) -> {ok, resolved, title?, hint?}` already exist in `api.ts`.

`cards/DrawerCard.tsx`:

```tsx
import { useState } from 'react';
import { Button } from '../../../../components/primitives';

export function DrawerCard({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <h3 className="text-[11px] font-semibold uppercase tracking-widest text-muted">{title}</h3>
      {description && <p className="mt-0.5 text-xs text-muted">{description}</p>}
      <div className="mt-3 space-y-2 text-sm">{children}</div>
    </section>
  );
}

export function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[7rem_1fr] gap-2 text-xs">
      <span className="text-muted">{label}</span>
      <span className="break-all">{children}</span>
    </div>
  );
}

/** A button whose result line appears next to it, the way Settings' Test buttons work. */
export function ActionButton({ label, run, onDone, variant = 'default', confirm }: {
  label: string; run: () => Promise<{ ok: boolean; message: string }>; onDone?: () => void;
  variant?: 'default' | 'primary' | 'ghost'; confirm?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const go = async () => {
    if (confirm && !window.confirm(confirm)) return;
    setBusy(true);
    try {
      const r = await run();
      setMsg({ ok: r.ok, text: r.message });
      if (r.ok) onDone?.();
    } catch (e: any) {
      setMsg({ ok: false, text: e.message });
    } finally {
      setBusy(false);
    }
  };
  return (
    <span className="inline-flex items-center gap-2">
      <Button variant={variant} onClick={go} loading={busy} loadingLabel="Working...">{label}</Button>
      {msg && <span className={`text-xs ${msg.ok ? 'text-ok' : 'text-danger'}`}>{msg.text}</span>}
    </span>
  );
}

export function Copy({ value }: { value: string }) {
  const [done, setDone] = useState(false);
  return <Button variant="ghost" aria-label={`Copy ${value.slice(0, 12)}`} onClick={() => { navigator.clipboard?.writeText(value); setDone(true); }}>{done ? 'Copied' : 'Copy'}</Button>;
}
```

`actions.ts`:

```ts
import { api } from '../../../api';
import type { LibraryDetail } from '../../../api';

type Result = { ok: boolean; message: string };
const path = (imdb: string, tail: string) => `/ui/api/library/${imdb}/${tail}`;

export const ACTIONS = {
  retry: async (d: LibraryDetail): Promise<Result> => { const r = await api.retryRequest(d.request.id); return { ok: r.ok, message: r.ok ? 'retry started' : 'retry failed' }; },
  reresolve: async (d: LibraryDetail): Promise<Result> => {
    if (!d.items.length) return { ok: false, message: 'no stream to re-resolve' };
    const results = await Promise.all(d.items.map((i) => api.reResolve(i.token)));
    const n = results.filter((r) => r.resolved).length;
    return { ok: n > 0, message: `${n} of ${results.length} resolved` };
  },
  mirror: (d: LibraryDetail) => api.libraryAction(path(d.request.imdb_id, 'mirror')),
  unmirror: (d: LibraryDetail) => api.libraryAction(path(d.request.imdb_id, 'unmirror')),
  purge: async (d: LibraryDetail): Promise<Result> => { await api.purgeRequest(d.request.id); return { ok: true, message: 'removed from the library' }; },
  blacklistCurrent: (d: LibraryDetail) => d.request.info_hash
    ? api.libraryAction(`/ui/api/library/hash/${d.request.info_hash}/blacklist`)
    : Promise.resolve({ ok: false, message: 'no current hash' }),
  dropRetry: (d: LibraryDetail) => api.libraryAction(path(d.request.imdb_id, 'drop-retry')),
  retryNow: (d: LibraryDetail) => api.libraryAction(path(d.request.imdb_id, 'retry-now')),
  resetPlayability: (d: LibraryDetail) => api.libraryAction(path(d.request.imdb_id, 'playability/reset')),
  recheckSeries: (d: LibraryDetail) => api.libraryAction(path(d.request.imdb_id, 'recheck-series')),
  retryEpisode: (d: LibraryDetail, s: number, e: number) => api.libraryAction(path(d.request.imdb_id, `episodes/${s}/${e}/retry`)),
  blacklist: (hash: string) => api.libraryAction(`/ui/api/library/hash/${hash}/blacklist`),
  unblacklist: (hash: string) => api.libraryAction(`/ui/api/library/hash/${hash}/unblacklist`),
  saveOverride: (d: LibraryDetail, body: unknown) => api.libraryAction(path(d.request.imdb_id, 'override'), 'POST', body),
  clearOverride: (d: LibraryDetail) => api.libraryAction(path(d.request.imdb_id, 'override'), 'DELETE'),
};
```

`cards/StatusCard.tsx`:

```tsx
import type { LibraryDetail } from '../../../../api';
import { Pill, statusLabel, statusToPillState } from '../../../../components/primitives';
import { ACTIONS } from '../actions';
import { ActionButton, DrawerCard, Row } from './DrawerCard';

export function StatusCard({ d, onDone }: { d: LibraryDetail; onDone: () => void }) {
  const r = d.request;
  return (
    <DrawerCard title="Status" description="Where this title stands and what is scheduled for it.">
      <Row label="Status"><Pill state={statusToPillState(r.status)}>{statusLabel(r.status)}</Pill></Row>
      {r.error && <Row label="Last error">{r.error}</Row>}
      <Row label="Changed">{r.updated_at}</Row>
      {r.status === 'pending' && <p className="text-xs text-muted">The processor has this title now.</p>}
      {d.retry && (
        <>
          <Row label="Retry queue">attempt {d.retry.attempt}, next at {d.retry.next_retry_at}</Row>
          <div className="flex gap-2">
            <ActionButton label="Retry now" run={() => ACTIONS.retryNow(d)} onDone={onDone} />
            <ActionButton label="Drop from queue" run={() => ACTIONS.dropRetry(d)} onDone={onDone} />
          </div>
        </>
      )}
      {d.wanted_movie && <Row label="Wanted">{d.wanted_movie.reason || 'no release yet'}, {d.wanted_movie.attempts} attempts, last {d.wanted_movie.last_checked || 'never'}</Row>}
    </DrawerCard>
  );
}
```

`cards/ReleaseCard.tsx`:

```tsx
import type { LibraryDetail } from '../../../../api';
import { Copy, DrawerCard, Row } from './DrawerCard';

export function ReleaseCard({ d }: { d: LibraryDetail }) {
  const r = d.request;
  if (!r.info_hash && !d.items.length) return null;
  return (
    <DrawerCard title="Release" description="The release in use and the files written for it.">
      {(r.quality || r.source) && <Row label="Quality">{[r.quality, r.source].filter(Boolean).join(' ')}</Row>}
      {r.info_hash && <Row label="Hash"><span className="font-mono">{r.info_hash}</span> <Copy value={r.info_hash} /></Row>}
      {d.items.map((i) => (
        <div key={i.token} className="rounded border border-border p-2 text-xs">
          <Row label="File">{i.strm_path || 'no file'} {i.strm_path && <Copy value={i.strm_path} />}</Row>
          <Row label="Provider">{i.debrid_provider || 'torbox'}{i.torbox_id ? `, TorBox id ${i.torbox_id}` : ', not in TorBox'}</Row>
          <Row label="Played">{i.play_count} times{i.last_played ? `, last ${i.last_played}` : ''}</Row>
          {i.season != null && <Row label="Episode">S{String(i.season).padStart(2, '0')}E{String(i.episode ?? 0).padStart(2, '0')}</Row>}
        </div>
      ))}
    </DrawerCard>
  );
}
```

`cards/PlayabilityCard.tsx`:

```tsx
import type { LibraryDetail } from '../../../../api';
import { ACTIONS } from '../actions';
import { ActionButton, DrawerCard, Row } from './DrawerCard';

export function PlayabilityCard({ d, onDone }: { d: LibraryDetail; onDone: () => void }) {
  if (!d.playability.length) return null;
  return (
    <DrawerCard title="Playability" description="What happened the last times someone pressed play.">
      {d.playability.map((p) => (
        <div key={p.content_key} className="rounded border border-border p-2 text-xs">
          <Row label="Key">{p.content_key}</Row>
          <Row label="State">{p.status}{p.consecutive_failures ? `, ${p.consecutive_failures} failures in a row` : ''}</Row>
          {p.last_ok_provider && <Row label="Last ok">{p.last_ok_provider} at {p.last_ok_at}</Row>}
          {p.last_fail_reason && <Row label="Last failure">{p.last_fail_reason}</Row>}
        </div>
      ))}
      <div className="flex gap-2">
        <ActionButton label="Re-resolve" run={() => ACTIONS.reresolve(d)} onDone={onDone} />
        <ActionButton label="Reset" run={() => ACTIONS.resetPlayability(d)} onDone={onDone} />
      </div>
    </DrawerCard>
  );
}
```

`TitleDrawer.tsx`:

```tsx
import { useEffect } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../../api';
import { Button, Pill, statusLabel, statusToPillState } from '../../../components/primitives';
import { ACTIONS } from './actions';
import { ActionButton } from './cards/DrawerCard';
import { StatusCard } from './cards/StatusCard';
import { ReleaseCard } from './cards/ReleaseCard';
import { PlayabilityCard } from './cards/PlayabilityCard';

export function TitleDrawer({ imdb, onClose, onChanged }: { imdb: string; onClose: () => void; onChanged: () => void }) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['library-detail', imdb], queryFn: () => api.libraryDetail(imdb) });
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  const refresh = () => { qc.invalidateQueries({ queryKey: ['library-detail', imdb] }); onChanged(); };
  const d = q.data;
  return (
    <aside role="dialog" aria-label="Title details" className="fixed inset-y-0 right-0 z-20 w-full max-w-[560px] overflow-y-auto border-l border-border bg-bg p-5 shadow-2xl">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold">{d ? d.request.title : 'Loading...'}</h2>
          {d && <div className="mt-1 flex items-center gap-2 text-xs text-muted">
            <span>{d.request.media_type === 'movie' ? 'Movie' : 'Series'}</span><span className="font-mono">{d.request.imdb_id}</span>
            <Pill state={statusToPillState(d.request.status)}>{statusLabel(d.request.status)}</Pill>
          </div>}
        </div>
        <Button variant="ghost" aria-label="Close" onClick={onClose}>&times;</Button>
      </div>
      {q.error && <p className="mt-4 text-sm text-danger">{(q.error as Error).message}</p>}
      {d && (
        <div className="mt-4 space-y-4">
          <div className="flex flex-wrap gap-2">
            <ActionButton label="Retry" run={() => ACTIONS.retry(d)} onDone={refresh} variant="primary" />
            <ActionButton label="Re-resolve" run={() => ACTIONS.reresolve(d)} onDone={refresh} />
            <ActionButton label="Mirror to arr" run={() => ACTIONS.mirror(d)} onDone={refresh} />
            <ActionButton label="Blacklist current hash" run={() => ACTIONS.blacklistCurrent(d)} onDone={refresh} />
            <ActionButton label="Purge" run={() => ACTIONS.purge(d)} onDone={() => { onChanged(); onClose(); }}
              confirm={`Remove "${d.request.title}" from the library? Its files, monitoring and request go too.`} />
          </div>
          <StatusCard d={d} onDone={refresh} />
          <ReleaseCard d={d} />
          <PlayabilityCard d={d} onDone={refresh} />
        </div>
      )}
    </aside>
  );
}
```

In `Library.tsx`: `{state.open && <TitleDrawer imdb={state.open} onClose={() => update({ open: null })} onChanged={() => { page.refetch(); counts.refetch(); }} />}`.

- [ ] **Step 3: Run, build, commit**

```bash
git add frontend/src static/app
git commit -m "feat(ui): title drawer with status, release and playability cards

Claude-Session: https://claude.ai/code/session_01F7oCy4VPeTT91GtZNTA8px"
```

---

### Task 7: Episodes, Requests, Preferences, Arr, Hashes and Activity cards

**Files:**
- Create: `cards/EpisodesCard.tsx`, `cards/RequestsCard.tsx`, `cards/PreferencesCard.tsx`, `cards/ArrCard.tsx`, `cards/HashesCard.tsx`, `cards/ActivityCard.tsx`
- Modify: `TitleDrawer.tsx` (mount them after `PlayabilityCard`)
- Test: `frontend/src/pages/admin/library/cards.test.tsx`

**Interfaces:** each card is `({ d, onDone }) => JSX | null` and returns `null` when it has nothing to show (no series, no user requests, no override and nothing to set... Preferences always shows for a title so the override can be created; Arr shows only when the mirror is on: `d.arr.mirrored_at` or the row's `in_torbox`? Use: show Arr card always, it explains the state; Hashes shows when `d.hashes.length`; Activity shows when `d.activity.length`).

- [ ] **Step 1: Failing tests**

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { EpisodesCard } from './cards/EpisodesCard';
import { RequestsCard } from './cards/RequestsCard';
import { PreferencesCard } from './cards/PreferencesCard';
import { HashesCard } from './cards/HashesCard';
import { ActivityCard } from './cards/ActivityCard';

const apiMocks = vi.hoisted(() => ({ librarySeason: vi.fn(), libraryAction: vi.fn(), libraryActivity: vi.fn() }));
vi.mock('../../../api', async () => {
  const actual = await vi.importActual<typeof import('../../../api')>('../../../api');
  return { ...actual, api: { ...actual.api, ...apiMocks } };
});

const base: any = {
  request: { id: 1, imdb_id: 'tt4', title: 'Loki', media_type: 'series', status: 'success', error: null, info_hash: null, quality: null, source: null, seasons: '1,2', created_at: '', updated_at: '', tmdb_id: null, arr_mirrored_at: null },
  items: [], playability: [], episodes: [{ season: 2, present: 2, wanted: 1 }], monitored: { status: 'active', last_checked: '2026-09-01 10:00:00', seasons: '1,2' },
  retry: null, wanted_movie: null,
  user_requests: [{ id: 9, username: 'adam', status: 'denied', reviewer: 'root', note: 'too big', created_at: '2026-09-01 09:00:00', reviewed_at: '2026-09-01 10:00:00' }],
  seerr_request_id: 12, override: { quality_preference: '1080p', allow_4k: 0, prefer_hevc: 1, notes: 'keep small' },
  hashes: [{ info_hash: 'a'.repeat(40), blacklisted: true, fail_count: 3, last_error: 'blacklisted by admin', current: false }],
  activity: [{ id: 5, event: 'added', title: 'Loki', message: 'series', success: 1, created_at: '2026-09-01 10:00:00' }], arr: { mirrored_at: null },
};

function wrap(el: React.ReactElement) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{el}</QueryClientProvider>);
}

describe('drawer cards', () => {
  beforeEach(() => vi.clearAllMocks());

  it('Episodes shows seasons and loads a season on expand, with per-episode retry', async () => {
    apiMocks.librarySeason.mockResolvedValue({ episodes: [
      { season: 2, episode: 1, present: true, strm_path: '/s/e1.strm', token: 'e1', wanted_status: null, attempt_count: 0, air_date: null, last_attempted: null },
      { season: 2, episode: 3, present: false, strm_path: null, token: null, wanted_status: 'wanted', attempt_count: 4, air_date: '2024-01-01', last_attempted: '2026-09-01 10:00:00' },
    ] });
    apiMocks.libraryAction.mockResolvedValue({ ok: true, message: 'searching S02E03' });
    wrap(<EpisodesCard d={base} onDone={() => {}} />);
    expect(screen.getByText(/Season 2/)).toHaveTextContent('2 present, 1 wanted');
    await userEvent.click(screen.getByRole('button', { name: 'Expand season 2' }));
    expect(await screen.findByText('E03')).toBeInTheDocument();
    expect(screen.getByText(/4 attempts/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Retry S02E03' }));
    await waitFor(() => expect(apiMocks.libraryAction).toHaveBeenCalledWith('/ui/api/library/tt4/episodes/2/3/retry'));
    expect(await screen.findByText('searching S02E03')).toBeInTheDocument();
  });

  it('Requests lists every user request with reviewer and note', () => {
    wrap(<RequestsCard d={base} onDone={() => {}} />);
    expect(screen.getByText('adam')).toBeInTheDocument();
    expect(screen.getByText(/root/)).toBeInTheDocument();
    expect(screen.getByText('too big')).toBeInTheDocument();
    expect(screen.getByText(/Seerr request 12/)).toBeInTheDocument();
  });

  it('Preferences saves the override as JSON and can clear it', async () => {
    apiMocks.libraryAction.mockResolvedValue({ ok: true, message: 'override saved' });
    wrap(<PreferencesCard d={base} onDone={() => {}} />);
    expect(screen.getByRole('checkbox', { name: 'Prefer HEVC' })).toBeChecked();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Allow 4K' }));
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(apiMocks.libraryAction).toHaveBeenCalledWith('/ui/api/library/tt4/override', 'POST',
      { quality_preference: '1080p', allow_4k: true, prefer_hevc: true, notes: 'keep small' }));
    await userEvent.click(screen.getByRole('button', { name: 'Clear' }));
    await waitFor(() => expect(apiMocks.libraryAction).toHaveBeenCalledWith('/ui/api/library/tt4/override', 'DELETE'));
  });

  it('Hashes shows the blacklist state with an Unblacklist button', async () => {
    apiMocks.libraryAction.mockResolvedValue({ ok: true, message: 'hash cleared' });
    wrap(<HashesCard d={base} onDone={() => {}} />);
    expect(screen.getByText('blacklisted by admin')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Unblacklist' }));
    await waitFor(() => expect(apiMocks.libraryAction).toHaveBeenCalledWith(`/ui/api/library/hash/${'a'.repeat(40)}/unblacklist`));
  });

  it('Activity lists entries and loads more', async () => {
    apiMocks.libraryActivity.mockResolvedValue({ activity: [{ id: 4, event: 'wanted', title: 'Loki', message: 'x', success: 0, created_at: '2026-08-31 10:00:00' }] });
    wrap(<ActivityCard d={base} />);
    expect(screen.getByText('added')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Load more' }));
    await waitFor(() => expect(apiMocks.libraryActivity).toHaveBeenCalledWith('tt4', 5));
    expect(await screen.findByText('wanted')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Implement**

`EpisodesCard.tsx`:

```tsx
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../../../api';
import type { LibraryDetail } from '../../../../api';
import { Button } from '../../../../components/primitives';
import { ACTIONS } from '../actions';
import { ActionButton, DrawerCard, Row } from './DrawerCard';

function Season({ d, season, onDone }: { d: LibraryDetail; season: { season: number; present: number; wanted: number }; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const q = useQuery({ queryKey: ['library-season', d.request.imdb_id, season.season], queryFn: () => api.librarySeason(d.request.imdb_id, season.season), enabled: open });
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    <div className="rounded border border-border p-2 text-xs">
      <div className="flex items-center justify-between">
        <span>Season {season.season}: {season.present} present, {season.wanted} wanted</span>
        <Button variant="ghost" aria-label={`${open ? 'Collapse' : 'Expand'} season ${season.season}`} onClick={() => setOpen((o) => !o)}>{open ? 'Hide' : 'Show'}</Button>
      </div>
      {open && q.data && (
        <ul className="mt-2 space-y-1">
          {q.data.episodes.map((e) => (
            <li key={e.episode} className="flex flex-wrap items-center justify-between gap-2">
              <span>E{pad(e.episode)} {e.present ? '✓' : e.wanted_status || 'missing'}{e.air_date ? `, aired ${e.air_date}` : ''}{e.attempt_count ? `, ${e.attempt_count} attempts` : ''}</span>
              {!e.present && <ActionButton label={`Retry S${pad(season.season)}E${pad(e.episode)}`} run={() => ACTIONS.retryEpisode(d, season.season, e.episode)} onDone={onDone} />}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function EpisodesCard({ d, onDone }: { d: LibraryDetail; onDone: () => void }) {
  if (!d.episodes) return null;
  return (
    <DrawerCard title="Episodes" description="Seasons Mycelium tracks for this series.">
      {d.monitored && <Row label="Monitor">{d.monitored.status}, last check {d.monitored.last_checked || 'never'}</Row>}
      {d.episodes.map((s) => <Season key={s.season} d={d} season={s} onDone={onDone} />)}
      <ActionButton label="Recheck series" run={() => ACTIONS.recheckSeries(d)} onDone={onDone} />
    </DrawerCard>
  );
}
```

`RequestsCard.tsx`:

```tsx
import type { LibraryDetail } from '../../../../api';
import { Pill, statusLabel, statusToPillState } from '../../../../components/primitives';
import { DrawerCard } from './DrawerCard';

export function RequestsCard({ d }: { d: LibraryDetail; onDone?: () => void }) {
  if (!d.user_requests.length && !d.seerr_request_id) return null;
  return (
    <DrawerCard title="Requests" description="Who asked for this title and what happened to the request.">
      {d.user_requests.map((u) => (
        <div key={u.id} className="rounded border border-border p-2 text-xs">
          <div className="flex items-center justify-between"><span className="font-medium">{u.username}</span><Pill state={statusToPillState(u.status)}>{statusLabel(u.status)}</Pill></div>
          <div className="text-muted">requested {u.created_at}{u.reviewer ? `, ${u.status} by ${u.reviewer} ${u.reviewed_at || ''}` : ''}</div>
          {u.note && <div className="mt-1">{u.note}</div>}
        </div>
      ))}
      {d.seerr_request_id && <div className="text-xs text-muted">Seerr request {d.seerr_request_id}</div>}
    </DrawerCard>
  );
}
```

`PreferencesCard.tsx`:

```tsx
import { useState } from 'react';
import type { LibraryDetail } from '../../../../api';
import { Toggle } from '../../../../components/primitives';
import { ACTIONS } from '../actions';
import { ActionButton, DrawerCard, Row } from './DrawerCard';

export function PreferencesCard({ d, onDone }: { d: LibraryDetail; onDone: () => void }) {
  const o = d.override;
  const [form, setForm] = useState({ quality_preference: o?.quality_preference || '', allow_4k: Boolean(o?.allow_4k), prefer_hevc: Boolean(o?.prefer_hevc), notes: o?.notes || '' });
  return (
    <DrawerCard title="Preferences" description="Overrides for this title only; blank means the global rules apply.">
      <Row label="Resolution"><input aria-label="Preferred resolution" value={form.quality_preference} placeholder="e.g. 1080p" onChange={(e) => setForm({ ...form, quality_preference: e.target.value })} className="w-full max-w-xs rounded border border-border bg-bg px-2 py-1 text-xs" /></Row>
      <Row label="Allow 4K"><Toggle label="Allow 4K" checked={form.allow_4k} onChange={(v) => setForm({ ...form, allow_4k: v })} /></Row>
      <Row label="Prefer HEVC"><Toggle label="Prefer HEVC" checked={form.prefer_hevc} onChange={(v) => setForm({ ...form, prefer_hevc: v })} /></Row>
      <Row label="Notes"><input aria-label="Notes" value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className="w-full max-w-xs rounded border border-border bg-bg px-2 py-1 text-xs" /></Row>
      <div className="flex gap-2">
        <ActionButton label="Save" variant="primary" run={() => ACTIONS.saveOverride(d, form)} onDone={onDone} />
        {o && <ActionButton label="Clear" run={() => ACTIONS.clearOverride(d)} onDone={onDone} />}
      </div>
    </DrawerCard>
  );
}
```

`ArrCard.tsx`:

```tsx
import type { LibraryDetail } from '../../../../api';
import { ACTIONS } from '../actions';
import { ActionButton, DrawerCard, Row } from './DrawerCard';

export function ArrCard({ d, onDone }: { d: LibraryDetail; onDone: () => void }) {
  return (
    <DrawerCard title="Arr mirror" description="Whether Radarr or Sonarr knows this title.">
      <Row label="Mirrored">{d.arr.mirrored_at ? `since ${d.arr.mirrored_at}` : 'no'}</Row>
      <div className="flex gap-2">
        <ActionButton label="Mirror now" run={() => ACTIONS.mirror(d)} onDone={onDone} />
        {d.arr.mirrored_at && <ActionButton label="Remove from arr" run={() => ACTIONS.unmirror(d)} onDone={onDone} />}
      </div>
    </DrawerCard>
  );
}
```

`HashesCard.tsx`:

```tsx
import type { LibraryDetail } from '../../../../api';
import { ACTIONS } from '../actions';
import { ActionButton, Copy, DrawerCard } from './DrawerCard';

export function HashesCard({ d, onDone }: { d: LibraryDetail; onDone: () => void }) {
  if (!d.hashes.length) return null;
  return (
    <DrawerCard title="Hashes" description="Releases this title has used and whether they are blacklisted.">
      {d.hashes.map((h) => (
        <div key={h.info_hash} className="rounded border border-border p-2 text-xs">
          <div className="flex flex-wrap items-center gap-2"><span className="font-mono break-all">{h.info_hash}</span><Copy value={h.info_hash} />{h.current && <span className="text-ok">current</span>}</div>
          <div className="text-muted">{h.blacklisted ? `blacklisted, ${h.fail_count} failures` : h.fail_count ? `${h.fail_count} failures` : 'no failures'}{h.last_error ? `: ${h.last_error}` : ''}</div>
          <div className="mt-1">
            {h.blacklisted
              ? <ActionButton label="Unblacklist" run={() => ACTIONS.unblacklist(h.info_hash)} onDone={onDone} />
              : <ActionButton label="Blacklist" run={() => ACTIONS.blacklist(h.info_hash)} onDone={onDone} />}
          </div>
        </div>
      ))}
    </DrawerCard>
  );
}
```

`ActivityCard.tsx`:

```tsx
import { useState } from 'react';
import { api } from '../../../../api';
import type { LibraryDetail } from '../../../../api';
import { Button } from '../../../../components/primitives';
import { DrawerCard } from './DrawerCard';

export function ActivityCard({ d }: { d: LibraryDetail }) {
  const [extra, setExtra] = useState<LibraryDetail['activity']>([]);
  const [done, setDone] = useState(false);
  const rows = [...d.activity, ...extra];
  if (!rows.length) return null;
  const more = async () => {
    const r = await api.libraryActivity(d.request.imdb_id, rows[rows.length - 1].id);
    setExtra((x) => [...x, ...r.activity]);
    if (r.activity.length < 20) setDone(true);
  };
  return (
    <DrawerCard title="Activity" description="What Mycelium did with this title, newest first.">
      <ul className="space-y-1 text-xs">
        {rows.map((a) => (
          <li key={a.id} className="flex gap-2"><span className="w-32 flex-none text-muted">{a.created_at.slice(0, 16)}</span><span className={a.success ? '' : 'text-danger'}>{a.event}</span><span className="text-muted">{a.message}</span></li>
        ))}
      </ul>
      {!done && <Button variant="ghost" onClick={more}>Load more</Button>}
    </DrawerCard>
  );
}
```

Mount in `TitleDrawer.tsx` after `PlayabilityCard`: `EpisodesCard`, `RequestsCard`, `PreferencesCard`, `ArrCard`, `HashesCard`, `ActivityCard`, each with `d` and `onDone={refresh}`.

- [ ] **Step 3: Run, build, commit**

```bash
git add frontend/src static/app
git commit -m "feat(ui): episodes, requests, preferences, arr, hashes and activity cards

Claude-Session: https://claude.ai/code/session_01F7oCy4VPeTT91GtZNTA8px"
```

---

### Task 8: Action bar and the Queue view

**Files:**
- Create: `frontend/src/pages/admin/library/ActionBar.tsx`
- Modify: `Library.tsx` (replace the placeholder bar; Queue view extras), `api.ts` if `purgeRequest`/`retryRequest` names differ
- Test: `frontend/src/pages/admin/library/ActionBar.test.tsx`; extend `Library.test.tsx`

**Interfaces:** `ActionBar({ rows: LibraryRow[], selected: Set<string>, view: string, onDone: () => void, onClear: () => void })`. Actions: Retry (per row `api.retryRequest(row.id)`), Re-resolve (needs tokens: fetch `api.libraryDetail(imdb)` per row and re-resolve its items), Mirror to arr (`/mirror`), Remove from library (`api.purgeRequest(row.id)`, one confirm with the count), and when `view === 'queue'` also Run now (`/retry-now`) and Drop from queue (`/drop-retry`). Runs sequentially, shows `k of N`, lists failures.

- [ ] **Step 1: Failing test**

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { LibraryRow } from '../../../api';
import { ActionBar } from './ActionBar';

const apiMocks = vi.hoisted(() => ({ retryRequest: vi.fn(), purgeRequest: vi.fn(), libraryAction: vi.fn(), libraryDetail: vi.fn(), reResolve: vi.fn() }));
vi.mock('../../../api', async () => {
  const actual = await vi.importActual<typeof import('../../../api')>('../../../api');
  return { ...actual, api: { ...actual.api, ...apiMocks } };
});
const row = (id: number, imdb: string, title: string): LibraryRow => ({
  id, imdb_id: imdb, tmdb_id: null, title, media_type: 'movie', status: 'failed', error: null, quality: null, source: null, info_hash: null,
  seasons: null, created_at: '', updated_at: '', requester: 'auto', requester_id: null, requested_at: null, playability: null,
  missing_episodes: 0, retry: null, arr_mirrored: false, in_torbox: false, in_wanted_movies: false,
});

describe('ActionBar', () => {
  beforeEach(() => vi.clearAllMocks());

  it('retries each selected title in turn, counts, and reports failures', async () => {
    apiMocks.retryRequest.mockResolvedValueOnce({ ok: true }).mockRejectedValueOnce(new Error('500: boom'));
    const onDone = vi.fn();
    render(<ActionBar rows={[row(1, 'tt1', 'Heat'), row(2, 'tt2', 'Alien'), row(3, 'tt3', 'Dune')]} selected={new Set(['tt1', 'tt2'])} view="all" onDone={onDone} onClear={() => {}} />);
    expect(screen.getByText('2 selected')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Run now' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(apiMocks.retryRequest).toHaveBeenCalledTimes(2));
    expect(await screen.findByText(/1 of 2 done, 1 failed/)).toBeInTheDocument();
    expect(screen.getByText(/Alien: 500: boom/)).toBeInTheDocument();
    expect(onDone).toHaveBeenCalled();
  });

  it('Remove asks once with the count and the queue view adds Run now and Drop', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<ActionBar rows={[row(1, 'tt1', 'Heat')]} selected={new Set(['tt1'])} view="queue" onDone={() => {}} onClear={() => {}} />);
    await userEvent.click(screen.getByRole('button', { name: 'Remove from library' }));
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining('1 title'));
    expect(apiMocks.purgeRequest).not.toHaveBeenCalled();
    apiMocks.libraryAction.mockResolvedValue({ ok: true, message: 'dropped from the retry queue' });
    await userEvent.click(screen.getByRole('button', { name: 'Drop from queue' }));
    await waitFor(() => expect(apiMocks.libraryAction).toHaveBeenCalledWith('/ui/api/library/tt1/drop-retry'));
    expect(screen.getByRole('button', { name: 'Run now' })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: `ActionBar.tsx`**

```tsx
import { useState } from 'react';
import { api } from '../../../api';
import type { LibraryRow } from '../../../api';
import { Button } from '../../../components/primitives';

type Op = { label: string; confirm?: (n: number) => string; run: (r: LibraryRow) => Promise<unknown>; queueOnly?: boolean };

const OPS: Op[] = [
  { label: 'Retry', run: (r) => api.retryRequest(r.id) },
  { label: 'Re-resolve', run: async (r) => { const d = await api.libraryDetail(r.imdb_id); await Promise.all(d.items.map((i) => api.reResolve(i.token))); } },
  { label: 'Mirror to arr', run: (r) => api.libraryAction(`/ui/api/library/${r.imdb_id}/mirror`).then((x) => { if (!x.ok) throw new Error(x.message); }) },
  { label: 'Run now', queueOnly: true, run: (r) => api.libraryAction(`/ui/api/library/${r.imdb_id}/retry-now`).then((x) => { if (!x.ok) throw new Error(x.message); }) },
  { label: 'Drop from queue', queueOnly: true, run: (r) => api.libraryAction(`/ui/api/library/${r.imdb_id}/drop-retry`).then((x) => { if (!x.ok) throw new Error(x.message); }) },
  { label: 'Remove from library', confirm: (n) => `Remove ${n} title${n === 1 ? '' : 's'} from the library? Their files, monitoring and requests go too.`, run: (r) => api.purgeRequest(r.id) },
];

export function ActionBar({ rows, selected, view, onDone, onClear }: {
  rows: LibraryRow[]; selected: Set<string>; view: string; onDone: () => void; onClear: () => void;
}) {
  const [progress, setProgress] = useState<{ label: string; done: number; total: number; failures: string[] } | null>(null);
  const targets = rows.filter((r) => selected.has(r.imdb_id));
  const run = async (op: Op) => {
    if (op.confirm && !window.confirm(op.confirm(targets.length))) return;
    const failures: string[] = [];
    let done = 0;
    setProgress({ label: op.label, done, total: targets.length, failures });
    for (const r of targets) {
      try { await op.run(r); done += 1; } catch (e: any) { failures.push(`${r.title}: ${e.message}`); }
      setProgress({ label: op.label, done, total: targets.length, failures: [...failures] });
    }
    onDone();
  };
  return (
    <div className="fixed inset-x-0 bottom-0 z-10 border-t border-border bg-bg/95 px-4 py-3 backdrop-blur md:left-auto">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-2 text-sm">
        <span className="mr-2">{selected.size} selected</span>
        {OPS.filter((o) => !o.queueOnly || view === 'queue').map((o) => (
          <Button key={o.label} onClick={() => run(o)} disabled={progress !== null && progress.done + progress.failures.length < progress.total}>{o.label}</Button>
        ))}
        <Button variant="ghost" onClick={onClear}>Clear</Button>
        {progress && (
          <span className="ml-auto text-xs text-muted">
            {progress.label}: {progress.done} of {progress.total} done{progress.failures.length ? `, ${progress.failures.length} failed` : ''}
            {progress.failures.map((f) => <span key={f} className="block text-danger">{f}</span>)}
          </span>
        )}
      </div>
    </div>
  );
}
```

In `Library.tsx`, replace the placeholder line with `{selected.size > 0 && <ActionBar rows={rows} selected={selected} view={state.view} onDone={() => { page.refetch(); counts.refetch(); }} onClear={() => setSelected(new Set())} />}`. Add to `Library.test.tsx` one case: selecting a row shows the `Retry` and `Remove from library` buttons in the bar.

- [ ] **Step 3: Run, build, commit**

```bash
git add frontend/src static/app
git commit -m "feat(ui): bulk action bar and queue actions for the Library tab

Claude-Session: https://claude.ai/code/session_01F7oCy4VPeTT91GtZNTA8px"
```

---

### Task 9: Tab strip, panel removals, links, docs

**Files:**
- Modify: `frontend/src/pages/admin/AdminLayout.tsx` (order: Overview, Library, Requests, Users, Filter rules, Scrapers, Logs, Releases, Maintenance, Blacklist, Settings), `Requests.tsx` (remove the "All requests" panel and its tests; keep Pending approvals and Auto-approve), `Overview.tsx` (retry-queue count links to `#library?view=queue`), `Maintenance.tsx` (remove the Playability panel; the drawer covers it), `Blacklist.tsx` (title column: the backend `GET /ui/api/blacklist` gains `titles: [..]` per hash via a `db.titles_for_hash(info_hash)` helper; show them), `README.md`, `docs/install-guide.html`, `CHANGELOG.md`
- Test: adjust `Requests.test.tsx`, `Maintenance.test.tsx`, `Blacklist.test.tsx`, `AdminLayout.test.tsx`; `tests/test_library_db.py` gains `titles_for_hash`

- [ ] **Step 1: Backend helper and test** (append to `tests/test_library_db.py`)

```python
def test_titles_for_hash():
    db.insert_request("Heat", "tt1", "movie")
    _item("tt1", "tok", "c" * 40)
    assert db.titles_for_hash("c" * 40) == [{"imdb_id": "tt1", "title": "Heat"}]
    assert db.titles_for_hash("d" * 40) == []
```

`db.py`:

```python
def titles_for_hash(info_hash: str) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            """SELECT DISTINCT r.imdb_id, r.title FROM requests r
               WHERE r.info_hash = ? OR r.imdb_id IN (SELECT imdb_id FROM virtual_items WHERE info_hash = ?)
               ORDER BY r.title""", (info_hash, info_hash)).fetchall()
        return [dict(r) for r in rows]
```

Find the blacklist list route (`grep -n "failed-hashes\|blacklist" app.py | head`) and add `"titles": db.titles_for_hash(h["info_hash"])` to each row it returns.

- [ ] **Step 2: Frontend edits**

- `AdminLayout.tsx`: reorder `ADMIN_TABS` as above (Library second).
- `Requests.tsx`: delete `AllRequestsPanel` (lines 107 to 227) and its render; keep the pending approvals and auto-approve panels; add a one-line link at the top: "Looking for a title? Open the Library tab." linking to `#library`. Remove the corresponding tests from `Requests.test.tsx`.
- `Overview.tsx`: wrap the retry-queue count in `<Link to={{ hash: 'library?view=queue' }}>`.
- `Maintenance.tsx`: remove the Playability panel (lines 322 to 418) and its tests; add a line in its place: "Per-title playability moved to the Library tab's drawer."
- `Blacklist.tsx`: add a Titles column rendering `titles.map(t => t.title)` with a link to `#library?open=<imdb>`; type the row accordingly in `api.ts`.
- `Library.tsx`: when `state.open` is set from the hash on first load, the drawer opens without a table row click (already handled since the drawer mounts on `state.open`).

- [ ] **Step 3: Docs**

`README.md`: in the admin line (line 72) replace "Requests" with "Library (every title with its status, requester, playability and queue state, plus a drawer with retry, re-resolve, purge, mirror and blacklist actions), Requests (approvals and auto-approve rules)". `docs/install-guide.html`: find the admin-tabs description (`grep -n "Requests" docs/install-guide.html`) and add a sentence per language span describing the Library tab and that per-title actions live in its drawer. `CHANGELOG.md`:

```markdown
## [Unreleased]

### Added

- Admin Library tab: every title in one table with status and failure
  reason, release, requester, playability, missing-episode and retry
  badges; saved views (Needs attention, Wanted, Queue, Incomplete series,
  Unmirrored); filters by type, status, problem, requester and date;
  sortable columns; server-side paging; a bulk action bar (retry,
  re-resolve, mirror, remove; run now and drop from queue in the Queue
  view). Clicking a title opens a drawer with everything Mycelium knows
  about it and its actions: retry, re-resolve, purge, mirror to the arr,
  blacklist a hash, reset playability, per-episode retry and series
  recheck, a per-title quality override, request history and the
  activity log.
- `activity_log.imdb_id` so the drawer can show a title's history.

### Changed

- The admin Requests tab keeps pending approvals and the auto-approve
  rules; its request list moved to the Library tab. Maintenance lost its
  per-token playability panel (the drawer replaces it); the Blacklist tab
  shows which titles used each hash; the Overview's retry-queue count links
  to the Queue view.
```

- [ ] **Step 4: Both suites, build, commit**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/ -q -p no:cacheprovider
cd frontend && npx tsc --noEmit && npx vitest run && npm run build && cd ..
git add -A
git commit -m "feat(admin): Library tab in the strip, Requests trimmed, links from Overview and Blacklist, docs

Claude-Session: https://claude.ai/code/session_01F7oCy4VPeTT91GtZNTA8px"
```

---

## Self-review notes

- Spec coverage: data and endpoints (Tasks 1 to 4, including the activity-log column, indexes, views, filters, paging, detail, seasons, activity paging, all twelve actions); the tab with rail, views with counts, filters in the hash, sortable table with badges, paging and page size, empty states (Task 5); the drawer header and nine cards (Tasks 6 and 7); the bulk bar and queue actions (Task 8); navigation, Maintenance and Blacklist changes, Overview link, docs (Task 9). Plan 2 (Requests tab) is out of scope as the spec says.
- Type consistency: the row shape is defined once in Task 2 and mirrored by `LibraryRow` in Task 5; the detail shape in Task 3 by `LibraryDetail` in Task 6; action paths in Task 4 match `actions.ts` and `ActionBar` in Tasks 6 and 8; `season_episodes` fields match `SeasonEpisode`.
- Known small liberties: the Playability card shows `unknown` records as well as `degraded` (the table hides `playable` only); the Arr card is always shown so the state is visible even when the mirror is off; `titles_for_hash` for the Blacklist tab was not in the spec's data section but is the spec's "Blacklist tab gains a title column".
