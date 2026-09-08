# Requests Admin Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the admin Requests tab with a rail-and-table view over every user request (Pending, Approved, Denied, All) with approve, inline deny and reopen, a per-user Quotas card, enforced monthly quotas, and the auto-approve rules moved under the table.

**Architecture:** A new backend read model `requests_admin.py` (one SELECT over `user_requests` joined to `users` twice and left-joined to `requests`, wrapped for views and filters, plus a COUNT) behind two admin routes, a `quota.allows()` rule enforced in the request-creation route, a quotas endpoint, and a reopen route. The frontend copies the Library tab's shape: `pages/admin/requests/state.ts` (hash state), `Rail.tsx`, `RequestTable.tsx` with inline row actions, `QuotasCard.tsx`, the existing auto-approve editor moved into `AutoApproveCard.tsx`, and the shell `pages/admin/Requests.tsx`. The title drawer is reused and gains a Forget button.

**Tech Stack:** Python 3.12 / Flask / SQLite, pytest; React 18 + TypeScript + Vite + Tailwind, `@tanstack/react-query`, vitest + Testing Library. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-08-requests-admin-design.md`

## Global Constraints

- Never use em-dashes or `--` in code, comments, copy or docs (a hyphen inside a Tailwind class is fine).
- The repo is public: no passwords, tokens or IP addresses.
- Branch `main`. Commit trailer `Claude-Session: https://claude.ai/code/session_017Cc8iouqJoYhUcnJhhgapA`. No `Co-Authored-By`.
- Tests never import `app.py`; routes are checked on source text via a `_src()` helper. Every DB-touching test file carries its own `_isolated_db` autouse fixture (copy the block from `tests/test_library_admin.py` lines 1 to 40). No `tests/conftest.py`. No test reaches the network.
- Mutation-check each new load-bearing test. Backend: `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/ -q -p no:cacheprovider` (904 passed at HEAD 83f68a0). Frontend: `cd frontend && npx tsc --noEmit && npx vitest run` (223 passed). `npm run build` output in `static/app/` is committed with any frontend change.
- Admin guard shape: `if not auth.is_admin(): return jsonify(error="admin required"), 403`. Action routes return JSON `{ok, message}`.
- `user_requests.status` values are `pending, approved, denied`. `users.quota_monthly` of 0 means unlimited. `users.role` is `admin` or `user`; `users.enabled` is 0 or 1.
- Copy: plain English, no code words in labels. Card titles are short nouns.
- Existing helpers used as is: `db.get_user_requests`, `db.get_user_request(req_id)`, `db.update_user_request_status(req_id, status, reviewed_by=None, note=None)`, `db.count_user_requests_this_month(user_id)`, `db.list_users()`, `db.get_user(user_id)`, `db.create_user_request(user_id, imdb_id, tmdb_id, media_type, title, seasons=None, status="pending")`, `db.create_user(username, password_hash, role="user", quota_monthly=0, auto_approve=False)`, `db.insert_request(title, imdb_id, media_type, seasons=None, tmdb_id=None)`, `db.update_request(row_id, status, ...)`, `quota.get_quota(user) -> {used, limit, resets_at, unlimited}`, `auth.current_user_record()`. Frontend: `api.userRequests`, `api.approveRequest(id)`, `api.denyRequest(id, note?)`, `api.deleteRequest(id)`, `api.users() -> {users}`, `api.autoApproveGenreRules`, `api.setAutoApproveGenreRules`, `api.genres`, `api.runAutoApproveNow`, `api.addToLibrary`; primitives `Button` (`variant: 'default'|'primary'|'ghost'`, `loading`), `Select({value, onChange, options, label, placeholder?, className?})`, `Pill`, `statusLabel`, `statusToPillState`, `Card`, `GenreRuleRows`; Library kit `pages/admin/library/TitleDrawer.tsx` (`{imdb, onClose, onChanged, onPurged?}`), `library/cards/DrawerCard.tsx` (`ActionButton({label, run, onDone, variant?, confirm?})`), `library/actions.ts` (`ACTIONS`), and `library/Library.tsx` as the layout reference (rail at `md:grid-cols-[14rem_1fr]`, paging strip lines 50 to 58).

## File structure

| File | Responsibility |
|---|---|
| `requests_admin.py` (new) | `list_requests(filters) -> (rows, total)`, `view_counts()`, `quota_rows()`; the view and sort vocabularies |
| `quota.py` | `allows(user) -> (ok, info)` next to `get_quota` |
| `db.py` | index `user_requests(status, created_at DESC)`; `reopen_user_request(req_id) -> bool` |
| `app.py` | `GET /ui/api/admin/requests`, `GET /ui/api/admin/requests/views`, `GET /ui/api/admin/quotas`, `POST /ui/api/user-requests/<id>/reopen`; enforcement in `ui_api_discover_add`; delete `ui_api_all_requests` |
| `frontend/src/api.ts` | `AdminRequestRow`, `AdminRequestPage`, `QuotaRow`; `adminRequests`, `adminRequestViews`, `adminQuotas`, `reopenRequest`; delete `requestsAll` |
| `frontend/src/pages/admin/requests/state.ts` | hash state for `#requests?` |
| `frontend/src/pages/admin/requests/Rail.tsx`, `RequestTable.tsx`, `RowActions.tsx`, `QuotasCard.tsx`, `AutoApproveCard.tsx` | the UI units |
| `frontend/src/pages/admin/Requests.tsx` | the shell (replaced) |
| `frontend/src/pages/admin/library/TitleDrawer.tsx`, `library/actions.ts` | Forget button |
| `frontend/src/components/DetailModal/index.tsx` | quota toast on 409 |
| `README.md`, `CHANGELOG.md` | docs |

---

### Task 1: `requests_admin.list_requests`, views, index and the two list endpoints

**Files:**
- Create: `requests_admin.py`
- Modify: `db.py` (index next to `idx_wanted_episodes_imdb_status`), `app.py` (two routes after `ui_api_library_views`)
- Test: `tests/test_requests_admin.py` (new)

**Interfaces:**
- Produces: `requests_admin.VIEWS = ("pending", "approved", "denied", "all")`, `SORTS`, `list_requests(filters: dict) -> tuple[list[dict], int]` with filter keys `view, user, type, added, q, sort, order, page, per_page`; `view_counts() -> dict[str, int]`; routes `GET /ui/api/admin/requests` returning `{rows, total, page, per_page}` and `GET /ui/api/admin/requests/views` returning `{counts}`.
- Row shape: `id, imdb_id, tmdb_id, title, media_type, seasons, status, note, created_at, reviewed_at, user_id, username, reviewer (str|None), library_status (str|None)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_requests_admin.py`:

```python
"""requests_admin: the read model behind the admin Requests tab."""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db
import requests_admin as ra

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
def seeded():
    """Three users, every status, movie and series. Returns ids by name."""
    adam = db.create_user("adam", "scrypt$x$y", role="user", quota_monthly=2)
    bea = db.create_user("bea", "scrypt$x$y", role="user", quota_monthly=0)
    root = db.create_user("root", "scrypt$x$y", role="admin")
    r1 = db.create_user_request(adam, "tt1", 1, "movie", "Heat")                      # pending
    r2 = db.create_user_request(adam, "tt2", 2, "series", "Loki")                     # approved, in library
    r3 = db.create_user_request(bea, "tt3", 3, "movie", "Alien")                      # denied with note
    r4 = db.create_user_request(bea, "tt4", 4, "movie", "Dune")                       # pending
    db.update_user_request_status(r2, "approved", reviewed_by=root)
    db.update_user_request_status(r3, "denied", reviewed_by=root, note="too big")
    db.insert_request("Loki", "tt2", "series")
    db.update_request(db.get_request_by_imdb("tt2")["id"], "success")
    with db._connect() as conn:
        conn.execute("UPDATE user_requests SET created_at = datetime('now', '-40 days') WHERE id = ?", (r3,))
        conn.execute("UPDATE user_requests SET created_at = datetime('now', '-2 days') WHERE id = ?", (r1,))
        conn.commit()
    return {"adam": adam, "bea": bea, "root": root, "r1": r1, "r2": r2, "r3": r3, "r4": r4}


def _ids(rows):
    return [r["id"] for r in rows]


def test_default_listing_is_every_request_newest_first_with_joined_columns(seeded):
    rows, total = ra.list_requests({})
    assert total == 4 and _ids(rows) == [seeded["r4"], seeded["r2"], seeded["r1"], seeded["r3"]]
    by = {r["id"]: r for r in rows}
    assert by[seeded["r2"]]["username"] == "adam" and by[seeded["r2"]]["reviewer"] == "root"
    assert by[seeded["r2"]]["library_status"] == "success"
    assert by[seeded["r1"]]["reviewer"] is None and by[seeded["r1"]]["library_status"] is None
    assert by[seeded["r3"]]["note"] == "too big"
    assert set(rows[0]) == {"id", "imdb_id", "tmdb_id", "title", "media_type", "seasons", "status", "note",
                            "created_at", "reviewed_at", "user_id", "username", "reviewer", "library_status"}


@pytest.mark.parametrize("view,key", [("pending", ["r1", "r4"]), ("approved", ["r2"]), ("denied", ["r3"]),
                                      ("all", ["r1", "r2", "r3", "r4"])])
def test_views_select_exactly_their_rows(seeded, view, key):
    rows, total = ra.list_requests({"view": view})
    assert set(_ids(rows)) == {seeded[k] for k in key} and total == len(key)


def test_pending_view_sorts_oldest_first(seeded):
    rows, _ = ra.list_requests({"view": "pending"})
    assert _ids(rows) == [seeded["r1"], seeded["r4"]]


def test_view_counts_match(seeded):
    assert ra.view_counts() == {"pending": 2, "approved": 1, "denied": 1, "all": 4}


@pytest.mark.parametrize("filters,key", [
    ({"user": "adam"}, ["r1", "r2"]),
    ({"type": "series"}, ["r2"]),
    ({"type": "movie", "view": "pending"}, ["r1", "r4"]),
    ({"added": "7d"}, ["r1", "r2", "r4"]),
    ({"added": "24h"}, ["r2", "r4"]),
    ({"q": "ali"}, ["r3"]),
    ({"q": "tt4"}, ["r4"]),
])
def test_filters(seeded, filters, key):
    if "user" in filters:
        filters = {**filters, "user": str(seeded[filters["user"]])}
    rows, _ = ra.list_requests(filters)
    assert set(_ids(rows)) == {seeded[k] for k in key}


def test_search_escapes_like_wildcards(seeded):
    db.create_user_request(seeded["bea"], "tt5", 5, "movie", "Silo_S1")
    db.create_user_request(seeded["bea"], "tt6", 6, "movie", "SiloXS1")
    rows, _ = ra.list_requests({"q": "Silo_"})
    assert [r["title"] for r in rows] == ["Silo_S1"]


def test_sorting_and_paging(seeded):
    rows, total = ra.list_requests({"sort": "title", "order": "asc", "per_page": 2, "page": 2})
    assert total == 4 and [r["title"] for r in rows] == ["Heat", "Loki"], "Alien, Dune | Heat, Loki"
    rows, _ = ra.list_requests({"sort": "user", "order": "desc"})
    assert [r["username"] for r in rows][:2] == ["bea", "bea"]
    rows, _ = ra.list_requests({"sort": "reviewed", "order": "desc"})
    assert rows[0]["id"] in (seeded["r2"], seeded["r3"]) and rows[-1]["reviewed_at"] is None
    rows, _ = ra.list_requests({"per_page": 1000})
    assert len(rows) == 4


def test_unknown_values_are_ignored_not_errors(seeded):
    rows, total = ra.list_requests({"view": "bogus", "sort": "DROP", "user": "x", "page": "y", "type": "cartoon"})
    assert total == 0
    rows, total = ra.list_requests({"sort": "DROP", "user": "x", "page": "y", "type": "cartoon"})
    assert total == 4


def test_the_index_exists():
    with db._connect() as conn:
        names = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_user_requests_status_created" in names


def test_the_routes_exist_and_are_admin_only():
    src = _src("app.py")
    for route in ('@app.get("/ui/api/admin/requests")', '@app.get("/ui/api/admin/requests/views")'):
        assert route in src, route
        body = src.split(route, 1)[1].split("\n\n\n", 1)[0]
        assert "auth.is_admin()" in body and "requests_admin" in body
```

`test_unknown_values_are_ignored_not_errors`: an unknown view yields nothing (like Library); unknown sort, user, page and type fall back to defaults or are ignored.

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/test_requests_admin.py -q -p no:cacheprovider`
Expected: `ModuleNotFoundError: No module named 'requests_admin'`.

- [ ] **Step 3: Index in `db.init()`**

Next to `idx_wanted_episodes_imdb_status`:

```python
        conn.execute("CREATE INDEX IF NOT EXISTS idx_user_requests_status_created ON user_requests(status, created_at DESC)")
```

- [ ] **Step 4: `requests_admin.py`**

```python
"""The read model behind the admin Requests tab.

One SELECT over user_requests joined to users twice (requester and
reviewer) and left-joined to requests for the library status, wrapped so
views and filters reference the computed columns, plus a COUNT with the
same WHERE. Same shape as library_admin so the two rails behave alike.
"""
from __future__ import annotations

import db

VIEWS = ("pending", "approved", "denied", "all")
SORTS = {
    "created": "t.created_at",
    "reviewed": "t.reviewed_at",
    "user": "t.username COLLATE NOCASE",
    "title": "t.title COLLATE NOCASE",
}
MAX_PER_PAGE = 200
DEFAULT_PER_PAGE = 50

_BASE = """
SELECT ur.id, ur.imdb_id, ur.tmdb_id, ur.title, ur.media_type, ur.seasons, ur.status, ur.note,
       ur.created_at, ur.reviewed_at, ur.user_id, u.username, rv.username AS reviewer,
       r.status AS library_status
FROM user_requests ur
JOIN users u ON u.id = ur.user_id
LEFT JOIN users rv ON rv.id = ur.reviewed_by
LEFT JOIN requests r ON r.imdb_id = ur.imdb_id
"""

_VIEW_WHERE = {"all": "1=1", "pending": "t.status = 'pending'",
               "approved": "t.status = 'approved'", "denied": "t.status = 'denied'"}
_VIEW_ORDER = {"pending": "t.created_at ASC, t.id ASC"}
_ADDED = {"24h": "-1 day", "7d": "-7 days", "30d": "-30 days"}


def _like(q: str) -> str:
    q = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{q}%"


def _int(value, default: int, lo: int, hi: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _where(filters: dict) -> tuple[str, list]:
    clauses = [_VIEW_WHERE.get(filters.get("view") or "all", "0=1")]
    args: list = []
    user = filters.get("user")
    if user and str(user).isdigit():
        clauses.append("t.user_id = ?")
        args.append(int(user))
    kind = filters.get("type")
    if kind == "movie":
        clauses.append("t.media_type = 'movie'")
    elif kind == "series":
        clauses.append("t.media_type != 'movie'")
    added = _ADDED.get(filters.get("added") or "")
    if added:
        clauses.append("t.created_at >= datetime('now', ?)")
        args.append(added)
    q = (filters.get("q") or "").strip()
    if q:
        clauses.append("(t.title LIKE ? ESCAPE '\\' OR t.imdb_id LIKE ? ESCAPE '\\')")
        args += [_like(q), _like(q)]
    return " AND ".join(clauses), args


def _order(filters: dict) -> str:
    sort = filters.get("sort")
    if sort in SORTS:
        direction = "ASC" if (filters.get("order") or "").lower() == "asc" else "DESC"
        col = SORTS[sort]
        if sort == "reviewed":
            return f"{col} IS NULL, {col} {direction}, t.id DESC"
        return f"{col} {direction}, t.id DESC"
    return _VIEW_ORDER.get(filters.get("view") or "all", "t.created_at DESC, t.id DESC")


def list_requests(filters: dict) -> tuple[list[dict], int]:
    where, args = _where(filters)
    per_page = _int(filters.get("per_page"), DEFAULT_PER_PAGE, 1, MAX_PER_PAGE)
    page = _int(filters.get("page"), 1, 1, 10_000_000)
    with db._connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM ({_BASE}) t WHERE {where}", args).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM ({_BASE}) t WHERE {where} ORDER BY {_order(filters)} LIMIT ? OFFSET ?",
            args + [per_page, (page - 1) * per_page]).fetchall()
    return [dict(r) for r in rows], total


def view_counts() -> dict[str, int]:
    with db._connect() as conn:
        return {v: conn.execute(f"SELECT COUNT(*) FROM ({_BASE}) t WHERE {_VIEW_WHERE[v]}").fetchone()[0]
                for v in VIEWS}
```

- [ ] **Step 5: Routes in `app.py`** (after `ui_api_library_views`)

```python
@app.get("/ui/api/admin/requests")
def ui_api_admin_requests():
    """The Requests tab's table: views, filters, sort and paging in SQL."""
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import requests_admin
    filters = {k: request.args.get(k) for k in
               ("view", "user", "type", "added", "q", "sort", "order", "page", "per_page")}
    rows, total = requests_admin.list_requests(filters)
    return jsonify(rows=rows, total=total,
                   page=requests_admin._int(filters["page"], 1, 1, 10_000_000),
                   per_page=requests_admin._int(filters["per_page"], requests_admin.DEFAULT_PER_PAGE, 1,
                                                requests_admin.MAX_PER_PAGE))


@app.get("/ui/api/admin/requests/views")
def ui_api_admin_request_views():
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import requests_admin
    return jsonify(counts=requests_admin.view_counts())
```

- [ ] **Step 6: Run, mutation-check, commit**

Full suite green. Mutation: make the `pending` view order `DESC`: `test_pending_view_sorts_oldest_first` must fail. Restore. Delete `__pycache__`.

```bash
git add requests_admin.py db.py app.py tests/test_requests_admin.py
git commit -m "feat(requests): admin read model with views, filters and paging

Claude-Session: https://claude.ai/code/session_017Cc8iouqJoYhUcnJhhgapA"
```

---

### Task 2: Quota rule and enforcement, quotas endpoint, reopen, orphan removal

**Files:**
- Modify: `quota.py`, `db.py` (after `get_user_request`), `requests_admin.py` (append `quota_rows`), `app.py` (`ui_api_discover_add`; routes after the views route; delete `ui_api_all_requests`), `frontend/src/api.ts` (delete `requestsAll` and its type if unused elsewhere)
- Test: `tests/test_quota_rules.py` (new), `tests/test_requests_admin.py` (append)

**Interfaces:**
- Produces: `quota.allows(user: dict | None) -> tuple[bool, dict]` where `info` is `get_quota(user)` plus `"reason": "quota reached"` when not ok; admins and unlimited users are always ok. `requests_admin.quota_rows() -> list[dict]` with `user_id, username, used, limit, remaining, unlimited, resets_at, auto_approve, paused`. `db.reopen_user_request(req_id) -> bool`. Routes: `GET /ui/api/admin/quotas -> {rows}`, `POST /ui/api/user-requests/<int:req_id>/reopen -> {ok, message}`. `POST /ui/api/discover/add` returns `409 {error, used, limit, resets_at}` when refused; an auto-approve user at the cap gets `status: "pending"` and the note `auto-approve paused: monthly quota reached`.

- [ ] **Step 1: Failing tests**

`tests/test_quota_rules.py`:

```python
"""quota.allows: the one rule behind request quotas, and the routes that
apply it (checked on source text; tests never import app.py)."""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db
import quota

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


def _user(name, role="user", cap=0, auto=False):
    uid = db.create_user(name, "scrypt$x$y", role=role, quota_monthly=cap, auto_approve=auto)
    return db.get_user(uid)


def test_unlimited_and_admin_users_are_always_allowed():
    ok, info = quota.allows(_user("free"))
    assert ok and info["unlimited"] is True
    root = _user("root", role="admin", cap=1)
    db.create_user_request(root["id"], "tt1", 1, "movie", "A")
    db.create_user_request(root["id"], "tt2", 2, "movie", "B")
    assert quota.allows(root)[0] is True
    assert quota.allows(None)[0] is True


def test_a_capped_user_is_refused_at_the_cap_with_the_numbers():
    u = _user("adam", cap=2)
    assert quota.allows(u)[0] is True
    db.create_user_request(u["id"], "tt1", 1, "movie", "A")
    ok, info = quota.allows(u)
    assert ok is True and info["used"] == 1 and info["limit"] == 2
    db.create_user_request(u["id"], "tt2", 2, "movie", "B")
    ok, info = quota.allows(u)
    assert ok is False and info["reason"] == "quota reached" and info["used"] == 2
    assert info["resets_at"].endswith("-01T00:00:00Z")


def test_the_add_route_refuses_with_409_and_downgrades_auto_approve():
    body = _src("app.py").split('@app.post("/ui/api/discover/add")', 1)[1].split("\n\n\n", 1)[0]
    assert "quota.allows(user_rec)" in body
    assert "409" in body and '"quota reached"' in body
    assert "auto-approve paused: monthly quota reached" in body
    assert body.index("quota.allows(user_rec)") < body.index("db.create_user_request(")


def test_reopen_helper_only_reopens_denied_rows():
    u = _user("adam")
    root = _user("root", role="admin")
    rid = db.create_user_request(u["id"], "tt1", 1, "movie", "A")
    assert db.reopen_user_request(rid) is False, "pending stays pending"
    db.update_user_request_status(rid, "denied", reviewed_by=root["id"], note="no")
    assert db.reopen_user_request(rid) is True
    row = db.get_user_request(rid)
    assert row["status"] == "pending" and row["reviewed_by"] is None and row["reviewed_at"] is None and row["note"] is None
    assert db.reopen_user_request(999) is False


def test_reopen_and_quota_routes_exist_and_the_orphan_is_gone():
    src = _src("app.py")
    for route in ('@app.post("/ui/api/user-requests/<int:req_id>/reopen")', '@app.get("/ui/api/admin/quotas")'):
        assert route in src, route
        body = src.split(route, 1)[1].split("\n\n\n", 1)[0]
        assert "auth.is_admin()" in body
    assert '"/ui/api/requests/all"' not in src
    assert "requestsAll" not in _src("frontend/src/api.ts")
```

Append to `tests/test_requests_admin.py`:

```python
def test_quota_rows_cover_enabled_non_admin_users(seeded):
    db.update_user(seeded["adam"], auto_approve=1)
    db.create_user_request(seeded["adam"], "tt9", 9, "movie", "Third")
    carl = db.create_user("carl", "scrypt$x$y", role="user", quota_monthly=5)
    db.update_user(carl, enabled=0)
    rows = ra.quota_rows()
    assert [r["username"] for r in rows] == ["adam", "bea"], "admins and disabled users are left out"
    adam = rows[0]
    # r1 sits two days back; on the 1st or 2nd of a month it falls into last month, so allow 2 or 3
    assert adam["used"] in (2, 3) and adam["limit"] == 2 and adam["remaining"] == 0
    assert adam["unlimited"] is False and adam["auto_approve"] is True and adam["paused"] is True
    bea = rows[1]
    assert bea["unlimited"] is True and bea["remaining"] is None and bea["paused"] is False
    assert adam["resets_at"].endswith("-01T00:00:00Z")
```

Check `db.update_user(user_id, **fields)` accepts `auto_approve` and `enabled` (its `_CORE` set does).

- [ ] **Step 2: Run, verify failure** (`AttributeError: module 'quota' has no attribute 'allows'`).

- [ ] **Step 3: `quota.allows`**

Append to `quota.py`:

```python
def allows(user: dict | None) -> tuple[bool, dict]:
    """The one quota rule. Admins and users with no cap always pass; a
    capped user passes while used < limit. The info dict is get_quota()
    plus a reason when refused, so a route can hand it to the client."""
    info = get_quota(user)
    if not user or user.get("role") == "admin" or info["unlimited"]:
        return True, info
    if info["used"] >= info["limit"]:
        return False, {**info, "reason": "quota reached"}
    return True, info
```

- [ ] **Step 4: `db.reopen_user_request`** (after `get_user_request`)

```python
def reopen_user_request(req_id: int) -> bool:
    """A denied request goes back to pending with the review cleared.
    Returns False when the row is missing or not denied."""
    with _connect() as conn:
        cur = conn.execute(
            """UPDATE user_requests SET status='pending', reviewed_by=NULL, reviewed_at=NULL, note=NULL
               WHERE id=? AND status='denied'""", (req_id,))
        conn.commit()
        return cur.rowcount == 1
```

- [ ] **Step 5: `requests_admin.quota_rows`** (append)

```python
def quota_rows() -> list[dict]:
    """One row per enabled non-admin user for the Quotas card."""
    import quota
    out = []
    for u in sorted(db.list_users(), key=lambda x: (x["username"] or "").lower()):
        if u.get("role") == "admin" or not u.get("enabled", 1):
            continue
        q = quota.get_quota(u)
        auto = bool(u.get("auto_approve"))
        at_cap = (not q["unlimited"]) and q["used"] >= q["limit"]
        out.append({"user_id": u["id"], "username": u["username"], "used": q["used"], "limit": q["limit"],
                    "remaining": None if q["unlimited"] else max(0, q["limit"] - q["used"]),
                    "unlimited": q["unlimited"], "resets_at": q["resets_at"],
                    "auto_approve": auto, "paused": auto and at_cap})
    return out
```

- [ ] **Step 6: Routes and enforcement in `app.py`**

Delete the whole `ui_api_all_requests` route (lines 2206 to 2210: decorator, def, two body lines) and `requestsAll` from `frontend/src/api.ts` (grep its type; delete it too if nothing else uses it).

In `ui_api_discover_add`, replace the multi-user block:

```python
    user_rec = auth.current_user_record()
    if user_rec and user_rec.get("id"):
        # Multi-user mode: go through approval flow, quota first
        ok, info = quota.allows(user_rec)
        auto = bool(user_rec.get("auto_approve")) or user_rec.get("role") == "admin"
        if not ok and not auto:
            return jsonify(error="quota reached", used=info["used"], limit=info["limit"],
                           resets_at=info["resets_at"]), 409
        status = "approved" if auto and ok else "pending"
        rid = db.create_user_request(user_rec["id"], imdb_id, tmdb_id, media_type,
                                       title, status=status)
        if not ok:
            db.update_user_request_status(rid, "pending", note="auto-approve paused: monthly quota reached")
        if status == "approved":
            _kick_off_processing(title, imdb_id, media_type, tmdb_id, monitor_mode, seasons)
        return jsonify(status=status, request_id=rid, imdb_id=imdb_id)
```

`quota` is already imported at the top of `app.py` (it serves `/ui/api/me/quota`); confirm with grep. Note an admin is never refused: `auto` is true for admins and `allows` returns ok for them, so they take the approved path.

After the views route:

```python
@app.get("/ui/api/admin/quotas")
def ui_api_admin_quotas():
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import requests_admin
    return jsonify(rows=requests_admin.quota_rows())


@app.post("/ui/api/user-requests/<int:req_id>/reopen")
def ui_api_user_request_reopen(req_id: int):
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    if db.reopen_user_request(req_id):
        return jsonify(ok=True, message="back in the pending list")
    return jsonify(ok=False, message="only a denied request can be reopened")
```

- [ ] **Step 7: Run, mutation-check, commit**

Full backend suite plus `cd frontend && npx tsc --noEmit` (the `requestsAll` removal must not break a type). Mutation: change `allows` to `info["used"] > info["limit"]`: the capped-user test must fail. Restore.

```bash
git add quota.py db.py requests_admin.py app.py frontend/src/api.ts tests/test_quota_rules.py tests/test_requests_admin.py
git commit -m "feat(requests): quota rule enforced on request creation, quotas endpoint, reopen route

Claude-Session: https://claude.ai/code/session_017Cc8iouqJoYhUcnJhhgapA"
```

---

### Task 3: Frontend types, hash state, rail, table and paging

**Files:**
- Modify: `frontend/src/api.ts`
- Create: `frontend/src/pages/admin/requests/state.ts`, `state.test.ts`, `fixtures.ts` (test fixture `row`), `Rail.tsx`, `RequestTable.tsx`
- Replace: `frontend/src/pages/admin/Requests.tsx` (shell; the pending and auto-approve panels come back in Tasks 4 and 5, so the old file's `AutoApprovePanel` code must be preserved: copy it verbatim into `frontend/src/pages/admin/requests/AutoApproveCard.tsx` in this task, exported as `AutoApproveCard`, unmounted until Task 5)
- Test: `frontend/src/pages/admin/Requests.test.tsx` (rewritten)

**Interfaces:**
- `api.ts`: `AdminRequestRow { id, imdb_id, tmdb_id, title, media_type, seasons, status: 'pending'|'approved'|'denied', note, created_at, reviewed_at, user_id, username, reviewer, library_status }`, `AdminRequestPage { rows, total, page, per_page }`, `api.adminRequests(params)`, `api.adminRequestViews() -> { counts: Record<string, number> }`.
- `state.ts`: `RequestsState { view, q, user, type, added, sort, order, page, perPage, open }`, `DEFAULT_STATE`, `parseHash`, `toHash` (`#requests?...`), `toQuery`.
- `Rail({ state, counts, users, onChange })`, `RequestTable({ rows, sort, order, onSort, onOpen, renderActions })` where `renderActions(row) => ReactNode` is filled by Task 4 (this task passes `() => null`).

- [ ] **Step 1: `api.ts` additions**

```ts
export interface AdminRequestRow {
  id: number; imdb_id: string; tmdb_id: number | null; title: string; media_type: string; seasons: string | null;
  status: 'pending' | 'approved' | 'denied'; note: string | null; created_at: string; reviewed_at: string | null;
  user_id: number; username: string; reviewer: string | null; library_status: string | null;
}
export interface AdminRequestPage { rows: AdminRequestRow[]; total: number; page: number; per_page: number }
```

in `api`:

```ts
  adminRequests: (params: Record<string, string>) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v !== '' && qs.append(k, v));
    return http<AdminRequestPage>(`/ui/api/admin/requests?${qs.toString()}`);
  },
  adminRequestViews: () => http<{ counts: Record<string, number> }>('/ui/api/admin/requests/views'),
```

- [ ] **Step 2: Failing `state.test.ts`**

```ts
import { describe, it, expect } from 'vitest';
import { DEFAULT_STATE, parseHash, toHash, toQuery } from './state';

describe('requests hash state', () => {
  it('round-trips and drops defaults', () => {
    const s = { ...DEFAULT_STATE, view: 'denied', q: 'heat', user: '3', page: 2, open: 'tt1' };
    const h = toHash(s);
    expect(h).toBe('#requests?view=denied&q=heat&user=3&page=2&open=tt1');
    expect(parseHash(h)).toEqual(s);
    expect(toHash(DEFAULT_STATE)).toBe('#requests');
    expect(parseHash('#library?view=queue')).toEqual(DEFAULT_STATE);
  });
  it('ignores junk', () => {
    const s = parseHash('#requests?view=bogus&type=cartoon&added=1y&sort=nope&order=up&page=0');
    expect(s).toEqual(DEFAULT_STATE);
  });
  it('serialises to query params', () => {
    expect(toQuery({ ...DEFAULT_STATE, view: 'pending', user: '3' })).toEqual({
      view: 'pending', q: '', user: '3', type: '', added: '', sort: '', order: 'desc', page: '1', per_page: '50',
    });
  });
});
```

- [ ] **Step 3: `state.ts`**

```ts
export const VIEWS = ['pending', 'approved', 'denied', 'all'] as const;
export const SORTS = ['created', 'reviewed', 'user', 'title'] as const;

export type RequestsState = {
  view: string; q: string; user: string; type: string; added: string;
  sort: string; order: 'asc' | 'desc'; page: number; perPage: number; open: string | null;
};

export const DEFAULT_STATE: RequestsState = {
  view: 'pending', q: '', user: '', type: '', added: '', sort: '', order: 'desc', page: 1, perPage: 50, open: null,
};

export function parseHash(hash: string): RequestsState {
  const [tab, query = ''] = hash.replace(/^#/, '').split('?');
  if (tab !== 'requests') return { ...DEFAULT_STATE };
  const p = new URLSearchParams(query);
  const pick = (k: string, allowed: readonly string[]) => (allowed.includes(p.get(k) || '') ? (p.get(k) as string) : '');
  const page = parseInt(p.get('page') || '1', 10);
  const perPage = parseInt(p.get('per_page') || '50', 10);
  return {
    view: pick('view', VIEWS) || 'pending',
    q: p.get('q') || '',
    user: /^\d+$/.test(p.get('user') || '') ? (p.get('user') as string) : '',
    type: pick('type', ['movie', 'series']),
    added: pick('added', ['24h', '7d', '30d']),
    sort: pick('sort', SORTS),
    order: p.get('order') === 'asc' ? 'asc' : 'desc',
    page: Number.isFinite(page) && page > 0 ? page : 1,
    perPage: [25, 50, 100, 200].includes(perPage) ? perPage : 50,
    open: p.get('open') || null,
  };
}

export function toHash(s: RequestsState): string {
  const p = new URLSearchParams();
  if (s.view !== 'pending') p.set('view', s.view);
  if (s.q) p.set('q', s.q);
  if (s.user) p.set('user', s.user);
  if (s.type) p.set('type', s.type);
  if (s.added) p.set('added', s.added);
  if (s.sort) { p.set('sort', s.sort); if (s.order !== 'desc') p.set('order', s.order); }
  if (s.page !== 1) p.set('page', String(s.page));
  if (s.perPage !== 50) p.set('per_page', String(s.perPage));
  if (s.open) p.set('open', s.open);
  const q = p.toString();
  return q ? `#requests?${q}` : '#requests';
}

export function toQuery(s: RequestsState): Record<string, string> {
  return { view: s.view, q: s.q, user: s.user, type: s.type, added: s.added, sort: s.sort, order: s.order,
    page: String(s.page), per_page: String(s.perPage) };
}
```

The default view is Pending, so `#requests` opens on what needs attention.

- [ ] **Step 4: Failing `Requests.test.tsx`** (rewrite the file)

```tsx
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import Requests from './Requests';
import { row } from './requests/fixtures';

const apiMocks = vi.hoisted(() => ({
  adminRequests: vi.fn(), adminRequestViews: vi.fn(), users: vi.fn(), adminQuotas: vi.fn(),
  approveRequest: vi.fn(), denyRequest: vi.fn(), reopenRequest: vi.fn(),
  autoApproveGenreRules: vi.fn(), genres: vi.fn(), libraryDetail: vi.fn(),
}));
vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return { ...actual, api: { ...actual.api, ...apiMocks } };
});

function renderIt(hash = '#requests') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <MemoryRouter initialEntries={[`/admin${hash}`]}>
      <QueryClientProvider client={qc}><Requests /></QueryClientProvider>
    </MemoryRouter>,
  );
}

describe('Requests tab', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.adminRequestViews.mockResolvedValue({ counts: { pending: 2, approved: 1, denied: 1, all: 4 } });
    apiMocks.users.mockResolvedValue({ users: [{ id: 3, username: 'adam' }, { id: 4, username: 'bea' }] });
    apiMocks.adminQuotas.mockResolvedValue({ rows: [] });
    apiMocks.autoApproveGenreRules.mockResolvedValue({ rules: [] });
    apiMocks.genres.mockResolvedValue({ genres: [{ id: 1, name: 'Action' }] });
    apiMocks.adminRequests.mockResolvedValue({
      rows: [row({}), row({ id: 2, imdb_id: 'tt2', title: 'Loki', media_type: 'series', status: 'approved', username: 'adam',
        reviewer: 'root', reviewed_at: '2026-09-02 10:00:00', library_status: 'success' })],
      total: 2, page: 1, per_page: 50,
    });
  });

  it('renders views with counts and the table, defaulting to Pending', async () => {
    renderIt();
    const nav = await screen.findByRole('navigation', { name: 'Request views' });
    await waitFor(() => expect(within(nav).getByRole('button', { name: /Pending/ })).toHaveTextContent('2'));
    expect(await screen.findByText('Heat')).toBeInTheDocument();
    const loki = screen.getByText('Loki').closest('tr')!;
    expect(within(loki).getByText('root')).toBeInTheDocument();
    expect(within(loki).getByText('In library')).toBeInTheDocument();
    expect(within(screen.getByText('Heat').closest('tr')!).getByText('not in library')).toBeInTheDocument();
    expect(apiMocks.adminRequests).toHaveBeenCalledWith(expect.objectContaining({ view: 'pending', page: '1' }));
  });

  it('a view click and a filter re-query and update the hash', async () => {
    renderIt();
    await userEvent.click(await screen.findByRole('button', { name: /Denied/ }));
    await waitFor(() => expect(apiMocks.adminRequests).toHaveBeenLastCalledWith(expect.objectContaining({ view: 'denied' })));
    expect(screen.getByTestId('requests-hash').textContent).toContain('view=denied');
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'User' }), '4');
    await waitFor(() => expect(apiMocks.adminRequests).toHaveBeenLastCalledWith(expect.objectContaining({ user: '4', page: '1' })));
  });

  it('restores from the hash, pages and sorts', async () => {
    apiMocks.adminRequests.mockResolvedValue({ rows: [row({})], total: 120, page: 2, per_page: 50 });
    renderIt('#requests?view=all&page=2');
    await waitFor(() => expect(apiMocks.adminRequests).toHaveBeenCalledWith(expect.objectContaining({ view: 'all', page: '2' })));
    expect(await screen.findByText(/51 to 100 of 120/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Next page' }));
    await waitFor(() => expect(apiMocks.adminRequests).toHaveBeenLastCalledWith(expect.objectContaining({ page: '3' })));
    await userEvent.click(screen.getByRole('button', { name: 'Sort by user' }));
    await waitFor(() => expect(apiMocks.adminRequests).toHaveBeenLastCalledWith(expect.objectContaining({ sort: 'user', order: 'asc' })));
  });

  it('shows the empty state for the view', async () => {
    apiMocks.adminRequests.mockResolvedValue({ rows: [], total: 0, page: 1, per_page: 50 });
    renderIt();
    expect(await screen.findByText('No requests waiting for review')).toBeInTheDocument();
  });
});
```

`frontend/src/pages/admin/requests/fixtures.ts` (a plain module, so importing it never re-registers a test suite):

```ts
import type { AdminRequestRow } from '../../../api';

export const row = (over: Partial<AdminRequestRow>): AdminRequestRow => ({
  id: 1, imdb_id: 'tt1', tmdb_id: 1, title: 'Heat', media_type: 'movie', seasons: null, status: 'pending', note: null,
  created_at: '2026-09-01 10:00:00', reviewed_at: null, user_id: 3, username: 'adam', reviewer: null, library_status: null,
  ...over,
});
```

The Task 4 and 5 mocks (`adminQuotas`, `reopenRequest`, `libraryDetail`) are declared now so this file does not change shape later.

- [ ] **Step 5: Components**

`Rail.tsx`:

```tsx
import { Button, Select } from '../../../components/primitives';
import { VIEWS } from './state';
import type { RequestsState } from './state';

const VIEW_LABEL: Record<string, string> = { pending: 'Pending', approved: 'Approved', denied: 'Denied', all: 'All' };

export function Rail({ state, counts, users, onChange }: {
  state: RequestsState; counts: Record<string, number>; users: { id: number; username: string }[];
  onChange: (patch: Partial<RequestsState>) => void;
}) {
  const active = state.q || state.user || state.type || state.added;
  return (
    <aside className="space-y-4">
      <nav aria-label="Request views" className="space-y-0.5">
        {VIEWS.map((v) => (
          <button key={v} type="button" onClick={() => onChange({ view: v, page: 1 })} aria-current={state.view === v ? 'page' : undefined}
            className={`flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-sm ${state.view === v ? 'bg-white/[0.08] text-white' : 'text-muted hover:text-body'}`}>
            <span>{VIEW_LABEL[v]}</span>
            <span className="text-xs text-muted">{counts[v] ?? ''}</span>
          </button>
        ))}
      </nav>
      <div className="space-y-2">
        <input type="search" aria-label="Search requests" placeholder="Title or imdb id" value={state.q}
          onChange={(e) => onChange({ q: e.target.value, page: 1 })} className="w-full rounded border border-border bg-bg px-2 py-1.5 text-xs" />
        <Select label="User" value={state.user} placeholder="Anyone" onChange={(v) => onChange({ user: v, page: 1 })}
          options={users.map((u) => ({ value: String(u.id), label: u.username }))} className="w-full" />
        <Select label="Type" value={state.type} placeholder="Any type" onChange={(v) => onChange({ type: v, page: 1 })}
          options={[{ value: 'movie', label: 'Movies' }, { value: 'series', label: 'Series' }]} className="w-full" />
        <Select label="Added" value={state.added} placeholder="Any time" onChange={(v) => onChange({ added: v, page: 1 })}
          options={[{ value: '24h', label: 'Last 24 hours' }, { value: '7d', label: 'Last 7 days' }, { value: '30d', label: 'Last 30 days' }]} className="w-full" />
        {active ? <Button variant="ghost" onClick={() => onChange({ q: '', user: '', type: '', added: '', page: 1 })}>Clear filters</Button> : null}
      </div>
    </aside>
  );
}
```

`RequestTable.tsx`:

```tsx
import type { ReactNode } from 'react';
import type { AdminRequestRow } from '../../../api';
import { Pill, statusLabel, statusToPillState } from '../../../components/primitives';

const REQUEST_LABEL: Record<string, string> = { pending: 'Pending', approved: 'Approved', denied: 'Denied' };

export function RequestTable({ rows, sort, order, onSort, onOpen, renderActions, loading }: {
  rows: AdminRequestRow[]; sort: string; order: 'asc' | 'desc'; onSort: (col: string) => void;
  onOpen: (imdb: string) => void; renderActions: (row: AdminRequestRow) => ReactNode; loading: boolean;
}) {
  const th = 'px-3 py-2 text-left text-[11px] font-medium uppercase tracking-wider text-muted';
  const header = (key: string, label: string) => (
    <th className={th}>
      <button type="button" aria-label={`Sort by ${label.toLowerCase()}`} onClick={() => onSort(key)} className="hover:text-body">
        {label}{sort === key ? (order === 'asc' ? ' ↑' : ' ↓') : ''}
      </button>
    </th>
  );
  return (
    <div className={`overflow-x-auto rounded-xl border border-border ${loading ? 'opacity-60' : ''}`}>
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border">
            {header('title', 'Title')}{header('user', 'User')}{header('created', 'Requested')}
            <th className={th}>Status</th><th className={th}>Library</th>
            {header('reviewed', 'Reviewed')}<th className={th}>Note</th><th className={th}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-b border-border last:border-0 hover:bg-white/[0.03]">
              <td className="px-3 py-2">
                <button type="button" onClick={() => onOpen(r.imdb_id)} className="text-left font-medium hover:underline">
                  {r.media_type === 'movie' ? '\u{1F3AC}' : '\u{1F4FA}'} <span>{r.title}</span>
                </button>
                <div className="font-mono text-[10px] text-muted">{r.imdb_id}</div>
              </td>
              <td className="px-3 py-2 text-xs"><span>{r.username}</span></td>
              <td className="px-3 py-2 text-xs text-muted">{r.created_at.slice(0, 16)}</td>
              <td className="px-3 py-2"><Pill state={statusToPillState(r.status)}>{REQUEST_LABEL[r.status] || r.status}</Pill></td>
              <td className="px-3 py-2">
                {r.library_status
                  ? <Pill state={statusToPillState(r.library_status)}>{statusLabel(r.library_status)}</Pill>
                  : <span className="text-xs text-muted">not in library</span>}
              </td>
              <td className="px-3 py-2 text-xs text-muted">{r.reviewer ? <><span>{r.reviewer}</span> {r.reviewed_at?.slice(0, 16)}</> : ''}</td>
              <td className="max-w-[12rem] truncate px-3 py-2 text-xs" title={r.note || ''}>{r.note}</td>
              <td className="px-3 py-2">{renderActions(r)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

The shared `statusLabel` renders `pending` as "Processing" (right for a library request, wrong for a request awaiting review), hence the local `REQUEST_LABEL` map for the Status column; the Library column keeps `statusLabel` ("In library" for `success`). `statusToPillState` already maps approved, pending and denied.

`Requests.tsx` (shell):

```tsx
import { useCallback, useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api';
import { Button, Select } from '../../components/primitives';
import { Rail } from './requests/Rail';
import { RequestTable } from './requests/RequestTable';
import { parseHash, toHash, toQuery } from './requests/state';
import type { RequestsState } from './requests/state';

const EMPTY: Record<string, string> = {
  pending: 'No requests waiting for review', approved: 'No approved requests yet',
  denied: 'Nothing denied', all: 'No one has requested anything yet',
};

export default function Requests() {
  const location = useLocation();
  const navigate = useNavigate();
  const [state, setState] = useState<RequestsState>(() => parseHash(location.hash));
  const query = useMemo(() => toQuery(state), [state]);
  const page = useQuery({ queryKey: ['admin-requests', query], queryFn: () => api.adminRequests(query), placeholderData: (p) => p });
  const counts = useQuery({ queryKey: ['admin-request-views'], queryFn: api.adminRequestViews });
  const users = useQuery({ queryKey: ['users'], queryFn: api.users });
  useEffect(() => { navigate({ hash: toHash(state) }, { replace: true }); }, [state, navigate]);
  const update = useCallback((patch: Partial<RequestsState>) => setState((s) => ({ ...s, ...patch })), []);
  const onSort = (col: string) => update({ sort: col, order: state.sort === col && state.order === 'asc' ? 'desc' : 'asc', page: 1 });
  const rows = page.data?.rows || [];
  const total = page.data?.total || 0;
  const first = (state.page - 1) * state.perPage + 1;
  const last = Math.min(total, state.page * state.perPage);

  return (
    <div className="grid gap-6 md:grid-cols-[14rem_1fr]">
      <span data-testid="requests-hash" hidden>{toHash(state)}</span>
      <Rail state={state} counts={counts.data?.counts || {}} users={users.data?.users || []} onChange={update} />
      <main className="space-y-3">
        <RequestTable rows={rows} sort={state.sort} order={state.order} onSort={onSort} loading={page.isFetching}
          onOpen={(id) => update({ open: id })} renderActions={() => null} />
        {!rows.length && !page.isFetching && <p className="text-sm text-muted">{EMPTY[state.view]}</p>}
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
          <span>{total ? `${first} to ${last} of ${total}` : ''}</span>
          <div className="flex items-center gap-2">
            <Select label="Rows per page" value={String(state.perPage)} onChange={(v) => update({ perPage: Number(v), page: 1 })}
              options={[25, 50, 100, 200].map((n) => ({ value: String(n), label: `${n} per page` }))} />
            <Button aria-label="Previous page" disabled={state.page <= 1} onClick={() => update({ page: state.page - 1 })}>Prev</Button>
            <Button aria-label="Next page" disabled={last >= total} onClick={() => update({ page: state.page + 1 })}>Next</Button>
          </div>
        </div>
      </main>
    </div>
  );
}
```

`requests/AutoApproveCard.tsx`: move the old `AutoApprovePanel` function body verbatim (imports: `useState`, `useMutation`, `useQuery`, `useQueryClient`, `api`, `GenreRule`, `Card`, `GenreRuleRows`), renamed `export function AutoApproveCard()`, with the `<section>` and `<h2>` replaced by the Settings-style card header: `<section className="rounded-xl border border-border bg-card p-4"><h3 className="text-[11px] font-semibold uppercase tracking-widest text-muted">Auto-approve</h3><p className="mt-0.5 text-xs text-muted">Rules that request titles on their own, up to the daily caps in Settings.</p>...` keeping the rest unchanged. It is not mounted until Task 5.

`AdminLayout.test.tsx` and any other test that rendered the old Requests tab: run the suite and adjust only what the replacement breaks (the tab count stays eleven).

- [ ] **Step 6: Run, build, commit**

`npx tsc --noEmit && npx vitest run && npm run build`.

```bash
git add frontend/src static/app
git commit -m "feat(ui): Requests tab with views, filters, sortable table and paging

Claude-Session: https://claude.ai/code/session_017Cc8iouqJoYhUcnJhhgapA"
```

---

### Task 4: Row actions with inline deny, reopen, drawer wiring, Forget button

**Files:**
- Modify: `frontend/src/api.ts` (`reopenRequest`), `frontend/src/pages/admin/Requests.tsx` (mount `RowActions`, the drawer), `frontend/src/pages/admin/library/actions.ts` (`forget`), `frontend/src/pages/admin/library/TitleDrawer.tsx` (Forget button)
- Create: `frontend/src/pages/admin/requests/RowActions.tsx`
- Test: `frontend/src/pages/admin/requests/RowActions.test.tsx` (new), `frontend/src/pages/admin/library/TitleDrawer.test.tsx` (append), `Requests.test.tsx` (append one drawer case)

**Interfaces:**
- `api.reopenRequest(id) -> {ok, message}`.
- `RowActions({ row, overQuota, onDone })`: pending shows Approve and Deny; Deny swaps to an input with Confirm and Cancel; denied shows Reopen and Approve; approved renders nothing. `overQuota` shows an amber "over quota" hint next to Approve. Every action shows `{ok, message}` inline (reuse `ActionButton` from `library/cards/DrawerCard.tsx`) and calls `onDone` on success.
- `ACTIONS.forget(d)` calls `api.deleteRequest(d.request.id)`; `TitleDrawer` renders "Forget request" next to Purge with confirm text "Forget the request for \"<title>\" but keep its files? It disappears from the Library table; the files stay in Jellyfin." and reports through `onPurged`.

- [ ] **Step 1: Failing `RowActions.test.tsx`**

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { RowActions } from './RowActions';
import { row } from './fixtures';

const apiMocks = vi.hoisted(() => ({ approveRequest: vi.fn(), denyRequest: vi.fn(), reopenRequest: vi.fn() }));
vi.mock('../../../api', async () => {
  const actual = await vi.importActual<typeof import('../../../api')>('../../../api');
  return { ...actual, api: { ...actual.api, ...apiMocks } };
});

describe('RowActions', () => {
  beforeEach(() => vi.clearAllMocks());

  it('pending: approve posts and reports; deny is inline with a note and can be cancelled', async () => {
    apiMocks.approveRequest.mockResolvedValue({ ok: true });
    apiMocks.denyRequest.mockResolvedValue({ ok: true });
    const onDone = vi.fn();
    render(<RowActions row={row({})} overQuota={false} onDone={onDone} />);
    await userEvent.click(screen.getByRole('button', { name: 'Deny' }));
    expect(screen.getByRole('textbox', { name: 'Reason' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('textbox')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Deny' }));
    await userEvent.type(screen.getByRole('textbox', { name: 'Reason' }), 'too big');
    await userEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() => expect(apiMocks.denyRequest).toHaveBeenCalledWith(1, 'too big'));
    expect(onDone).toHaveBeenCalled();
    await userEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(apiMocks.approveRequest).toHaveBeenCalledWith(1));
    expect(await screen.findByText('approved')).toBeInTheDocument();
  });

  it('denied: reopen and approve; approved: nothing; over quota shows the hint', async () => {
    apiMocks.reopenRequest.mockResolvedValue({ ok: true, message: 'back in the pending list' });
    const { rerender } = render(<RowActions row={row({ status: 'denied' })} overQuota onDone={() => {}} />);
    expect(screen.getByText('over quota')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Reopen' }));
    await waitFor(() => expect(apiMocks.reopenRequest).toHaveBeenCalledWith(1));
    expect(await screen.findByText('back in the pending list')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument();
    rerender(<RowActions row={row({ status: 'approved' })} overQuota={false} onDone={() => {}} />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Implement**

`api.ts`: `reopenRequest: (id: number) => http<{ ok: boolean; message: string }>(\`/ui/api/user-requests/${id}/reopen\`, { method: 'POST' }),`

`RowActions.tsx`:

```tsx
import { useState } from 'react';
import { api } from '../../../api';
import type { AdminRequestRow } from '../../../api';
import { Button } from '../../../components/primitives';
import { ActionButton } from '../library/cards/DrawerCard';

export function RowActions({ row, overQuota, onDone }: { row: AdminRequestRow; overQuota: boolean; onDone: () => void }) {
  const [denying, setDenying] = useState(false);
  const [note, setNote] = useState('');
  if (row.status === 'approved') return null;
  const approve = () => api.approveRequest(row.id).then((r) => ({ ok: r.ok, message: r.ok ? 'approved' : 'approve failed' }));
  const deny = () => api.denyRequest(row.id, note.trim() || undefined).then((r) => ({ ok: r.ok, message: r.ok ? 'denied' : 'deny failed' }));
  if (denying) {
    return (
      <span className="inline-flex items-center gap-1">
        <input aria-label="Reason" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Reason (optional)"
          className="w-40 rounded border border-border bg-bg px-2 py-1 text-xs" />
        <ActionButton label="Confirm" variant="primary" run={deny} onDone={() => { setDenying(false); setNote(''); onDone(); }} />
        <Button variant="ghost" onClick={() => { setDenying(false); setNote(''); }}>Cancel</Button>
      </span>
    );
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-1">
      {row.status === 'denied' && (
        <ActionButton label="Reopen" run={() => api.reopenRequest(row.id)} onDone={onDone} />
      )}
      <ActionButton label="Approve" variant="primary" run={approve} onDone={onDone} />
      {overQuota && <span className="text-[10px] text-warn" title="This user is at the monthly quota; approving still works">over quota</span>}
      {row.status === 'pending' && <Button onClick={() => setDenying(true)}>Deny</Button>}
    </span>
  );
}
```

`Requests.tsx`: fetch quotas (`useQuery({ queryKey: ['admin-quotas'], queryFn: api.adminQuotas })`, the `api.adminQuotas` helper and `QuotaRow` type come in Task 5; add them now as `adminQuotas: () => http<{ rows: QuotaRow[] }>('/ui/api/admin/quotas')` with the `QuotaRow` interface from Task 5's Interfaces block), build `overQuotaUsers = new Set(rows where !unlimited && used >= limit)`, and pass `renderActions={(r) => <RowActions row={r} overQuota={overQuotaUsers.has(r.user_id)} onDone={refetchAll} />}` where `refetchAll` refetches `page`, `counts` and quotas. Mount the drawer: `{state.open && <TitleDrawer key={state.open} imdb={state.open} onClose={closeDrawer} onChanged={refetchAll} />}` with `closeDrawer = useCallback(() => update({ open: null }), [update])`.

`library/actions.ts`: `forget: async (d: LibraryDetail): Promise<Result> => { await api.deleteRequest(d.request.id); return { ok: true, message: 'request forgotten, files kept' }; },`

`TitleDrawer.tsx`: after the Purge `ActionButton`: `<ActionButton label="Forget request" run={() => ACTIONS.forget(d)} onDone={() => { onPurged?.(d.request.imdb_id); onChanged(); onClose(); }} confirm={\`Forget the request for "${d.request.title}" but keep its files? It disappears from the Library table; the files stay in Jellyfin.\`} />`.

Append to `TitleDrawer.test.tsx` a case: with `window.confirm` mocked true and `deleteRequest` mocked (add it to the hoisted mocks) resolving `{ok: true}`, clicking "Forget request" calls `deleteRequest(1)` and `onPurged('tt1')`.

Append to `Requests.test.tsx`: clicking the title "Heat" opens the drawer (mock `libraryDetail` to resolve a minimal detail with `request.title: 'Heat'`, reuse the `detail()` shape from `TitleDrawer.test.tsx`) and the hash contains `open=tt1`.

- [ ] **Step 3: Run, build, commit**

```bash
git add frontend/src static/app
git commit -m "feat(ui): request row actions with inline deny and reopen, drawer from the Requests tab, forget button

Claude-Session: https://claude.ai/code/session_017Cc8iouqJoYhUcnJhhgapA"
```

---

### Task 5: Quotas card, auto-approve card, quota message in the detail modal

**Files:**
- Create: `frontend/src/pages/admin/requests/QuotasCard.tsx`, `QuotasCard.test.tsx`
- Modify: `frontend/src/pages/admin/Requests.tsx` (mount both cards below the paging strip), `frontend/src/components/DetailModal/index.tsx` (`onError`), `frontend/src/components/DetailModal/DetailModal.test.tsx` (one case)

**Interfaces:**
- `QuotaRow { user_id, username, used, limit, remaining: number | null, unlimited, resets_at, auto_approve, paused }` (declared in Task 4 already if the implementer followed it; otherwise declare here).
- `QuotasCard({ rows })`.

- [ ] **Step 1: Failing `QuotasCard.test.tsx`**

```tsx
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import { QuotasCard } from './QuotasCard';

describe('QuotasCard', () => {
  it('lists users with used, cap, remaining and reset date, marking the ones at the cap', () => {
    render(<MemoryRouter initialEntries={['/admin']}><QuotasCard rows={[
      { user_id: 3, username: 'adam', used: 3, limit: 2, remaining: 0, unlimited: false, resets_at: '2026-10-01T00:00:00Z', auto_approve: true, paused: true },
      { user_id: 4, username: 'bea', used: 5, limit: 0, remaining: null, unlimited: true, resets_at: '2026-10-01T00:00:00Z', auto_approve: false, paused: false },
      { user_id: 5, username: 'carl', used: 1, limit: 10, remaining: 9, unlimited: false, resets_at: '2026-10-01T00:00:00Z', auto_approve: false, paused: false },
    ]} /></MemoryRouter>);
    const adam = screen.getByText('adam').closest('li')!;
    expect(within(adam).getByText('3 of 2')).toHaveClass('text-danger');
    expect(within(adam).getByText('auto-approve paused')).toBeInTheDocument();
    expect(within(screen.getByText('bea').closest('li')!).getByText('unlimited')).toBeInTheDocument();
    expect(within(screen.getByText('carl').closest('li')!).getByText('9 left')).toBeInTheDocument();
    expect(screen.getAllByText(/resets 2026-10-01/)).toHaveLength(2);
    expect(screen.getByRole('link', { name: 'Edit quotas in Users' })).toHaveAttribute('href', '/admin#users');
  });
  it('says so when no user has a cap', () => {
    render(<MemoryRouter initialEntries={['/admin']}><QuotasCard rows={[]} /></MemoryRouter>);
    expect(screen.getByText('No users to show.')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: `QuotasCard.tsx`**

```tsx
import { Link } from 'react-router-dom';
import type { QuotaRow } from '../../../api';

export function QuotasCard({ rows }: { rows: QuotaRow[] }) {
  return (
    <section className="rounded-xl border border-border bg-card p-4">
      <h3 className="text-[11px] font-semibold uppercase tracking-widest text-muted">Quotas</h3>
      <p className="mt-0.5 text-xs text-muted">Requests this month against each user's monthly cap.</p>
      {rows.length === 0 ? <p className="mt-3 text-sm text-muted">No users to show.</p> : (
        <ul className="mt-3 space-y-1 text-sm">
          {rows.map((r) => {
            const atCap = !r.unlimited && r.used >= r.limit;
            return (
              <li key={r.user_id} className="flex flex-wrap items-center gap-2">
                <span className="w-32 font-medium">{r.username}</span>
                {r.unlimited
                  ? <span className="text-muted">unlimited</span>
                  : <span className={atCap ? 'text-danger' : ''}>{r.used} of {r.limit}</span>}
                {!r.unlimited && !atCap && <span className="text-xs text-muted">{r.remaining} left</span>}
                {!r.unlimited && <span className="text-xs text-muted">resets {r.resets_at.slice(0, 10)}</span>}
                {r.paused && <span className="rounded bg-warn/20 px-1.5 py-0.5 text-[10px] font-semibold text-warn">auto-approve paused</span>}
              </li>
            );
          })}
        </ul>
      )}
      <Link to={{ hash: 'users' }} className="mt-3 inline-block text-xs text-accent-light hover:underline">Edit quotas in Users</Link>
    </section>
  );
}
```

The hash-only `Link` form is the existing pattern (Overview and Blacklist use it); render the test inside `<MemoryRouter initialEntries={['/admin']}>` so the href resolves to `/admin#users`.

- [ ] **Step 3: Mount both cards in `Requests.tsx`**

Below the paging strip inside `<main>`: `<QuotasCard rows={quotas.data?.rows || []} />` and `<AutoApproveCard />`. Add to `Requests.test.tsx` one case: with `adminQuotas` resolving one at-cap row, the card shows "auto-approve paused" and the "Auto-approve" heading renders with "Run now".

- [ ] **Step 4: Quota message in the detail modal**

In `frontend/src/components/DetailModal/index.tsx` the add mutation's `onError` currently toasts `Request failed` with `err.message`. Change to:

```tsx
    onError: (err: Error) => {
      const m = /^409: quota reached/.test(err.message);
      toast(m ? 'Monthly quota reached' : 'Request failed',
            m ? 'You have used this month’s requests. Ask an admin, or try again after the reset.' : err.message, 'err');
    },
```

Look at the two lines above `onError` (135 to 137) for the exact `toast` signature and keep it. Add one case to `DetailModal.test.tsx`: when `addToLibrary` rejects with `new Error('409: quota reached')`, the toast title "Monthly quota reached" appears (follow the file's existing toast mocking pattern).

- [ ] **Step 5: Run, build, commit**

```bash
git add frontend/src static/app
git commit -m "feat(ui): quotas card and auto-approve card on the Requests tab, quota message on request

Claude-Session: https://claude.ai/code/session_017Cc8iouqJoYhUcnJhhgapA"
```

---

### Task 6: Docs, changelog, cleanup check

**Files:**
- Modify: `README.md` (admin row, line 72), `CHANGELOG.md` (`## [Unreleased]`), `frontend/src/pages/admin/Requests.tsx` (remove the Library link line if it survived; the tab no longer needs it)
- Test: `tests/test_requests_admin.py` (append a source-text guard)

- [ ] **Step 1: Guard test** (append)

```python
def test_the_old_requests_panels_are_gone():
    src = _src("frontend/src/pages/admin/Requests.tsx")
    assert "PendingApprovalsPanel" not in src and "AllRequestsPanel" not in src
    assert "RowActions" in src and "QuotasCard" in src and "AutoApproveCard" in src
```

- [ ] **Step 2: Docs**

`README.md` line 72: replace "Requests (approvals and auto-approve rules)" with "Requests (every user request with approve, inline deny and reopen; per-user quotas; auto-approve rules)".

`CHANGELOG.md` under `## [Unreleased]`:

```markdown
### Added

- Admin Requests tab rebuilt on the Library kit: views Pending, Approved,
  Denied and All with counts; filters by user, type and date; sortable
  columns; server-side paging; Approve, inline Deny with a reason, and
  Reopen for a denied request; a Quotas card with each user's requests
  this month against their cap; the auto-approve rules moved under the
  table. Clicking a title opens the same drawer as the Library tab.
- Monthly request quotas are enforced: a user at the cap is refused with a
  clear message, and an auto-approve user at the cap has new requests
  wait for review until the month resets. Admins are never limited.
- The title drawer gains "Forget request", which drops the request but
  keeps the files.

### Removed

- `GET /ui/api/requests/all`, unused since the Library tab.
```

- [ ] **Step 3: Both suites, build, commit**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/ -q -p no:cacheprovider
cd frontend && npx tsc --noEmit && npx vitest run && npm run build && cd ..
git add -A
git commit -m "docs(admin): Requests tab and enforced quotas in README and changelog

Claude-Session: https://claude.ai/code/session_017Cc8iouqJoYhUcnJhhgapA"
```

---

## Self-review notes

- Spec coverage: section 1 (list endpoint, views, index, quotas endpoint, enforcement, reopen, orphan removal) in Tasks 1 and 2; section 2 (rail, table, row actions, drawer, two cards, empty states) in Tasks 3 to 5; section 3 (tab replacement, quota message, docs) in Tasks 3, 5 and 6; section 4's tests are spread across each task's test files.
- Clarification against the spec: the request control is the detail modal's add button, so the quota message is a toast there rather than "under the request control on the Requests page"; the user page's existing quota card already shows the numbers.
- Type consistency: the row shape in Task 1 matches `AdminRequestRow` in Task 3; `QuotaRow` fields match `quota_rows()` in Task 2; `reopenRequest` returns `{ok, message}` as the route does; `RowActions` props are the same in Tasks 4 and 5's mount.
