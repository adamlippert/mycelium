# TorBox Account Pool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Several TorBox API keys used as equal peers: new torrents go to the least loaded healthy account, every play uses the account that holds the torrent, and a broken or disabled account hands its titles over on their next play.

**Architecture:** A new `torbox_pool.py` owns the accounts (table `torbox_accounts`, account 1 mirrors `TORBOX_API_KEY`), picks a home for a new add, and tracks per-account health. `torbox.py` keeps its functions but every account-bound one takes `account_id` first and keeps its state per account. `virtual_items.torbox_account` records the home next to `torbox_id`; the play path, the jobs and the admin surfaces read it.

**Tech Stack:** Python 3.12, Flask, SQLite (WAL), APScheduler; React 18 + TypeScript + Vite + Tailwind (`frontend/`, built into `static/app/`); pytest, vitest.

**Spec:** `docs/superpowers/specs/2026-09-13-torbox-account-pool-design.md`

## Global Constraints

- Never write two hyphens in a row anywhere (code, comments, docs, commit messages). Markdown table separators, horizontal rules and real CLI flags such as the TypeScript no-emit flag are the exceptions.
- The repo is public: no keys, tokens or IP addresses in commits or tests (use `"k1"`, `"k2"`).
- Work on branch `main`. No `Co-Authored-By`. Commit trailer on every commit: `Claude-Session: https://claude.ai/code/session_01E4NjBiGw4m7EjGexJTbQu5`.
- Tests never import `app.py`; routes are asserted on source text via a `_src()` helper. Every test file that touches the database carries its own `_isolated_db` autouse fixture (drop the thread-local connection, monkeypatch `db.DB_PATH`, `db.init()`); there is no `tests/conftest.py`. No test reaches the network: fake `requests.get`/`requests.post` or the module seam.
- Run Python tests with `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/ -q -p no:cacheprovider`. After a new test, mutation-check it (break the implementation, the test must fail, restore by copying the file back, never `git checkout`).
- Frontend: `cd frontend && npx tsc --noEmit && npx vitest run`, then `npm run build`; commit `static/app/` with any frontend change.
- Some test modules replace `sys.modules["torbox"]` with a MagicMock at collection time; a test that needs the real client imports it the way `tests/test_torbox_ratelimit.py` does (pop, import, restore).
- Account 1 is the one whose key is `settings.get("TORBOX_API_KEY")`. A single-key install must behave exactly as before this plan.

---

## File Structure

| File | Responsibility |
|---|---|
| `db.py` | `torbox_accounts` DDL, migrations (`virtual_items.torbox_account`, `createtorrent_log.account`, seed account 1, mark existing items), account CRUD helpers, `set_virtual_torbox`, `count_items_by_account`, per-account budget queries |
| `torbox_pool.py` (new) | `Account`, `accounts()`, `account()`, `any_key()`, `choose_for_add()`, `mark_429()`, `mark_auth_failure()`, `health()`, `invalidate()` |
| `torbox.py` | Account-aware client: `_headers(account_id)`, per-account mylist cache and 429 time, `request_download_link`, every account-bound function takes `account_id` first |
| `settings.py` | `set("TORBOX_API_KEY", ...)` mirrors into account 1; the "TorBox accounts" custom card in the debrid section |
| `catbox.py` | Homing in `_materialize_locked`, re-home rules, `release_idle` and `reconcile_torbox_ids` per account |
| `strm_generator.py`, `cleanup.py`, `processor.py`, `monitor.py`, `upgrader.py`, `retry_queue.py`, `catchup.py`, `plugins/webplayer/web_player.py`, `shell_summary.py` | Callers pass an account (the item's home, or one chosen per operation) |
| `health.py` | One "TorBox <label>" ping row per enabled account; budget row per account |
| `metrics_prom.py` | `account` label on the TorBox gauges, new `mycelium_torbox_createtorrent_used{account}` |
| `overview.py` | `torbox.accounts` in the payload; the adds cell sums accounts and names the one over 45 |
| `library_admin.py` | `torbox_account` and its label on drawer items |
| `app.py` | `/ui/api/torbox-accounts` endpoints; `/ui/api/torbox-usage`, `/ui/api/torbox-list`, `/ui/torbox-delete`, manual add use accounts |
| `frontend/src/api.ts` | Types and client calls for accounts and the overview additions |
| `frontend/src/pages/admin/settings/customCards.tsx` | `TorboxAccounts` card |
| `frontend/src/pages/admin/overview/TorboxCard.tsx`, `StatusStrip.tsx` | Per-account columns; amber rule per account |
| `frontend/src/pages/admin/library/cards/ReleaseCard.tsx` | Home label next to the TorBox id |
| `docs/INTEGRATIONS.md`, `README.md`, `docs/SCALING.md`, `CHANGELOG.md` | Documentation |

---

### Task 1: Accounts table, migrations and the pool

**Files:**
- Modify: `db.py` (DDL after `createtorrent_log`, `_migrate()` after the `wanted_episodes.excluded_hashes` block, helpers after `update_virtual_torbox_id`)
- Modify: `settings.py:691` (`set`)
- Create: `torbox_pool.py`
- Test: `tests/test_torbox_pool.py`

**Interfaces:**
- Produces (db): `list_torbox_accounts() -> list[dict]` (id, label, api_key, enabled, created_at; all rows, ordered by id), `get_torbox_account(account_id) -> dict | None`, `insert_torbox_account(label, api_key) -> int`, `update_torbox_account(account_id, *, label=None, api_key=None, enabled=None) -> None`, `delete_torbox_account(account_id) -> None`, `count_items_by_account() -> dict[int, int]` (items with a non-null `torbox_account`), `set_virtual_torbox(token, torbox_id: int | None, account_id: int | None) -> None` (writes both columns), `get_createtorrent_log(since_ts, account_id=None) -> list[tuple[float, str, bool, int]]` (ts, reason, cached, account), `reserve_createtorrent_slot(now, reason, hour_limit, min_limit, cached=False, account_id=1)` (hour and minute counts per account), `get_virtual_items_with_torbox_id()` rows now include `torbox_account`.
- Produces (pool): `Account` dataclass `(id: int, label: str, api_key: str, enabled: bool)`; `accounts(enabled_only=True) -> list[Account]`; `account(account_id) -> Account | None`; `any_key() -> str` (lowest enabled id's key, `""` when none); `choose_for_add() -> Account`; `mark_429(account_id)`; `mark_auth_failure(account_id)`; `health(account_id) -> dict` (`rate_limited_until: float | None`, `auth_failed_at: float | None`, `budget_left: int`, `torrents: int`); `invalidate()`; constants `EXCLUDE_WINDOW_SEC = 600`, `MIN_BUDGET_LEFT = 2`.
- Produces (settings): `settings.set("TORBOX_API_KEY", v)` also updates account 1's `api_key` column when the row exists.

- [ ] **Step 1: Write the failing tests**

`tests/test_torbox_pool.py`:

```python
"""Accounts table, migrations and torbox_pool: account 1 mirrors
TORBOX_API_KEY, extra accounts live in the table, choose_for_add picks the
least loaded healthy account and never fails outright."""
import os
import sqlite3
import time

import pytest

import db
import settings
import torbox_pool as pool


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
    pool.invalidate()
    pool._health.clear()
    yield
    _drop_cached_conn()


def _item(token, account_id, torbox_id=5):
    with db._connect() as conn:
        conn.execute("INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, torbox_id, torbox_account) "
                     "VALUES (?, 'h', 'm', ?, 'movie', ?, ?)", (token, token, torbox_id, account_id))
        conn.commit()


# migration and table

def test_init_seeds_account_1_from_the_configured_key_once():
    rows = db.list_torbox_accounts()
    assert [(r["id"], r["label"], r["api_key"], r["enabled"]) for r in rows] == [(1, "main", "k1", 1)]
    db.init()
    assert len(db.list_torbox_accounts()) == 1, "idempotent"


def test_migration_marks_homed_items_and_budget_rows_as_account_1(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE virtual_items (token TEXT PRIMARY KEY, info_hash TEXT, magnet TEXT, title TEXT,
            media_type TEXT, torbox_id INTEGER);
        INSERT INTO virtual_items VALUES ('a', 'h', 'm', 'A', 'movie', 7);
        INSERT INTO virtual_items VALUES ('b', 'h', 'm', 'B', 'movie', NULL);
        CREATE TABLE createtorrent_log (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL,
            reason TEXT NOT NULL DEFAULT '', cached INTEGER NOT NULL DEFAULT 0);
        INSERT INTO createtorrent_log (ts, reason) VALUES (1.0, 'x');
    """)
    conn.commit(); conn.close()
    _drop_cached_conn()
    monkeypatch.setattr(db, "DB_PATH", str(path))
    db.init()
    assert db.get_virtual_item("a")["torbox_account"] == 1
    assert db.get_virtual_item("b")["torbox_account"] is None
    assert db.get_createtorrent_log(0.0) == [(1.0, "x", False, 1)]


def test_account_crud_and_key_mirroring():
    two = db.insert_torbox_account("second", "k2")
    assert two == 2
    db.update_torbox_account(2, enabled=False)
    assert db.get_torbox_account(2)["enabled"] == 0
    db.update_torbox_account(2, label="backup", api_key="k2b", enabled=True)
    assert db.get_torbox_account(2)["label"] == "backup" and db.get_torbox_account(2)["api_key"] == "k2b"
    settings.set("TORBOX_API_KEY", "k1-new")
    assert db.get_torbox_account(1)["api_key"] == "k1-new"
    db.delete_torbox_account(2)
    assert db.get_torbox_account(2) is None
    with pytest.raises(sqlite3.IntegrityError):
        db.insert_torbox_account("main", "dup")


def test_set_virtual_torbox_writes_and_clears_both_columns():
    _item("t", None, torbox_id=None)
    db.set_virtual_torbox("t", 9, 2)
    it = db.get_virtual_item("t")
    assert (it["torbox_id"], it["torbox_account"]) == (9, 2)
    db.set_virtual_torbox("t", None, None)
    it = db.get_virtual_item("t")
    assert (it["torbox_id"], it["torbox_account"]) == (None, None)
    db.set_virtual_torbox("t", 9, 2)
    db.update_virtual_item_upgrade("t", "h2", "m2", None, None)
    it = db.get_virtual_item("t")
    assert (it["torbox_id"], it["torbox_account"]) == (None, None), "an upgrade clears the home too"


def test_budget_is_counted_per_account():
    now = time.time()
    for _ in range(3):
        db.reserve_createtorrent_slot(now, "x", 60, 10, account_id=1)
    db.reserve_createtorrent_slot(now, "x", 60, 10, account_id=2)
    assert db.reserve_createtorrent_slot(now, "x", 60, 10, account_id=2)["hour_count"] == 2
    assert len(db.get_createtorrent_log(now - 1, account_id=1)) == 3
    assert len(db.get_createtorrent_log(now - 1)) == 5
    assert db.count_items_by_account() == {}
    _item("a", 1); _item("b", 1); _item("c", 2)
    assert db.count_items_by_account() == {1: 2, 2: 1}


# pool

def test_accounts_reads_the_table_with_account_1_from_settings(monkeypatch):
    db.insert_torbox_account("second", "k2")
    db.insert_torbox_account("off", "k3")
    db.update_torbox_account(3, enabled=False)
    settings.set("TORBOX_API_KEY", "k1-live")
    pool.invalidate()
    assert [(a.id, a.label, a.api_key, a.enabled) for a in pool.accounts()] == [(1, "main", "k1-live", True), (2, "second", "k2", True)]
    assert [a.id for a in pool.accounts(enabled_only=False)] == [1, 2, 3]
    assert pool.account(3).enabled is False and pool.account(9) is None
    assert pool.any_key() == "k1-live"


def test_accounts_cache_is_sixty_seconds_and_invalidate_drops_it(monkeypatch):
    pool.accounts()
    db.insert_torbox_account("second", "k2")
    assert [a.id for a in pool.accounts()] == [1], "cached"
    pool.invalidate()
    assert [a.id for a in pool.accounts()] == [1, 2]
    db.insert_torbox_account("third", "k3")
    monkeypatch.setattr(pool.time, "monotonic", lambda: time.monotonic() + 61)
    assert [a.id for a in pool.accounts()] == [1, 2, 3]


def test_choose_for_add_picks_fewest_torrents_then_budget_then_lowest_id(monkeypatch):
    db.insert_torbox_account("second", "k2")
    db.insert_torbox_account("third", "k3")
    pool.invalidate()
    _item("a", 1); _item("b", 1); _item("c", 2)
    assert pool.choose_for_add().id == 3, "holds nothing"
    _item("d", 3); _item("e", 3)
    assert pool.choose_for_add().id == 2, "one item beats two"
    now = time.time()
    for _ in range(5):
        db.reserve_createtorrent_slot(now, "x", 60, 10, account_id=2)
    _item("f", 2)
    # 2 and 3 tie on two items each; 3 has more budget left
    assert pool.choose_for_add().id == 3
    _item("g", 3)
    # 2 (two items, budget 55) vs 3 (three items): fewest torrents wins first
    assert pool.choose_for_add().id == 2


def test_choose_for_add_excludes_limited_failed_and_exhausted_accounts_then_falls_back(monkeypatch):
    db.insert_torbox_account("second", "k2")
    pool.invalidate()
    _item("a", 1)
    pool.mark_429(2)
    assert pool.choose_for_add().id == 1, "2 answered 429 within the window"
    monkeypatch.setattr(pool.time, "time", lambda: time.time() + pool.EXCLUDE_WINDOW_SEC + 1)
    assert pool.choose_for_add().id == 2, "window over"
    pool.mark_auth_failure(2)
    assert pool.choose_for_add().id == 1
    monkeypatch.undo()
    pool._health.clear()
    now = time.time()
    for _ in range(59):
        db.reserve_createtorrent_slot(now, "x", 60, 10, account_id=2)
    assert pool.choose_for_add().id == 1, "2 has fewer than two uncached adds left"
    pool.mark_429(1)
    chosen = pool.choose_for_add()
    assert chosen.id in (1, 2), "every account excluded: still returns one"
    db.update_torbox_account(1, enabled=False)
    pool.invalidate()
    assert pool.choose_for_add().id == 2, "disabled accounts never chosen"


def test_health_reports_marks_budget_and_torrents():
    _item("a", 1)
    h = pool.health(1)
    assert h["torrents"] == 1 and h["budget_left"] == 60 and h["rate_limited_until"] is None and h["auth_failed_at"] is None
    pool.mark_429(1)
    assert pool.health(1)["rate_limited_until"] > time.time()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/test_torbox_pool.py -q -p no:cacheprovider`
Expected: errors, `ModuleNotFoundError: No module named 'torbox_pool'`.

- [ ] **Step 3: DDL and migrations in `db.py`**

After the `idx_createtorrent_ts` index in `_DDL`, add:

```sql
CREATE TABLE IF NOT EXISTS torbox_accounts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    label       TEXT    NOT NULL UNIQUE,
    api_key     TEXT    NOT NULL,
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%d %H:%M:%S','now'))
);
```

In `_migrate()`, add `("torbox_account", "INTEGER")` to the `virtual_items` column list (the one that contains `("rd_id", "TEXT")`). After the `wanted_episodes.excluded_hashes` block:

```python
        ct_cols = {r["name"] for r in conn.execute("PRAGMA table_info(createtorrent_log)")}
        if "account" not in ct_cols:
            conn.execute("ALTER TABLE createtorrent_log ADD COLUMN account INTEGER NOT NULL DEFAULT 1")
            log.info("Migration: added createtorrent_log.account")

        # Account pool: account 1 is the configured TORBOX_API_KEY. Seed it
        # once, and mark every item that already sits on TorBox as homed
        # there, so a single-key install keeps behaving as before.
        n_accounts = conn.execute("SELECT COUNT(*) AS n FROM torbox_accounts").fetchone()["n"]
        if n_accounts == 0:
            row = conn.execute("SELECT value FROM settings WHERE key='TORBOX_API_KEY'").fetchone()
            key = (row["value"] if row else None) or os.environ.get("TORBOX_API_KEY") or ""
            if key:
                conn.execute("INSERT INTO torbox_accounts (id, label, api_key) VALUES (1, 'main', ?)", (key,))
                log.info("Migration: seeded torbox_accounts with account 1 (main)")
        conn.execute("UPDATE virtual_items SET torbox_account=1 WHERE torbox_id IS NOT NULL AND torbox_account IS NULL")
        conn.commit()
```

(`db.py` does not import `os` yet: add `import os` to its imports. The settings table is `settings(key, value, updated_at)`.)

- [ ] **Step 4: Helpers in `db.py`**

Replace `update_virtual_torbox_id` with `set_virtual_torbox` and keep the old name as a thin wrapper for one release (callers move in Task 2 and 3; the wrapper keeps the account untouched):

```python
def set_virtual_torbox(token: str, torbox_id: int | None, account_id: int | None) -> None:
    """The TorBox torrent id and the account that holds it are written and
    cleared together; one without the other is meaningless."""
    with _connect() as conn:
        conn.execute("UPDATE virtual_items SET torbox_id=?, torbox_account=? WHERE token=?",
                     (torbox_id, account_id, token))
        conn.commit()


def update_virtual_torbox_id(token: str, torbox_id: int | None) -> None:
    """Kept for callers not yet account-aware; clearing also clears the home."""
    if torbox_id is None:
        set_virtual_torbox(token, None, None)
        return
    with _connect() as conn:
        conn.execute("UPDATE virtual_items SET torbox_id=? WHERE token=?", (torbox_id, token))
        conn.commit()


def count_items_by_account() -> dict[int, int]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT torbox_account AS a, COUNT(*) AS n FROM virtual_items "
            "WHERE torbox_account IS NOT NULL GROUP BY torbox_account").fetchall()
    return {int(r["a"]): int(r["n"]) for r in rows}


def list_torbox_accounts() -> list[dict]:
    with _connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM torbox_accounts ORDER BY id").fetchall()]


def get_torbox_account(account_id: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM torbox_accounts WHERE id=?", (account_id,)).fetchone()
        return dict(row) if row else None


def insert_torbox_account(label: str, api_key: str) -> int:
    with _connect() as conn:
        cur = conn.execute("INSERT INTO torbox_accounts (label, api_key) VALUES (?, ?)", (label.strip(), api_key.strip()))
        conn.commit()
        return int(cur.lastrowid)


def update_torbox_account(account_id: int, *, label: str | None = None, api_key: str | None = None,
                          enabled: bool | None = None) -> None:
    sets, args = [], []
    if label is not None:
        sets.append("label=?"); args.append(label.strip())
    if api_key is not None:
        sets.append("api_key=?"); args.append(api_key.strip())
    if enabled is not None:
        sets.append("enabled=?"); args.append(1 if enabled else 0)
    if not sets:
        return
    args.append(account_id)
    with _connect() as conn:
        conn.execute(f"UPDATE torbox_accounts SET {', '.join(sets)} WHERE id=?", args)
        conn.commit()


def delete_torbox_account(account_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM torbox_accounts WHERE id=?", (account_id,))
        conn.commit()
```

In `update_virtual_item_upgrade`, change `torbox_id=NULL, file_id=NULL` to `torbox_id=NULL, torbox_account=NULL, file_id=NULL`.

`get_virtual_items_with_torbox_id`: select `token, torbox_id, torbox_account, info_hash, title`.

`reserve_createtorrent_slot(now, reason, hour_limit, min_limit, cached=False, account_id=1)`: both `COUNT(*)` queries gain `AND account = ?` with `account_id`; the INSERT becomes `INSERT INTO createtorrent_log (ts, reason, cached, account) VALUES (?, ?, ?, ?)`.

`get_createtorrent_log(since_ts, account_id=None)`: select `ts, reason, cached, account`; add `AND account = ?` when `account_id` is given; return `(ts, reason, bool(cached), int(account))` tuples.

- [ ] **Step 5: Mirror the key into account 1 in `settings.set`**

At the top of `settings.set`, after the `None`/empty branch:

```python
    if key == "TORBOX_API_KEY":
        # Account 1 of the TorBox pool is this key; keep its row in step so
        # the pool and the setting never disagree.
        try:
            if db.get_torbox_account(1):
                db.update_torbox_account(1, api_key=str(value))
        except Exception as exc:
            log.debug("settings.set: could not mirror TORBOX_API_KEY into account 1: %s", exc)
```

- [ ] **Step 6: Create `torbox_pool.py`**

```python
"""The TorBox account pool: several API keys as equal peers.

Account 1 is the configured TORBOX_API_KEY (its row mirrors the setting);
extra accounts live only in `torbox_accounts`. `choose_for_add()` picks the
least loaded healthy account for a new torrent; every later play of that
title uses the account recorded on the item. Health (last 429, last auth
failure) is process state, forgotten on restart, like the single
`_last_429_at` before the pool.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

import db
import settings

log = logging.getLogger(__name__)

EXCLUDE_WINDOW_SEC = 600      # a 429 or an auth failure keeps an account out of new adds this long
MIN_BUDGET_LEFT = 2           # fewer uncached adds left than this: not a candidate
_CACHE_TTL_SEC = 60.0


@dataclass(frozen=True)
class Account:
    id: int
    label: str
    api_key: str
    enabled: bool


_lock = threading.Lock()
_cache: dict = {"accounts": None, "ts": None}
# account id -> {"rate_limited_at": float | None, "auth_failed_at": float | None}
_health: dict[int, dict] = {}


def invalidate() -> None:
    with _lock:
        _cache["accounts"] = None
        _cache["ts"] = None


def _load() -> list[Account]:
    rows = db.list_torbox_accounts()
    out = []
    for r in rows:
        key = r["api_key"]
        if r["id"] == 1:
            key = settings.get("TORBOX_API_KEY", "") or key
        out.append(Account(id=int(r["id"]), label=r["label"], api_key=key, enabled=bool(r["enabled"])))
    return out


def accounts(enabled_only: bool = True) -> list[Account]:
    with _lock:
        ts = _cache["ts"]
        if _cache["accounts"] is None or ts is None or time.monotonic() - ts > _CACHE_TTL_SEC:
            _cache["accounts"] = _load()
            _cache["ts"] = time.monotonic()
        all_accounts = list(_cache["accounts"])
    return [a for a in all_accounts if a.enabled] if enabled_only else all_accounts


def account(account_id: int) -> Account | None:
    for a in accounts(enabled_only=False):
        if a.id == account_id:
            return a
    return None


def any_key() -> str:
    """A key for calls that are not bound to an account (cache checks)."""
    enabled = accounts()
    return enabled[0].api_key if enabled else ""


def mark_429(account_id: int) -> None:
    _health.setdefault(account_id, {})["rate_limited_at"] = time.time()


def mark_auth_failure(account_id: int) -> None:
    _health.setdefault(account_id, {})["auth_failed_at"] = time.time()


def _budget_left(account_id: int) -> int:
    import torbox
    try:
        return max(0, 60 - torbox.createtorrent_usage(account_id)["count"])
    except Exception as exc:
        log.debug("budget for account %s unavailable: %s", account_id, exc)
        return 0


def health(account_id: int) -> dict:
    h = _health.get(account_id, {})
    limited = h.get("rate_limited_at")
    return {
        "rate_limited_until": (limited + EXCLUDE_WINDOW_SEC) if limited else None,
        "auth_failed_at": h.get("auth_failed_at"),
        "budget_left": _budget_left(account_id),
        "torrents": db.count_items_by_account().get(account_id, 0),
    }


def _excluded(a: Account, now: float) -> str | None:
    h = _health.get(a.id, {})
    if h.get("rate_limited_at") and now - h["rate_limited_at"] < EXCLUDE_WINDOW_SEC:
        return "rate limited"
    if h.get("auth_failed_at") and now - h["auth_failed_at"] < EXCLUDE_WINDOW_SEC:
        return "auth failure"
    if _budget_left(a.id) < MIN_BUDGET_LEFT:
        return "no budget"
    return None


def choose_for_add() -> Account:
    """The account a new torrent goes to. Candidates are the enabled
    accounts minus those rate limited or auth-failed in the last ten
    minutes and those with fewer than two uncached adds left; the winner
    holds the fewest torrents, ties by most budget left, then lowest id.
    With no candidate at all the account whose 429 is oldest is returned,
    so a burst degrades to a 429 and today's cooldown, never a hard fail."""
    enabled = accounts()
    if not enabled:
        raise RuntimeError("no enabled TorBox account")
    now = time.time()
    reasons = {a.id: _excluded(a, now) for a in enabled}
    candidates = [a for a in enabled if reasons[a.id] is None]
    if candidates:
        counts = db.count_items_by_account()
        chosen = min(candidates, key=lambda a: (counts.get(a.id, 0), -_budget_left(a.id), a.id))
        log.info("TorBox pool: %s for the next add (%d torrents, %d adds left)",
                 chosen.label, counts.get(chosen.id, 0), _budget_left(chosen.id))
        return chosen
    chosen = min(enabled, key=lambda a: (_health.get(a.id, {}).get("rate_limited_at") or 0.0, a.id))
    log.warning("TorBox pool: every account excluded (%s); falling back to %s",
                ", ".join(f"{a.label}: {reasons[a.id]}" for a in enabled), chosen.label)
    return chosen
```

`torbox.createtorrent_usage(account_id)` does not exist yet; until Task 2, add to `torbox.py` a temporary signature-compatible form: `def createtorrent_usage(account_id: int | None = None, window_sec: int = 3600)` that passes `account_id` to `_db.get_createtorrent_log(cutoff, account_id)` and unpacks four-tuples. Task 2 finishes the client.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/test_torbox_pool.py tests/test_torbox_ratelimit.py tests/test_torbox_reconcile.py tests/test_overview.py -q -p no:cacheprovider`
Expected: all pass. Then the full suite; fix any test that unpacked three-tuples from `get_createtorrent_log`.

- [ ] **Step 8: Mutation checks**

Break, run, restore (copy from the scratchpad, never `git checkout`): the `enabled_only` filter in `accounts()`; the `counts.get` key in `choose_for_add`; the `rate_limited_at` window; the `UPDATE virtual_items SET torbox_account=1` migration line.

- [ ] **Step 9: Commit**

```bash
git add db.py settings.py torbox_pool.py tests/test_torbox_pool.py
git commit -m "feat(torbox): accounts table, migrations and the account pool

Claude-Session: https://claude.ai/code/session_01E4NjBiGw4m7EjGexJTbQu5"
```

---

### Task 2: Account-aware TorBox client

**Files:**
- Modify: `torbox.py` (whole module)
- Modify: `strm_generator.py:201-217` (delete `_get_stream_url`, callers at 605, 1500, 1663), `cleanup.py:369`, `health.py:104-107`, `plugins/webplayer/web_player.py:278-296`
- Modify: every caller listed in the "Callers" table below, passing `torbox_pool.accounts()[0].id` (a placeholder Task 3 replaces with real homing) where no account is known yet
- Test: `tests/test_torbox_client_accounts.py`

**Interfaces:**
- Consumes: `torbox_pool.account(account_id)`, `torbox_pool.any_key()`, `torbox_pool.mark_429`, `torbox_pool.mark_auth_failure`, `db.reserve_createtorrent_slot(..., account_id=)`, `db.get_createtorrent_log(since, account_id)`.
- Produces: `_headers(account_id) -> dict`; `add_magnet(account_id, magnet, timeout=30, reason="unknown", cached=None) -> dict`; `list_torrents(account_id, timeout=30, force_refresh=False)`; `find_by_hash(account_id, info_hash, force_refresh=False)`; `find_by_id(account_id, torrent_id, timeout=15)`; `delete_torrent(account_id, torrent_id, timeout=15)`; `wait_until_ready(account_id, info_hash, timeout=None, torrent_id=None)`; `get_user_info(account_id, timeout=10)`; `get_usage_summary(account_id)`; `title_exists(account_id, title)`; `invalidate_mylist_cache(account_id=None)` (None clears every account); `createtorrent_usage(account_id=None, window_sec=3600)` (None sums every account); `last_429_at(account_id=None)` (None: latest across accounts); `request_download_link(account_id, torrent_id, file_id) -> str | None`; `check_cached`, `check_cached_files` unchanged signatures, header from `torbox_pool.any_key()`. `AuthFailed(Exception)` raised by account-bound calls on 401 or 403 after `mark_auth_failure`.

**Callers to update in this task** (grep `torbox\.` in each; pass the account named):

| File | Call | Account to pass |
|---|---|---|
| `catbox.py` | every `torbox.` call in `_materialize_locked`, `release_idle`, `reconcile_torbox_ids` | `_home(item)` helper: `item.get("torbox_account") or torbox_pool.accounts()[0].id` (Task 3 replaces) |
| `strm_generator.py` 605, 1500, 1663 | `_get_stream_url(torrent_id, file_id)` | `torbox.request_download_link(account_id, torrent_id, file_id)` with the item's `torbox_account` where an item is at hand, else `torbox_pool.accounts()[0].id` |
| `cleanup.py` 208, 209, 369, 844 | add, wait, link, list | one `acct = torbox_pool.choose_for_add().id` per repair; list per enabled account |
| `processor.py` 84, 93, 94, 794 | find, add, wait | `acct = torbox_pool.choose_for_add().id` at the top of the operation; 794: loop enabled accounts |
| `monitor.py` 175, 262, 267, 268, 315, 316 | usage, find, add, wait | usage: `createtorrent_usage()` (sum); adds: `choose_for_add()` once per operation |
| `upgrader.py` 154, 155, 224, 225, 266 | add, wait, usage | same |
| `retry_queue.py` 79, 91 | usage | sum |
| `catchup.py` 69 | list | union over enabled accounts |
| `app.py` 452, 1190, 1214, 1274, 2390, 2391, 3124 | quota, list, delete, manual add, usage, user, usage | quota per account (Task 4), list: union with an `account` field per row, delete: `request.form["account"]`, manual add: `choose_for_add()`, usage and user: account 1 for now (Task 6 makes it per account), 3124: sum |
| `overview.py` 76, 130 | usage, last 429 | sums for now (Task 6) |
| `shell_summary.py` 21 | usage | sum |
| `health.py` 85, 104 | usage, ping | sum; ping account 1 for now (Task 6) |
| `metrics_prom.py` 116 | usage summary | account 1 for now (Task 6) |
| `plugins/webplayer/web_player.py` 238, 244, 252, 255, 264, 331, 376 and `requestdl` at 280 | find, add, wait, link | one `choose_for_add()` per play; `find_by_hash` over enabled accounts for the library checks at 331 and 376 |

- [ ] **Step 1: Write the failing tests**

`tests/test_torbox_client_accounts.py`:

```python
"""torbox.py builds every header from the account it is given, keeps its
mylist cache and 429 marks per account, records the account on the budget
log, and never builds a header without an account."""
import os
import re
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
_prior_torbox = sys.modules.get("torbox")
sys.modules.pop("torbox", None)
import torbox  # noqa: E402
if _prior_torbox is not None:
    sys.modules["torbox"] = _prior_torbox
else:
    sys.modules.pop("torbox", None)

import db  # noqa: E402
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


def test_request_download_link_uses_the_accounts_key(monkeypatch):
    seen = {}

    def fake_get(url, params=None, timeout=None, headers=None):
        seen.update(params or {})
        return Resp(body={"data": "https://cdn/x"})
    monkeypatch.setattr(torbox.requests, "get", fake_get)
    assert torbox.request_download_link(2, 77, 0) == "https://cdn/x"
    assert seen["token"] == "k2" and seen["torrent_id"] == 77 and seen["file_id"] == 0


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/test_torbox_client_accounts.py -q -p no:cacheprovider`
Expected: failures on `_headers(1)` (takes no argument), `_last_429` missing, `AuthFailed` missing.

- [ ] **Step 3: Rewrite the account-bound parts of `torbox.py`**

Replace `_headers`:

```python
class AuthFailed(Exception):
    """TorBox answered 401 or 403 for this account: key revoked, plan
    restriction, or the account disabled on their side."""


def _headers(account_id: int) -> dict[str, str]:
    import torbox_pool
    acct = torbox_pool.account(account_id)
    if acct is None:
        raise RuntimeError(f"unknown TorBox account {account_id}")
    return {"Authorization": f"Bearer {acct.api_key}"}


def _any_headers() -> dict[str, str]:
    """For calls not bound to an account (cache checks)."""
    import torbox_pool
    return {"Authorization": f"Bearer {torbox_pool.any_key()}"}


def _check_auth(account_id: int, resp) -> None:
    if resp.status_code in (401, 403):
        import torbox_pool
        torbox_pool.mark_auth_failure(account_id)
        log.warning("TorBox account %s answered %s", account_id, resp.status_code)
        raise AuthFailed(f"account {account_id}: {resp.status_code}")
```

Keep exactly one `Bearer` string in the module: `_any_headers` must build through `_headers`-like code without the literal; simplest is `_any_headers` returning `{"Authorization": "Bearer " + torbox_pool.any_key()}` is still a literal, so instead write `_AUTH = "Bearer {}"` once and use `_AUTH.format(key)` in both builders (the guard test counts lines containing `Bearer`: one).

Budget: `_reserve_createtorrent_slot(account_id, reason, cached=False)` passes `account_id=account_id` to `db.reserve_createtorrent_slot`. `createtorrent_usage(account_id=None, window_sec=3600)` calls `_db.get_createtorrent_log(cutoff, account_id)` and unpacks `(ts, reason, cached, account)`.

Per-account 429: replace `_last_429_at` with `_last_429: dict[int, float] = {}`; `last_429_at(account_id=None)` returns `_last_429.get(account_id)` or, for None, `max(_last_429.values(), default=None)`.

`add_magnet(account_id, magnet, timeout=30, reason="unknown", cached=None)`: header `_headers(account_id)`; on 429 set `_last_429[account_id] = time.time()` and call `torbox_pool.mark_429(account_id)`; call `_check_auth(account_id, resp)` before `raise_for_status()`; `invalidate_mylist_cache(account_id)`.

Mylist: `_mylist: dict[int, dict] = {}` holding `{"items", "ts"}` per account, one `_mylist_refresh_lock` per account in `_mylist_refresh_locks: dict[int, threading.Lock]` created under `_mylist_lock`. `list_torrents(account_id, timeout=30, force_refresh=False)` and `_fetch_mylist(account_id, timeout)` read and write `_mylist[account_id]`; the 403 branch becomes `_check_auth` (raise) instead of caching an empty list. `invalidate_mylist_cache(account_id=None)` drops one or all. `find_by_hash(account_id, info_hash, force_refresh=False)`, `find_by_id(account_id, torrent_id, timeout=15)` (call `_check_auth` before `raise_for_status`), `get_user_info(account_id, timeout=10)`, `get_usage_summary(account_id)`, `title_exists(account_id, title)`, `delete_torrent(account_id, torrent_id, timeout=15)` (an `AuthFailed` is caught like any exception and returns False after marking), `wait_until_ready(account_id, info_hash, timeout=None, torrent_id=None)`.

`check_quota_and_warn(threshold_count, threshold_gb)`: loop `torbox_pool.accounts()`, `get_usage_summary(a.id)`, key `_last_quota_warn` by `(a.id, metric)`, messages prefixed with the label.

New:

```python
def request_download_link(account_id: int, torrent_id: int, file_id: int, timeout: int = 15) -> str | None:
    """The CDN link for one file of a torrent in this account (requestdl)."""
    import torbox_pool
    acct = torbox_pool.account(account_id)
    if acct is None:
        return None
    url = f"{_base_url().rstrip('/')}/torrents/requestdl"
    params = {"token": acct.api_key, "torrent_id": torrent_id, "file_id": file_id, "zip_link": "false"}
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        _check_auth(account_id, resp)
        resp.raise_for_status()
        return (resp.json() or {}).get("data") or None
    except Exception as exc:
        log.warning("requestdl failed account=%s torrent=%s file=%s: %s", account_id, torrent_id, file_id, exc)
        return None
```

`check_cached` and `check_cached_files` use `_any_headers()`.

- [ ] **Step 4: Move the three outside header sites and update every caller**

- `strm_generator.py`: delete `_get_stream_url`; the three callers become `torbox.request_download_link(account_id, torrent_id, file_id)`. At 605 and 1500 the item row is at hand: use `item.get("torbox_account") or torbox_pool.accounts()[0].id`. At 1663 the function receives `torrent_id, file_id`; add an `account_id` parameter and update its one caller (`grep -n "def " strm_generator.py | sed -n` around 1655 to find it).
- `cleanup.py:369`: `torbox.request_download_link(acct, int(torrent_id), main["id"])` where `acct` is the account chosen for that repair.
- `health.py:104-107`: `headers=torbox._headers(torbox_pool.accounts()[0].id)` for now (Task 6 loops accounts).
- `plugins/webplayer/web_player.py:278-296`: delete the local `requestdl` function; callers use `torbox.request_download_link(acct, torrent_id, file_id)`.
- `catbox.py`: add near the top of the module

```python
def _home(item: dict) -> int:
    """The account holding the item's torrent; until Task 3 homes items
    properly, an unhomed item uses the first enabled account."""
    import torbox_pool
    return item.get("torbox_account") or torbox_pool.accounts()[0].id
```

and pass `_home(item)` as the first argument of every `torbox.` call in `_materialize_locked`, `release_idle` and `reconcile_torbox_ids`; `update_virtual_torbox_id(token, torbox_id)` calls become `db.set_virtual_torbox(token, torbox_id, _home(item))`.
- The remaining callers per the table above.

- [ ] **Step 5: Run the tests to verify they pass**

Run the new file, then `tests/test_torbox_ratelimit.py`, `tests/test_torbox_reconcile.py`, `tests/test_catbox*.py`, `tests/test_pack_files.py`, `tests/test_pack_registration.py`, `tests/test_health_rows.py`, `tests/test_overview.py`, then the full suite. Existing tests that call `torbox.add_magnet(magnet, ...)` or fake `torbox.list_torrents(**k)` need the account argument added (`lambda account_id, **k:`); fix them, never weaken them.

- [ ] **Step 6: Mutation checks**

Break and restore: the `mark_429` call in `add_magnet`; the per-account key in `_mylist`; `_check_auth` in `list_torrents`; the account passed to `reserve_createtorrent_slot`.

- [ ] **Step 7: Commit**

```bash
git add torbox.py strm_generator.py cleanup.py health.py plugins/webplayer/web_player.py catbox.py processor.py monitor.py upgrader.py retry_queue.py catchup.py app.py overview.py shell_summary.py metrics_prom.py tests/
git commit -m "refactor(torbox): every account-bound client call names its account

Claude-Session: https://claude.ai/code/session_01E4NjBiGw4m7EjGexJTbQu5"
```

---

### Task 3: Homing in the play path and the other adders

**Files:**
- Modify: `catbox.py` (`_home`, `_materialize_locked` TorBox path lines 503-560 and 646-666, the download link at 717)
- Modify: `processor.py:80-95`, `monitor.py:255-270, 310-317`, `upgrader.py:150-156, 220-226`, `cleanup.py:200-210`, `plugins/webplayer/web_player.py:230-266`, `app.py:1270-1276`
- Test: `tests/test_catbox_homing.py`

**Interfaces:**
- Consumes: `torbox_pool.choose_for_add()`, `torbox_pool.account()`, `torbox.AuthFailed`, `db.set_virtual_torbox`.
- Produces: `catbox._home(item) -> int | None` (the recorded home, None when unhomed); `catbox._adopt_or_choose(item) -> tuple[int, dict | None]` (account id and the live torrent when found in a library); items always carry `torbox_account` with `torbox_id`.

- [ ] **Step 1: Write the failing tests**

`tests/test_catbox_homing.py`:

```python
"""A play uses the account that holds the torrent. An unhomed item adopts
the account whose library already has the hash, else the pool's choice;
a disabled home, an auth failure or a gone torrent re-homes; a 429 does
not."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
_prior = sys.modules.get("torbox")
sys.modules.pop("torbox", None)
import torbox  # noqa: E402
if _prior is not None:
    sys.modules["torbox"] = _prior
else:
    sys.modules.pop("torbox", None)

import catbox  # noqa: E402
import torbox_pool as pool  # noqa: E402

db = catbox.db
H = "a" * 40


def _db_modules():
    """test_catbox_cache_sweep.py imports catbox against a fresh db module
    object; isolate every db object the code under test may be bound to."""
    mods = []
    for m in (db, catbox.db, pool.db):
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
    catbox.invalidate_url_cache()
    torbox.invalidate_mylist_cache()
    monkeypatch.setattr(catbox._settings, "get", lambda k, d=None: {"CATBOX_MODE": True}.get(k, d))
    yield
    _drop_cached_conn()


def _item(token="t", torbox_id=None, account=None):
    with db._connect() as conn:
        conn.execute("INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, torbox_id, torbox_account, file_id) "
                     "VALUES (?, ?, ?, 'Heat', 'movie', ?, ?, 0)", (token, H, f"magnet:?xt=urn:btih:{H}", torbox_id, account))
        conn.commit()
    return db.get_virtual_item(token)


READY = {"id": 5, "hash": H, "download_state": "cached", "download_finished": True, "files": [{"id": 0, "name": "Heat.mkv", "size": 10}]}


@pytest.fixture
def client(monkeypatch):
    """A fake TorBox: per-account libraries and a recorder of every call."""
    libs = {1: [], 2: []}
    calls = []
    monkeypatch.setattr(torbox, "find_by_id", lambda acct, tid, **k: (calls.append(("find_by_id", acct, tid)), next((t for t in libs[acct] if t["id"] == tid), None))[1])
    monkeypatch.setattr(torbox, "find_by_hash", lambda acct, h, **k: (calls.append(("find_by_hash", acct)), next((t for t in libs[acct] if t["hash"] == h), None))[1])
    monkeypatch.setattr(torbox, "list_torrents", lambda acct, **k: list(libs[acct]))
    def add(acct, magnet, **k):
        calls.append(("add", acct))
        t = dict(READY, id=len(libs[acct]) + 10)
        libs[acct].append(t)
        return t
    monkeypatch.setattr(torbox, "add_magnet", add)
    monkeypatch.setattr(torbox, "wait_until_ready", lambda acct, h, **k: next((t for t in libs[acct] if t["hash"] == h), None))
    monkeypatch.setattr(torbox, "request_download_link", lambda acct, tid, fid, **k: (calls.append(("link", acct, tid)), f"https://cdn/{acct}/{tid}")[1])
    monkeypatch.setattr(torbox, "_is_ready", lambda t: bool(t and t.get("download_finished")))
    return libs, calls


def test_a_homed_item_plays_from_its_home_and_nothing_else(client):
    libs, calls = client
    libs[2].append(dict(READY))
    _item(torbox_id=5, account=2)
    assert catbox.materialize("t") == "https://cdn/2/5"
    assert all(c[1] == 2 for c in calls) and ("add", 2) not in calls


def test_an_unhomed_item_adopts_the_account_that_already_has_the_hash(client):
    libs, calls = client
    libs[2].append(dict(READY))
    _item()
    assert catbox.materialize("t") == "https://cdn/2/5"
    it = db.get_virtual_item("t")
    assert (it["torbox_id"], it["torbox_account"]) == (5, 2)
    assert ("add", 1) not in calls and ("add", 2) not in calls


def test_an_unhomed_item_goes_to_the_pools_choice(client, monkeypatch):
    libs, calls = client
    monkeypatch.setattr(pool, "choose_for_add", lambda: pool.account(2))
    _item()
    assert catbox.materialize("t") == "https://cdn/2/10"
    it = db.get_virtual_item("t")
    assert (it["torbox_id"], it["torbox_account"]) == (10, 2)
    assert ("add", 2) in calls and ("add", 1) not in calls


def test_a_disabled_home_re_homes_on_the_next_play(client, monkeypatch):
    libs, calls = client
    libs[2].append(dict(READY))
    _item(torbox_id=5, account=2)
    db.update_torbox_account(2, enabled=False)
    pool.invalidate()
    monkeypatch.setattr(pool, "choose_for_add", lambda: pool.account(1))
    assert catbox.materialize("t") == "https://cdn/1/10"
    assert db.get_virtual_item("t")["torbox_account"] == 1


def test_an_auth_failure_from_the_home_re_homes(client, monkeypatch):
    libs, calls = client
    _item(torbox_id=5, account=2)
    def failing(acct, tid, **k):
        if acct == 2:
            raise torbox.AuthFailed("account 2: 403")
        return next((t for t in libs[acct] if t["id"] == tid), None)
    monkeypatch.setattr(torbox, "find_by_id", failing)
    monkeypatch.setattr(pool, "choose_for_add", lambda: pool.account(1))
    assert catbox.materialize("t") == "https://cdn/1/10"
    assert db.get_virtual_item("t")["torbox_account"] == 1


def test_a_gone_torrent_re_homes_but_a_429_does_not(client, monkeypatch):
    libs, calls = client
    _item(torbox_id=5, account=2)          # not in libs[2]: gone
    monkeypatch.setattr(pool, "choose_for_add", lambda: pool.account(1))
    assert catbox.materialize("t") == "https://cdn/1/10"
    assert db.get_virtual_item("t")["torbox_account"] == 1

    calls.clear()
    def limited(acct, magnet, **k):
        raise torbox.RateLimited()
    monkeypatch.setattr(torbox, "add_magnet", limited)
    _item(token="u")
    monkeypatch.setattr(pool, "choose_for_add", lambda: pool.account(2))
    assert catbox.materialize("u") is None
    assert db.get_virtual_item("u")["torbox_account"] is None, "no home recorded for a refused add"


def test_fixed_mode_adders_pass_one_account_through_an_operation():
    src = open(os.path.join(os.path.dirname(__file__), "..", "processor.py")).read()
    body = src.split("def _try_add_magnet(")[1].split("\ndef ")[0]
    assert "torbox_pool.choose_for_add()" in body
    assert "torbox.add_magnet(acct" in body and "torbox.wait_until_ready(acct" in body
```

(`_try_add_magnet(stream, label, cached=False)` at `processor.py:76` is the processor's add helper.)

- [ ] **Step 2: Run the tests to verify they fail**

Expected: adoption and re-homing tests fail (the Task 2 placeholder always uses account 1's library).

- [ ] **Step 3: Implement homing in `catbox.py`**

Replace the Task 2 `_home` placeholder:

```python
def _home(item: dict) -> int | None:
    """The account holding the item's torrent, or None when the item has
    no torrent on TorBox (or its home is disabled, which counts as none)."""
    import torbox_pool
    acct_id = item.get("torbox_account")
    if not acct_id or not item.get("torbox_id"):
        return None
    acct = torbox_pool.account(acct_id)
    if acct is None or not acct.enabled:
        return None
    return acct_id


def _adopt_or_choose(item: dict) -> tuple[int, dict | None]:
    """Where an unhomed torrent goes: the enabled account whose library
    already holds the hash (no add needed), else the pool's choice."""
    import torbox_pool
    h = item.get("info_hash") or ""
    if h:
        for acct in torbox_pool.accounts():
            try:
                existing = torbox.find_by_hash(acct.id, h)
            except torbox.AuthFailed:
                continue
            if existing and torbox._is_ready(existing):
                log.info("Catbox: %s found in %s's library (id=%s), adopting", item["title"], acct.label, existing["id"])
                return acct.id, existing
    return torbox_pool.choose_for_add().id, None
```

In `_materialize_locked`, the TorBox path becomes:

```python
    torbox_id = item["torbox_id"]
    account_id = _home(item)
    if torbox_id and account_id is None:
        # Homed on an account that no longer exists or is disabled.
        log.info("Catbox: %s was on a disabled account, re-homing", item["title"])
        torbox_id = None
        rematerialized = True

    # Fast path: the home still has the torrent.
    if torbox_id:
        try:
            live = torbox.find_by_id(account_id, torbox_id)
        except torbox.AuthFailed:
            live = None
        if not live or not torbox._is_ready(live):
            torbox_id = None
            rematerialized = True

    # Unhomed: adopt from a library that has it, else add to the pool's choice.
    if not torbox_id and item.get("info_hash"):
        account_id, existing = _adopt_or_choose(item)
        if existing:
            torbox_id = existing["id"]
            db.set_virtual_torbox(token, torbox_id, account_id)

    if not torbox_id and item.get("magnet") and allow_readd:
        try:
            log.info("Catbox: %s adding stored magnet to account %s", item["title"], account_id)
            added = torbox.add_magnet(account_id, item["magnet"], reason="catbox-readd")
            _tid = added.get("id") or added.get("torrent_id")
            existing = added if _tid and torbox._is_ready(added) else (
                torbox.find_by_id(account_id, _tid) if _tid else
                torbox.find_by_hash(account_id, item["info_hash"], force_refresh=True)
            )
            if not (existing and torbox._is_ready(existing)) and _tid:
                existing = torbox.wait_until_ready(
                    account_id, item["info_hash"], timeout=ON_PLAY_READY_TIMEOUT_SEC, torrent_id=_tid)
            if existing and torbox._is_ready(existing):
                torbox_id = existing["id"]
                db.set_virtual_torbox(token, torbox_id, account_id)
                log.info("Catbox: %s added via stored magnet (id=%s, account %s)", item["title"], torbox_id, account_id)
        except Exception as exc:
            exc_str = str(exc)
            is_rate_limited = (isinstance(exc, (torbox.RateLimited, torbox.AuthFailed))
                               or "429" in exc_str or "403" in exc_str)
            log.warning("Catbox: stored-magnet re-add failed for %s on account %s: %s", item["title"], account_id, exc)
            if is_rate_limited:
                # 429: the pool marked the account, new adds avoid it for ten
                # minutes; 401/403: the pool marked an auth failure. Either way
                # this play backs off; the item stays unhomed for the next one.
                _fail_put(token, _FAIL_COOLDOWN_429_SEC)
                if ckey:
                    db.update_playability_fail(ckey, REASON_TB_429)
                return None
```

The search branch (line 646 onward) uses the same `account_id` from `_adopt_or_choose(item)` for `add_magnet`, `find_by_id`, `wait_until_ready`, and stores with `set_virtual_torbox`. The file-listing block and the download link use `account_id`: `torbox.find_by_id(account_id, torbox_id)` and `torbox.request_download_link(account_id, torbox_id, file_id)`.

- [ ] **Step 4: The other adders**

Each operation picks once: `acct = torbox_pool.choose_for_add().id` before the first TorBox call and passes `acct` to `find_by_hash`, `add_magnet`, `wait_until_ready` and `request_download_link` within that operation. Files: `processor.py` (the add helper around line 80), `monitor.py` (262-268 and 315-316), `upgrader.py` (154-155, 224-225), `cleanup.py` (200-210, 369), `plugins/webplayer/web_player.py` (238-266), `app.py` manual add (1274). The library checks in the web player (331, 376) loop `torbox_pool.accounts()` and stop at the first hit.

- [ ] **Step 5: Run the tests to verify they pass**

The new file, then the full suite.

- [ ] **Step 6: Mutation checks**

Break and restore: the disabled-home branch; the adoption loop (skip `find_by_hash`); the `set_virtual_torbox` call after adoption; the `AuthFailed` catch in the fast path.

- [ ] **Step 7: Commit**

```bash
git add catbox.py processor.py monitor.py upgrader.py cleanup.py plugins/webplayer/web_player.py app.py tests/test_catbox_homing.py
git commit -m "feat(catbox): items are homed on the account that holds their torrent

Claude-Session: https://claude.ai/code/session_01E4NjBiGw4m7EjGexJTbQu5"
```

---

### Task 4: Jobs per account

**Files:**
- Modify: `catbox.py` (`release_idle`, `reconcile_torbox_ids`), `torbox.py` (`check_quota_and_warn`, done in Task 2), `app.py:452`
- Test: extend `tests/test_torbox_reconcile.py`, add `tests/test_release_idle_accounts.py`

**Interfaces:**
- Produces: `reconcile_torbox_ids() -> dict` gains `"accounts": {label: {"checked", "cleared", "repointed", "skipped"}}` next to the totals; `release_idle()` unchanged signature.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_torbox_reconcile.py` (its fixture must also insert account 2 and call `pool.invalidate()`; update `_item` to take an account):

```python
def test_reconcile_checks_each_item_against_its_own_accounts_list_and_re_homes_by_hash(monkeypatch):
    import torbox_pool as pool
    db.insert_torbox_account("second", "k2"); pool.invalidate()
    _item("on1", 1, HA, account=1)         # present in 1
    _item("moved", 2, HB, account=1)       # gone from 1, hash lives in account 2 under id 22
    _item("gone", 3, HC, account=2)        # gone everywhere
    lists = {1: [{"id": 1, "hash": HA}], 2: [{"id": 22, "hash": HB}]}
    monkeypatch.setattr(catbox.torbox, "list_torrents", lambda acct, **k: list(lists[acct]))
    out = catbox.reconcile_torbox_ids()
    assert (out["checked"], out["cleared"], out["repointed"]) == (3, 1, 1)
    m = db.get_virtual_item("moved")
    assert (m["torbox_id"], m["torbox_account"]) == (22, 2)
    g = db.get_virtual_item("gone")
    assert (g["torbox_id"], g["torbox_account"]) == (None, None)
    assert out["accounts"]["second"]["cleared"] == 1 and out["accounts"]["main"]["repointed"] == 1


def test_reconcile_skips_an_account_whose_list_fails_and_leaves_its_items(monkeypatch):
    import torbox_pool as pool
    db.insert_torbox_account("second", "k2"); pool.invalidate()
    _item("a", 1, HA, account=1)
    _item("b", 2, HB, account=2)
    def lists(acct, **k):
        if acct == 2:
            raise RuntimeError("down")
        return [{"id": 1, "hash": HA}]
    monkeypatch.setattr(catbox.torbox, "list_torrents", lists)
    out = catbox.reconcile_torbox_ids()
    assert out["accounts"]["second"]["skipped"] and db.get_virtual_item("b")["torbox_id"] == 2
    assert out["accounts"]["main"]["skipped"] is None
```

`tests/test_release_idle_accounts.py` (same fixture shape as the reconcile file, plus the `torbox` import dance):

```python
def test_release_idle_deletes_through_the_items_home_and_clears_both_columns(monkeypatch):
    db.insert_torbox_account("second", "k2"); pool.invalidate()
    with db._connect() as conn:
        conn.execute("INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, torbox_id, torbox_account, last_played) "
                     "VALUES ('old', 'h', 'm', 'Old', 'movie', 7, 2, '2000-01-01 00:00:00')")
        conn.commit()
    deleted = []
    monkeypatch.setattr(catbox.torbox, "delete_torrent", lambda acct, tid, **k: (deleted.append((acct, tid)), True)[1])
    assert catbox.release_idle() == 1
    assert deleted == [(2, 7)]
    it = db.get_virtual_item("old")
    assert (it["torbox_id"], it["torbox_account"]) == (None, None)
```

- [ ] **Step 2: Run the tests to verify they fail**

- [ ] **Step 3: Implement**

`release_idle`: `deleted = torbox.delete_torrent(item["torbox_account"], item["torbox_id"])`; `still_there = torbox.find_by_id(item["torbox_account"], item["torbox_id"])`; clear with `db.set_virtual_torbox(item["token"], None, None)`. An item with a torbox id but no account (cannot happen after the migration, guard anyway) is cleared without a delete.

`reconcile_torbox_ids`: per enabled account fetch `torbox.list_torrents(a.id, force_refresh=True)` into `lists[a.id]`, `skipped[a.id]` set to the reason when the list is empty or raises. Build `hash_to_home = {hash: (account_id, torrent_id)}` over the successful lists. For each item: if its account's list was skipped, leave it; if `torbox_id` is in that account's ids, fine; else if `_token_lock(token).locked()`, skip; else if the hash is in `hash_to_home`, `set_virtual_torbox(token, tid, acct)` and count repointed under the item's old account label; else clear both and count cleared. Result gains `"accounts": {label: {...}}`.

`app.py:452`: the quota job stays; `torbox.check_quota_and_warn` already loops accounts (Task 2).

- [ ] **Step 4: Run the tests, mutation-check** (the per-account list lookup, the skip on a failed list, the delete account argument), **commit**

```bash
git add catbox.py tests/test_torbox_reconcile.py tests/test_release_idle_accounts.py
git commit -m "feat(catbox): idle release and the id check work per account

Claude-Session: https://claude.ai/code/session_01E4NjBiGw4m7EjGexJTbQu5"
```

---

### Task 5: Account endpoints and the Settings card

**Files:**
- Modify: `app.py` (after `/ui/api/torbox-usage`), `settings.py` (debrid section: `_custom("TorboxAccounts", "TorBox accounts")` after the base URL field; `_UNLISTED_KEYS` unchanged)
- Modify: `frontend/src/api.ts` (types and client), `frontend/src/pages/admin/settings/customCards.tsx` (new `TorboxAccounts` card, registered in `CUSTOM_CARDS`)
- Test: `tests/test_torbox_accounts_api.py`, `frontend/src/pages/admin/settings/customCards.test.tsx`

**Interfaces:**
- Produces (backend): `GET /ui/api/torbox-accounts` -> `{accounts: [{id, label, enabled, key_hint, items, health: {rate_limited_until, auth_failed_at, budget_left}}]}` (`key_hint` is the last four characters); `POST /ui/api/torbox-accounts` `{label, api_key}` -> `{ok, id}` or `{ok: false, message}`; `POST /ui/api/torbox-accounts/<id>` `{label?, api_key?, enabled?}` -> `{ok, message}`; `DELETE /ui/api/torbox-accounts/<id>` -> `{ok, message}` (refused with the item count when items are homed there, refused for id 1); `POST /ui/api/torbox-accounts/<id>/test` -> the TorBox tester's `{ok, message}` against that account's key. All admin only; every write calls `torbox_pool.invalidate()`.
- Produces (frontend): `api.torboxAccounts()`, `api.torboxAccountAdd(body)`, `api.torboxAccountUpdate(id, body)`, `api.torboxAccountDelete(id)`, `api.torboxAccountTest(id)`; type `TorboxAccount`.

- [ ] **Step 1: Write the failing backend test**

`tests/test_torbox_accounts_api.py` (isolated db fixture as in Task 1; `_src()` reads `app.py`):

```python
def test_routes_exist_and_are_admin_only():
    src = _src("app.py")
    for route in ('@app.get("/ui/api/torbox-accounts")', '@app.post("/ui/api/torbox-accounts")',
                  '@app.post("/ui/api/torbox-accounts/<int:account_id>")',
                  '@app.delete("/ui/api/torbox-accounts/<int:account_id>")',
                  '@app.post("/ui/api/torbox-accounts/<int:account_id>/test")'):
        assert route in src
        body = src.split(route)[1].split("\n@app.")[0]
        assert "auth.is_admin()" in body and "torbox_accounts_api." in body


def test_list_hides_keys_and_carries_items_and_health():
    import torbox_accounts_api as api
    db.insert_torbox_account("second", "k2-secret-tail")
    _item("a", 2)
    out = api.list_accounts()
    assert [a["label"] for a in out] == ["main", "second"]
    assert out[1]["key_hint"] == "tail" and out[1]["items"] == 1 and "api_key" not in out[1]
    assert set(out[0]["health"]) == {"rate_limited_until", "auth_failed_at", "budget_left"}


def test_add_update_delete_rules():
    import torbox_accounts_api as api
    assert api.add("", "k")["ok"] is False and api.add("x", "")["ok"] is False
    r = api.add("second", "k2"); assert r["ok"] and r["id"] == 2
    assert api.add("second", "k3")["ok"] is False, "labels are unique"
    assert api.update(2, enabled=False)["ok"] and db.get_torbox_account(2)["enabled"] == 0
    assert api.update(9, label="x")["ok"] is False
    _item("a", 2)
    r = api.delete(2)
    assert r["ok"] is False and "1 title" in r["message"]
    db.set_virtual_torbox("a", None, None)
    assert api.delete(2)["ok"] and db.get_torbox_account(2) is None
    assert api.delete(1)["ok"] is False


def test_test_runs_the_torbox_tester_with_that_accounts_key(monkeypatch):
    import torbox_accounts_api as api
    import service_tests
    seen = {}
    monkeypatch.setattr(service_tests, "run", lambda kind, values: (seen.update(values), {"ok": True, "message": "ok"})[1])
    db.insert_torbox_account("second", "k2")
    assert api.test(2)["ok"] is True and seen["TORBOX_API_KEY"] == "k2"
    assert api.test(9)["ok"] is False
```

- [ ] **Step 2: Run to verify it fails** (`ModuleNotFoundError: torbox_accounts_api`).

- [ ] **Step 3: Create `torbox_accounts_api.py` and the routes**

```python
"""Admin actions on the TorBox account pool, behind /ui/api/torbox-accounts."""
import logging

import db
import torbox_pool

log = logging.getLogger(__name__)


def list_accounts() -> list[dict]:
    counts = db.count_items_by_account()
    out = []
    for a in torbox_pool.accounts(enabled_only=False):
        h = torbox_pool.health(a.id)
        out.append({"id": a.id, "label": a.label, "enabled": a.enabled, "key_hint": a.api_key[-4:],
                    "items": counts.get(a.id, 0),
                    "health": {k: h[k] for k in ("rate_limited_until", "auth_failed_at", "budget_left")}})
    return out


def add(label: str, api_key: str) -> dict:
    label, api_key = (label or "").strip(), (api_key or "").strip()
    if not label or not api_key:
        return {"ok": False, "message": "label and API key are required"}
    if any(a.label == label for a in torbox_pool.accounts(enabled_only=False)):
        return {"ok": False, "message": f"an account labelled {label!r} exists"}
    new_id = db.insert_torbox_account(label, api_key)
    torbox_pool.invalidate()
    db.log_activity("added", "TorBox account", label, True)
    return {"ok": True, "id": new_id, "message": f"account {label} added"}


def update(account_id: int, *, label=None, api_key=None, enabled=None) -> dict:
    if db.get_torbox_account(account_id) is None:
        return {"ok": False, "message": "unknown account"}
    if account_id == 1 and api_key is not None:
        import settings
        settings.set("TORBOX_API_KEY", api_key)   # mirrors into row 1
        api_key = None
    db.update_torbox_account(account_id, label=label, api_key=api_key, enabled=enabled)
    torbox_pool.invalidate()
    return {"ok": True, "message": "saved"}


def delete(account_id: int) -> dict:
    if account_id == 1:
        return {"ok": False, "message": "account 1 is the configured TorBox API key; change it in Settings instead"}
    if db.get_torbox_account(account_id) is None:
        return {"ok": False, "message": "unknown account"}
    homed = db.count_items_by_account().get(account_id, 0)
    if homed:
        return {"ok": False, "message": f"{homed} title{'s' if homed != 1 else ''} still on this account; disable it instead, they move on their next play"}
    db.delete_torbox_account(account_id)
    torbox_pool.invalidate()
    return {"ok": True, "message": "account removed"}


def test(account_id: int) -> dict:
    import service_tests
    acct = torbox_pool.account(account_id)
    if acct is None:
        return {"ok": False, "message": "unknown account"}
    return service_tests.run("torbox", {"TORBOX_API_KEY": acct.api_key})
```

Routes in `app.py` after `ui_api_torbox_usage`:

```python
@app.get("/ui/api/torbox-accounts")
def ui_api_torbox_accounts():
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import torbox_accounts_api
    return jsonify(accounts=torbox_accounts_api.list_accounts())


@app.post("/ui/api/torbox-accounts")
def ui_api_torbox_accounts_add():
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import torbox_accounts_api
    p = request.get_json(silent=True) or {}
    return jsonify(**torbox_accounts_api.add(str(p.get("label") or ""), str(p.get("api_key") or "")))


@app.post("/ui/api/torbox-accounts/<int:account_id>")
def ui_api_torbox_accounts_update(account_id: int):
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import torbox_accounts_api
    p = request.get_json(silent=True) or {}
    return jsonify(**torbox_accounts_api.update(
        account_id, label=p.get("label"), api_key=p.get("api_key"),
        enabled=None if p.get("enabled") is None else bool(p.get("enabled"))))


@app.delete("/ui/api/torbox-accounts/<int:account_id>")
def ui_api_torbox_accounts_delete(account_id: int):
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import torbox_accounts_api
    return jsonify(**torbox_accounts_api.delete(account_id))


@app.post("/ui/api/torbox-accounts/<int:account_id>/test")
def ui_api_torbox_accounts_test(account_id: int):
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import torbox_accounts_api
    return jsonify(**torbox_accounts_api.test(account_id))
```

(`service_tests.run(kind, values)` is the entry point the Settings tester uses; confirm with `grep -n "^def run" service_tests.py`.)

- [ ] **Step 4: Settings schema and the card**

`settings.py` debrid section, after the `TORBOX_BASE_URL` field: `_custom("TorboxAccounts", "TorBox accounts"),`. The schema guard test (`tests/test_settings_schema.py`) accepts custom fields.

`frontend/src/api.ts`:

```ts
export interface TorboxAccount {
  id: number; label: string; enabled: boolean; key_hint: string; items: number;
  health: { rate_limited_until: number | null; auth_failed_at: number | null; budget_left: number };
}
```

and in `api`:

```ts
  torboxAccounts: () => http<{ accounts: TorboxAccount[] }>('/ui/api/torbox-accounts'),
  torboxAccountAdd: (body: { label: string; api_key: string }) =>
    http<{ ok: boolean; id?: number; message: string }>('/ui/api/torbox-accounts', { method: 'POST', body: JSON.stringify(body) }),
  torboxAccountUpdate: (id: number, body: { label?: string; api_key?: string; enabled?: boolean }) =>
    http<{ ok: boolean; message: string }>(`/ui/api/torbox-accounts/${id}`, { method: 'POST', body: JSON.stringify(body) }),
  torboxAccountDelete: (id: number) => http<{ ok: boolean; message: string }>(`/ui/api/torbox-accounts/${id}`, { method: 'DELETE' }),
  torboxAccountTest: (id: number) => http<{ ok: boolean; message: string }>(`/ui/api/torbox-accounts/${id}/test`, { method: 'POST' }),
```

`customCards.tsx`, new card (registered as `TorboxAccounts` in `CUSTOM_CARDS`):

```tsx
export function TorboxAccounts(_props: CardProps) {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ['torbox-accounts'], queryFn: api.torboxAccounts });
  const [label, setLabel] = useState('');
  const [key, setKey] = useState('');
  const [msg, setMsg] = useState<Record<number | 'new', string>>({} as Record<number | 'new', string>);
  const refresh = () => qc.invalidateQueries({ queryKey: ['torbox-accounts'] });
  const note = (id: number | 'new', text: string) => setMsg((m) => ({ ...m, [id]: text }));

  const add = async () => {
    const r = await api.torboxAccountAdd({ label, api_key: key });
    note('new', r.message);
    if (r.ok) { setLabel(''); setKey(''); refresh(); }
  };
  const toggle = async (a: TorboxAccount) => { const r = await api.torboxAccountUpdate(a.id, { enabled: !a.enabled }); note(a.id, r.message); refresh(); };
  const test = async (a: TorboxAccount) => { const r = await api.torboxAccountTest(a.id); note(a.id, r.message); };
  const remove = async (a: TorboxAccount) => { const r = await api.torboxAccountDelete(a.id); note(a.id, r.message); if (r.ok) refresh(); };

  return (
    <div className="space-y-3">
      <div className="text-sm font-semibold">TorBox accounts</div>
      <p className="text-xs text-muted">Several TorBox accounts are used as equal peers: a new torrent goes to the least loaded one, every play uses the account that holds its torrent. Account 1 is the API key above. A disabled account keeps its torrents until its titles move on their next play.</p>
      <ul className="space-y-1 text-xs">
        {(q.data?.accounts ?? []).map((a) => (
          <li key={a.id} className="flex flex-wrap items-center gap-2 rounded border border-border p-2">
            <span className="font-semibold">{a.label}</span>
            <span className="font-mono text-muted">key ending {a.key_hint}</span>
            <span className="text-muted">{a.items} titles, {a.health.budget_left} adds left</span>
            {!a.enabled && <span className="text-warn">disabled</span>}
            {a.health.auth_failed_at && <span className="text-danger">key rejected</span>}
            <span className="ml-auto flex items-center gap-1">
              <Button variant="ghost" onClick={() => test(a)}>Test</Button>
              {a.id !== 1 && <Button variant="ghost" onClick={() => toggle(a)}>{a.enabled ? 'Disable' : 'Enable'}</Button>}
              {a.id !== 1 && <Button variant="ghost" onClick={() => remove(a)}>Remove</Button>}
            </span>
            {msg[a.id] && <span role="status" className="basis-full text-muted">{msg[a.id]}</span>}
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap items-center gap-2">
        <input aria-label="New account label" className="rounded border border-border bg-bg px-2 py-1 text-xs" placeholder="label" value={label} onChange={(e) => setLabel(e.target.value)} />
        <input aria-label="New account API key" type="password" className="rounded border border-border bg-bg px-2 py-1 text-xs" placeholder="API key" value={key} onChange={(e) => setKey(e.target.value)} />
        <Button onClick={add} disabled={!label || !key}>Add account</Button>
        {msg.new && <span role="status" className="text-muted">{msg.new}</span>}
      </div>
    </div>
  );
}
```

- [ ] **Step 5: Frontend test**

Append to `customCards.test.tsx` (follow the file's existing mocking of `api`): the card lists accounts with label, hint and counts; account 1 has Test only; Add posts `{label, api_key}` and shows the message; Remove shows a refusal message and keeps the row.

- [ ] **Step 6: Run both suites, mutation-check** (`delete` refusal when items are homed, `delete(1)`, the label-uniqueness branch), **build, commit**

```bash
git add torbox_accounts_api.py app.py settings.py frontend/src static/app tests/test_torbox_accounts_api.py
git commit -m "feat(settings): TorBox accounts card and endpoints

Claude-Session: https://claude.ai/code/session_01E4NjBiGw4m7EjGexJTbQu5"
```

---

### Task 6: Overview, health rows, drawer label, metrics

**Files:**
- Modify: `overview.py:74-80, 130-140`, `health.py:81-110`, `metrics_prom.py:60-70, 77-80, 94-97, 113-118`, `library_admin.py:211`
- Modify: `frontend/src/api.ts` (`OverviewPayload.torbox.accounts`, `LibraryDetail.items[].torbox_account`), `frontend/src/pages/admin/overview/TorboxCard.tsx`, `StatusStrip.tsx`, `frontend/src/pages/admin/library/cards/ReleaseCard.tsx`
- Test: `tests/test_overview.py`, `tests/test_health_rows.py`, `tests/test_metrics_accounts.py`, `TorboxCard.test.tsx`, `StatusStrip.test.tsx`, `cards.test.tsx`

**Interfaces:**
- Produces: `/ui/api/overview` `torbox.accounts: [{id, label, adds: {uncached, cached, limit, resets_in_sec}, torrents, last_429_at}]`; `status.torbox_adds` keeps its shape and sums accounts, plus `over: string | null` naming the first account at 45 or more. Health rows `TorBox <label>` per enabled account and `TorBox adds this hour (<label>)` per account. Drawer items carry `torbox_account` and `torbox_account_label`. Gauges `mycelium_torbox_torrent_count{account}`, `mycelium_torbox_total_bytes{account}`, `mycelium_catbox_active_in_torbox{account}`, `mycelium_service_up{service="torbox",account}`, new `mycelium_torbox_createtorrent_used{account}`.

- [ ] **Step 1: Failing tests**

`tests/test_overview.py`, add (fixture inserts account 2):

```python
def test_overview_lists_torbox_accounts_and_names_the_one_over_the_warn_line(monkeypatch):
    import torbox_pool as pool
    db.insert_torbox_account("second", "k2"); pool.invalidate()
    now = time.time()
    for _ in range(46):
        db.reserve_createtorrent_slot(now, "x", 60, 10, account_id=2)
    out = overview.build(force=True)
    accts = out["torbox"]["accounts"]
    assert [a["label"] for a in accts] == ["main", "second"]
    assert accts[1]["adds"]["uncached"] == 46 and accts[0]["adds"]["uncached"] == 0
    assert out["status"]["torbox_adds"]["uncached"] == 46 and out["status"]["torbox_adds"]["over"] == "second"
```

`tests/test_health_rows.py`, add: with two enabled accounts the rows contain `TorBox main` and `TorBox second`, each pinged with its own key (`headers["Authorization"]` ends with `k1` / `k2`), and a 403 on the second makes only that row `down`.

`tests/test_metrics_accounts.py`: `metrics_prom.refresh_gauges()` with faked `torbox.get_usage_summary(acct)` sets `torbox_torrent_count.labels(account="main")` and `labels(account="second")`; `torbox_createtorrent_used` per account from reserved slots.

Frontend: `TorboxCard.test.tsx` renders two account columns with their budgets; `StatusStrip.test.tsx` turns the adds cell amber when `over` is set and puts the label in the sub line; `cards.test.tsx` shows `TorBox id 5 (second)` on the release card.

- [ ] **Step 2: Implement**

`overview.py`:

```python
def _torbox_accounts() -> list[dict]:
    import torbox
    import torbox_pool
    counts = db.count_items_by_account()
    out = []
    for a in torbox_pool.accounts():
        u = torbox.createtorrent_usage(a.id)
        last = torbox.last_429_at(a.id)
        out.append({"id": a.id, "label": a.label,
                    "adds": {"uncached": u["count"], "cached": u["cached_count"], "limit": u["limit"], "resets_in_sec": u["resets_in_sec"]},
                    "torrents": counts.get(a.id, 0),
                    "last_429_at": datetime.fromtimestamp(last, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if last else None})
    return out
```

`_torbox_adds()` sums `uncached` and `cached` over `_torbox_accounts()`, keeps `limit` at 60 times the account count, `resets_in_sec` the maximum, and adds `"over": next((a["label"] for a in accts if a["adds"]["uncached"] >= 45), None)`. The payload's `torbox` block gains `"accounts": _safe(_torbox_accounts, [], name="torbox_accounts", errors=errors)`.

`health.py`: replace the single ping with a loop over `torbox_pool.accounts()`: `_ping(f"TorBox {a.label}", url, headers=torbox._headers(a.id), down_codes=(401, 403))`; `_torbox_budget_row(a)` per account, named `TorBox adds this hour ({label})`, warn at 45.

`metrics_prom.py`: gauges gain `["account"]`; `refresh_gauges` loops accounts for `get_usage_summary`, counts items per account for `catbox_active_in_torbox`, exports `torbox_createtorrent_used.labels(account=a.label).set(torbox.createtorrent_usage(a.id)["count"])`; the `service_up` update site (find with `grep -n "service_up" metrics_prom.py`) labels the TorBox row per account.

`library_admin.py:211`: add `"torbox_account"` to the key list and a `"torbox_account_label"` computed from `torbox_pool.account(i.get("torbox_account"))`.

Frontend: `OverviewPayload.torbox.accounts` type; `TorboxCard` renders the adds column once per account (label header, bar, cached count, resets) and the torrents count per account; `StatusStrip` uses `adds.over` for the tone and `sub` (`"second at 46 / 60"`); `ReleaseCard` renders `TorBox id {i.torbox_id} ({i.torbox_account_label})` when the label is present.

- [ ] **Step 3: Run both suites, mutation-check** (`over` computation, the per-account ping loop, the account label on the gauge), **build, commit**

```bash
git add overview.py health.py metrics_prom.py library_admin.py frontend/src static/app tests/
git commit -m "feat(overview): TorBox accounts on the Overview, health rows, drawer and metrics

Claude-Session: https://claude.ai/code/session_01E4NjBiGw4m7EjGexJTbQu5"
```

---

### Task 7: Documentation and changelog

**Files:**
- Modify: `docs/INTEGRATIONS.md` (new section "TorBox: several accounts" before "Jellyfin: versions and authentication"), `README.md` (one paragraph under the TorBox setup), `docs/SCALING.md` (a note that the add budget scales with accounts), `CHANGELOG.md` (`## [Unreleased]`, "Added").

- [ ] **Step 1: Write the docs**

INTEGRATIONS section content: what the pool is, how account 1 relates to the API key setting, where extra accounts are added, the selection rule in one sentence, that a play never rebalances, what disable does to torrents, what remove refuses, the Overview columns, the metrics labels. No double dashes.

CHANGELOG entry:

```markdown
### Added

- TorBox account pool. Several TorBox API keys can be configured in
  Settings (section Debrid, "TorBox accounts") and are used as equal
  peers: a new torrent goes to the least loaded healthy account (fewest
  torrents, budget left, no recent 429 or auth failure), every play of a
  title uses the account that holds its torrent, and a disabled or failing
  account hands its titles over on their next play. The hourly add budget
  is counted per account. The Overview's TorBox card, the health rows, the
  Library drawer and the Prometheus gauges show accounts by label. A
  single-key install is unchanged: the existing key becomes account 1.
```

- [ ] **Step 2: Guard**

Run `grep -rn "\-\-" docs/INTEGRATIONS.md README.md docs/SCALING.md CHANGELOG.md | grep -v "^\S*:[0-9]*:|"` and expect no output beyond table separators.

- [ ] **Step 3: Commit**

```bash
git add docs/INTEGRATIONS.md README.md docs/SCALING.md CHANGELOG.md
git commit -m "docs: TorBox account pool

Claude-Session: https://claude.ai/code/session_01E4NjBiGw4m7EjGexJTbQu5"
```

---

## Whole-branch review and release

After Task 7: one opus review of `git diff -U10 <base>..HEAD -- . ':(exclude)static/app'` covering correctness, races (token lock versus pool cache, the reconcile per account), the single-key path staying unchanged, secrets in logs (labels only, never keys), and the tests. One fix wave, scoped re-review, then release 0.29.0 on request (bump `APP_VERSION`, changelog heading, `releases.json` entry, tag, watch the Release and CI runs by id).
