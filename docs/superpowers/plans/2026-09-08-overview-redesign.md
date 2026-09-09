# Admin Overview Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the admin Overview as five bands (status strip, activity, library, TorBox, collapsed reference) fed by one aggregated endpoint, adding attention, approvals, plays and scraper state.

**Architecture:** A new backend module `overview.py` aggregates every database-derived figure behind `GET /ui/api/overview` with a short cache; service pings and the TorBox list keep their existing endpoints. The page becomes a composition of components under `frontend/src/pages/admin/overview/`, with a new `StatusCell` primitive; reference sections are native `details` elements that remember their state and fetch only when opened.

**Tech Stack:** Python 3.12 + Flask + SQLite; React 18 + TypeScript + Tailwind + react-query; pytest, vitest + testing-library.

**Spec:** `docs/superpowers/specs/2026-09-08-overview-redesign-design.md`

## Global Constraints

- NEVER write an em-dash (`--` as punctuation in prose or comments, or U+2014) anywhere. Use a comma, a colon, or a new sentence.
- Backend tests never import `app.py`; route checks read source text through a `_src()` helper. Every DB test file carries its own `_isolated_db` fixture (`_drop_cached_conn`, monkeypatch `db.DB_PATH`, `db.init()`); there is no conftest. No network in tests.
- Backend runner: `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/ -q -p no:cacheprovider` (1073 passing at start). Frontend from `frontend/`: `npx tsc --noEmit && npx vitest run` (276 passing at start). Mutation-check every new test.
- The built bundle `static/app/` is committed with the source: the task that changes the page composition runs `npm run build` and commits `static/app/`.
- Existing endpoints stay. The new endpoint is `GET /ui/api/overview`, admin only, response shape exactly as in the spec section 1.
- Status cell tones and links exactly as the spec section 2: services red when any service is down, scrapers amber when any enabled scraper is down, TorBox adds amber from 45 uncached, failures red above zero, queue amber when the retry queue is non-empty, attention amber above zero, approvals amber above zero; links `#settings`, `#scrapers`, `#library?view=attention` (failures and attention), `#library?view=queue`, `#requests`. A link renders only when the cell is amber or red.
- Reference sections closed by default, state under localStorage key `mycelium.overview.<id>` with ids `metrics`, `endpoints`, `folders`; their queries run only when open.
- Number formats: egress in TB with two decimals, TorBox library in GiB, percentages rounded.
- Commit trailer on every commit: `Claude-Session: https://claude.ai/code/session_017Cc8iouqJoYhUcnJhhgapA`. No Co-Authored-By.

---

## File structure

| File | Responsibility |
|---|---|
| `overview.py` (new) | `build()` and cached `get()` for the aggregated payload |
| `db.py` | `play_counts`, `count_requests_mirrored`, `oldest_pending_user_request_age_sec` |
| `egress_estimate.py` | `recent(window_sec)` |
| `torbox.py` | `_last_429_at`, `last_429_at()` |
| `app.py` | the route |
| `frontend/src/api.ts` | `OverviewPayload` type, `api.overview` |
| `frontend/src/components/primitives/StatusCell.tsx` | the status cell primitive |
| `frontend/src/pages/admin/overview/format.ts` | `formatGiB`, `formatTB`, `formatCountdown`, `formatLatency`, `relativeAge` |
| `frontend/src/pages/admin/overview/StatusStrip.tsx`, `ScraperStrip.tsx` | band 1 |
| `frontend/src/pages/admin/overview/ActivityBand.tsx`, `LibraryBand.tsx` | bands 2 and 3 |
| `frontend/src/pages/admin/overview/TorboxCard.tsx`, `ReferenceSection.tsx`, `reference/MetricsPanel.tsx`, `reference/EndpointsPanel.tsx`, `reference/FoldersPanel.tsx` | bands 4 and 5 |
| `frontend/src/pages/admin/Overview.tsx` | composition only |
| tests alongside each file | |

---

### Task 1: Aggregated endpoint

**Files:**
- Create: `overview.py`
- Modify: `db.py` (after `egress_this_month`), `egress_estimate.py`, `torbox.py` (`add_magnet` 429 branch), `app.py` (next to `ui_api_stats`)
- Test: `tests/test_overview.py`

**Interfaces:**
- Consumes: `stats._build_overview()`, `db.get_request_stats(7)`, `db.count_wanted_episodes_by_status()`, `db.get_pending_retries()`, `library_admin.view_counts()`, `requests_admin.view_counts()`, `scrapers.health_rows()`, `torbox.createtorrent_usage()`, `library_sync.orphans()`, `db.get_last_cleanup_run()`.
- Produces: `overview.get(force=False) -> dict` with the spec shape; `db.play_counts(days: int) -> dict` (`{"plays": int, "titles": int}`, `days=0` means the current UTC calendar day); `db.count_requests_mirrored() -> tuple[int, int]`; `db.oldest_pending_user_request_age_sec() -> int | None`; `egress_estimate.recent(window_sec: int = 900) -> int`; `torbox.last_429_at() -> float | None`; route `GET /ui/api/overview`.

- [ ] **Step 1: Write the failing tests**

```python
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
```

Before running: check `db.create_user` and `db.create_user_request` signatures in `db.py` (`grep -n "def create_user\b\|def create_user_request" db.py`) and adapt the two calls in `test_oldest_pending_approval_age` to the real parameter order. `db.update_user_request_status(req_id, status, reviewed_by=None, note=None)` exists.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/test_overview.py -q -p no:cacheprovider`
Expected: FAIL at import (`No module named 'overview'`).

- [ ] **Step 3: db helpers**

Append after `egress_this_month` in `db.py`:

```python
def play_counts(days: int) -> dict:
    """Plays and distinct titles from the egress log. One estimated row is
    one play of a redirected title; proxied rows count one play per
    distinct (token, calendar day). days=0 means the current UTC day,
    otherwise the last `days` days."""
    since = ("strftime('%Y-%m-%d 00:00:00', 'now')" if days <= 0
             else f"datetime('now', '-{int(days)} days')")
    with _connect() as conn:
        estimated = conn.execute(
            f"SELECT COUNT(*) AS n FROM egress_log WHERE estimated = 1 AND created_at >= {since}"
        ).fetchone()["n"]
        proxied = conn.execute(
            f"SELECT COUNT(*) AS n FROM (SELECT DISTINCT token, date(created_at) AS d "
            f"FROM egress_log WHERE estimated = 0 AND created_at >= {since})"
        ).fetchone()["n"]
        titles = conn.execute(
            f"SELECT COUNT(DISTINCT token) AS n FROM egress_log WHERE created_at >= {since}"
        ).fetchone()["n"]
    return {"plays": int(estimated) + int(proxied), "titles": int(titles)}


def count_requests_mirrored() -> tuple[int, int]:
    """(mirrored, total) over success requests, from requests.arr_mirrored_at."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS total, COALESCE(SUM(arr_mirrored_at IS NOT NULL), 0) AS mirrored "
            "FROM requests WHERE status = 'success'").fetchone()
    return int(row["mirrored"]), int(row["total"])


def oldest_pending_user_request_age_sec() -> int | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT CAST(strftime('%s', 'now') AS INTEGER) - CAST(strftime('%s', MIN(created_at)) AS INTEGER) AS age "
            "FROM user_requests WHERE status = 'pending'").fetchone()
    return int(row["age"]) if row and row["age"] is not None else None
```

- [ ] **Step 4: `egress_estimate.recent` and `torbox.last_429_at`**

In `egress_estimate.py`, after `note_redirect`:

```python
def recent(window_sec: int = 900) -> int:
    """Tokens the redirect branch resolved within the last window_sec."""
    now = time.monotonic()
    with _lock:
        return sum(1 for seen in _last_seen.values() if now - seen <= window_sec)
```

Note: `_reset()` already exists; `recent` must use `time.monotonic()` directly here while tests monkeypatch `_now`. To keep the two consistent, change `recent` to `now = _now()` and make the test above rely on `_now`, which it already does.

In `torbox.py`, near `_last_quota_warn`:

```python
_last_429_at: float | None = None  # wall-clock time of the last 429 from createtorrent


def last_429_at() -> float | None:
    return _last_429_at
```

and in `add_magnet`, inside the `if resp.status_code == 429:` branch, before the warning: `global _last_429_at` at the top of the function and `_last_429_at = time.time()` in the branch.

- [ ] **Step 5: `overview.py`**

```python
"""The aggregated admin Overview payload: everything the database and
in-memory state can answer in one call. Service pings and the TorBox
list stay on their own endpoints because they call other services.

Every block is built through _safe() so one failing source (a scraper
registry error, a TorBox usage query) leaves the rest of the page
usable; the failed block shows its neutral default.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

import db

log = logging.getLogger(__name__)

CACHE_TTL_SEC = 30
_cache: dict = {"data": None, "ts": 0.0}
_lock = threading.Lock()


def _safe(fn, default):
    try:
        return fn()
    except Exception as exc:
        log.debug("overview block failed: %s", exc)
        return default


def _scrapers() -> list[dict]:
    import scrapers
    return [{"name": r["name"], "state": r["state"], "latency_ms": r.get("latency_ms")}
            for r in scrapers.health_rows()]


def _torbox_adds() -> dict:
    import torbox
    u = torbox.createtorrent_usage()
    return {"uncached": int(u.get("count", 0)), "cached": int(u.get("cached_count", 0) or 0),
            "limit": int(u.get("limit", 60) or 60), "resets_in_sec": int(u.get("resets_in_sec", 0) or 0)}


def _approvals() -> dict:
    import requests_admin
    return {"pending": int(requests_admin.view_counts().get("pending", 0)),
            "oldest_age_sec": db.oldest_pending_user_request_age_sec()}


def _attention() -> int:
    import library_admin
    return int(library_admin.view_counts().get("attention", 0))


def _consistency() -> dict:
    import library_sync
    orphans = _safe(library_sync.orphans, {"db_count": 0, "strm_without_db": 0, "db_without_strm": 0})
    mirrored, total = db.count_requests_mirrored()
    last = db.get_last_cleanup_run()
    return {"db_items": int(orphans.get("db_count", 0)),
            "strm_without_db": int(orphans.get("strm_without_db", 0)),
            "db_without_strm": int(orphans.get("db_without_strm", 0)),
            "arr_mirrored": mirrored, "arr_total": total,
            "last_cleanup": ({"ran_at": last["ran_at"], "deleted": int(last.get("deleted", 0))} if last else None)}


def build() -> dict:
    import egress_estimate
    import stats
    import torbox
    base = stats._build_overview()
    req = db.get_request_stats(days=7)
    wanted = db.count_wanted_episodes_by_status()
    today = db.play_counts(0)
    week = db.play_counts(7)
    last_429 = torbox.last_429_at()
    return {
        "status": {
            "scrapers": _safe(_scrapers, []),
            "torbox_adds": _safe(_torbox_adds, {"uncached": 0, "cached": 0, "limit": 60, "resets_in_sec": 0}),
            "failures_7d": int(req["failed"]),
            "queue": {"retry": len(_safe(db.get_pending_retries, [])), "wanted": int(wanted.get("wanted", 0))},
            "attention": _safe(_attention, 0),
            "approvals": _safe(_approvals, {"pending": 0, "oldest_age_sec": None}),
        },
        "activity": {
            "plays": {"today": today["plays"], "week": week["plays"],
                      "titles_today": today["titles"], "titles_week": week["titles"]},
            "requests_7d": {"total": int(req["succeeded"]) + int(req["failed"]),
                            "succeeded": int(req["succeeded"]), "failed": int(req["failed"]),
                            "success_rate": base["requests"]["success_rate_7d"]},
            "egress": {"proxied_bytes": base["egress_bytes_month"],
                       "estimated_bytes": base["egress_estimated_bytes_month"]},
        },
        "library": {
            "movies": base["library"]["movie_count"],
            "episodes": base["library"]["episode_count"],
            "series": base["library"]["series_count"],
            "wanted": int(wanted.get("wanted", 0)),
            "upcoming": int(base.get("movies_pending", 0)),
            "qualities": base["qualities"],
            "consistency": _safe(_consistency, {"db_items": 0, "strm_without_db": 0, "db_without_strm": 0,
                                                 "arr_mirrored": 0, "arr_total": 0, "last_cleanup": None}),
        },
        "torbox": {
            "recent_streams": egress_estimate.recent(900),
            "last_429_at": (datetime.fromtimestamp(last_429, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                            if last_429 else None),
        },
    }


def get(force: bool = False) -> dict:
    now = time.monotonic()
    if not force and _cache["data"] is not None and now - _cache["ts"] < CACHE_TTL_SEC:
        return _cache["data"]
    with _lock:
        now = time.monotonic()
        if not force and _cache["data"] is not None and now - _cache["ts"] < CACHE_TTL_SEC:
            return _cache["data"]
        data = build()
        _cache["data"] = data
        _cache["ts"] = time.monotonic()
        return data
```

`base.get("movies_pending")` is the "upcoming" figure the old page called movies pending; keep the key name `upcoming` in the payload.

- [ ] **Step 6: The route**

In `app.py`, after `ui_api_stats`:

```python
@app.get("/ui/api/overview")
def ui_api_overview():
    """Everything the admin Overview reads from the database, in one call."""
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    return jsonify(overview.get())
```

Add `import overview` next to `import stats`.

- [ ] **Step 7: Run the tests, mutation-check, full suite, commit**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/test_overview.py -q -p no:cacheprovider` then the full suite.
Mutations: count proxied rows per row instead of per (token, day) (play test fails); make `_safe` re-raise (survives test fails); drop the `global _last_429_at` (429 test fails). Restore each.

```bash
git add overview.py db.py egress_estimate.py torbox.py app.py tests/test_overview.py
git commit -m "feat(overview): aggregated /ui/api/overview payload with plays, approvals, attention

Claude-Session: https://claude.ai/code/session_017Cc8iouqJoYhUcnJhhgapA"
```

---

### Task 2: StatusCell primitive, StatusStrip, ScraperStrip

**Files:**
- Modify: `frontend/src/api.ts` (type and helper)
- Create: `frontend/src/components/primitives/StatusCell.tsx`, `frontend/src/pages/admin/overview/format.ts`, `frontend/src/pages/admin/overview/StatusStrip.tsx`, `frontend/src/pages/admin/overview/ScraperStrip.tsx`
- Modify: `frontend/src/components/primitives/index.ts` (export `StatusCell`)
- Test: `frontend/src/pages/admin/overview/StatusStrip.test.tsx`, `frontend/src/pages/admin/overview/ScraperStrip.test.tsx`, `frontend/src/components/primitives/StatusCell.test.tsx`

**Interfaces:**
- Consumes: the payload from Task 1.
- Produces: `OverviewPayload` type and `api.overview()` in `api.ts`; `StatusCell` props `{ tone: 'ok' | 'warn' | 'danger' | 'off'; label: string; value: string; sub?: string; href?: string; linkLabel?: string }`; `StatusStrip` props `{ status: OverviewPayload['status'] | undefined; services: HealthService[] | undefined; loading: boolean; error: boolean }`; `ScraperStrip` props `{ scrapers: OverviewPayload['status']['scrapers'] }`; `format.ts` exports `formatGiB(bytes)`, `formatTB(bytes)`, `formatCountdown(sec)`, `formatLatency(ms)`, `relativeAge(sec)`.

- [ ] **Step 1: api.ts**

Add near `StatsOverview`:

```ts
/** GET /ui/api/overview, built by overview.py. Service pings and the TorBox list are separate calls. */
export type OverviewPayload = {
  status: {
    scrapers: { name: string; state: 'ok' | 'slow' | 'down' | 'unknown' | 'disabled'; latency_ms: number | null }[];
    torbox_adds: { uncached: number; cached: number; limit: number; resets_in_sec: number };
    failures_7d: number;
    queue: { retry: number; wanted: number };
    attention: number;
    approvals: { pending: number; oldest_age_sec: number | null };
  };
  activity: {
    plays: { today: number; week: number; titles_today: number; titles_week: number };
    requests_7d: { total: number; succeeded: number; failed: number; success_rate: number };
    egress: { proxied_bytes: number; estimated_bytes: number };
  };
  library: {
    movies: number; episodes: number; series: number; wanted: number; upcoming: number;
    qualities: Record<string, number>;
    consistency: {
      db_items: number; strm_without_db: number; db_without_strm: number;
      arr_mirrored: number; arr_total: number;
      last_cleanup: { ran_at: string; deleted: number } | null;
    };
  };
  torbox: { recent_streams: number; last_429_at: string | null };
};
```

and in `api`: `overview: () => http<OverviewPayload>('/ui/api/overview'),` next to `stats`.

- [ ] **Step 2: Write the failing tests**

`StatusCell.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import { StatusCell } from './StatusCell';

const wrap = (ui: React.ReactNode) => render(<MemoryRouter>{ui}</MemoryRouter>);

describe('StatusCell', () => {
  it('shows value, label and sub, and no link when green', () => {
    wrap(<StatusCell tone="ok" label="Queue" value="0" sub="retry queue empty" href="#library?view=queue" linkLabel="Open queue" />);
    expect(screen.getByText('Queue')).toBeInTheDocument();
    expect(screen.getByText('0')).toBeInTheDocument();
    expect(screen.getByText('retry queue empty')).toBeInTheDocument();
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('renders the link only when amber or red', () => {
    wrap(<StatusCell tone="warn" label="Attention" value="3" href="#library?view=attention" linkLabel="Open Library" />);
    expect(screen.getByRole('link', { name: 'Open Library' })).toHaveAttribute('href', expect.stringContaining('library?view=attention'));
  });

  it('exposes its tone for assistive tech', () => {
    wrap(<StatusCell tone="danger" label="Failures 7d" value="2" />);
    expect(screen.getByRole('group', { name: 'Failures 7d: problem' })).toBeInTheDocument();
  });
});
```

`StatusStrip.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import { StatusStrip } from './StatusStrip';
import type { OverviewPayload } from '../../../api';

const status: OverviewPayload['status'] = {
  scrapers: [
    { name: 'zilean', state: 'ok', latency_ms: 45 },
    { name: 'comet', state: 'down', latency_ms: null },
    { name: 'debridio', state: 'disabled', latency_ms: null },
  ],
  torbox_adds: { uncached: 3, cached: 41, limit: 60, resets_in_sec: 2520 },
  failures_7d: 2,
  queue: { retry: 0, wanted: 7 },
  attention: 3,
  approvals: { pending: 2, oldest_age_sec: 100_800 },
};
const services = [
  { name: 'TorBox', status: 'ok' }, { name: 'Jellyfin', status: 'ok' }, { name: 'Zilean', status: 'disabled' },
];

function renderIt(s = status, svc = services) {
  return render(<MemoryRouter><StatusStrip status={s} services={svc} loading={false} error={false} /></MemoryRouter>);
}

describe('StatusStrip', () => {
  it('renders the seven cells with the documented tones and links', () => {
    renderIt();
    expect(screen.getByRole('group', { name: 'Services: ok' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Scrapers: warning' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Scrapers' })).toHaveAttribute('href', expect.stringContaining('scrapers'));
    expect(screen.getByRole('group', { name: 'TorBox adds: ok' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Failures 7d: problem' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open failures' })).toHaveAttribute('href', expect.stringContaining('library?view=attention'));
    expect(screen.getByRole('group', { name: 'Queue: ok' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Library' })).toHaveAttribute('href', expect.stringContaining('library?view=attention'));
    expect(screen.getByRole('link', { name: 'Review requests' })).toHaveAttribute('href', expect.stringContaining('requests'));
    expect(screen.getByText('2 / 60')).toBeInTheDocument();
    expect(screen.getByText('oldest 1 d 4 h')).toBeInTheDocument();
  });

  it('counts only enabled services and marks a down service red', () => {
    renderIt(status, [{ name: 'TorBox', status: 'ok' }, { name: 'Jellyfin', status: 'down', note: 'HTTP 502' }]);
    expect(screen.getByRole('group', { name: 'Services: problem' })).toBeInTheDocument();
    expect(screen.getByText('1/2')).toBeInTheDocument();
    expect(screen.getByText('Jellyfin down')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open Settings' })).toBeInTheDocument();
  });

  it('turns TorBox adds amber from 45 uncached and queue amber with retries', () => {
    renderIt({ ...status, torbox_adds: { ...status.torbox_adds, uncached: 45 }, queue: { retry: 2, wanted: 1 } });
    expect(screen.getByRole('group', { name: 'TorBox adds: warning' })).toBeInTheDocument();
    expect(screen.getByRole('group', { name: 'Queue: warning' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open queue' })).toHaveAttribute('href', expect.stringContaining('library?view=queue'));
  });

  it('shows unavailable cells when the payload failed', () => {
    render(<MemoryRouter><StatusStrip status={undefined} services={services} loading={false} error /></MemoryRouter>);
    expect(screen.getAllByText('unavailable').length).toBeGreaterThanOrEqual(5);
  });
});
```

The `2 / 60` in the first test is wrong on purpose to make you read the component: the cell value is `3 / 60` for `uncached: 3`; fix the expectation to `3 / 60` before running.

`ScraperStrip.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { ScraperStrip } from './ScraperStrip';

describe('ScraperStrip', () => {
  it('renders one entry per scraper with latency, state and dimmed disabled ones', () => {
    render(<ScraperStrip scrapers={[
      { name: 'zilean', state: 'ok', latency_ms: 45 },
      { name: 'mediafusion', state: 'slow', latency_ms: 1840 },
      { name: 'comet', state: 'down', latency_ms: null },
      { name: 'debridio', state: 'disabled', latency_ms: null },
    ]} />);
    expect(screen.getByText('45 ms')).toBeInTheDocument();
    expect(screen.getByText('1.8 s')).toBeInTheDocument();
    expect(screen.getByText('down')).toBeInTheDocument();
    expect(screen.getByText('disabled')).toBeInTheDocument();
    expect(screen.getByLabelText('comet: down')).toBeInTheDocument();
    expect(screen.getByLabelText('debridio: disabled')).toHaveClass('opacity-50');
  });
});
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/admin/overview src/components/primitives/StatusCell.test.tsx`
Expected: FAIL, modules not found.

- [ ] **Step 4: format.ts**

```ts
const GIB = 1024 ** 3;

export function formatGiB(bytes: number): string {
  return `${(bytes / GIB).toFixed(1)} GiB`;
}

export function formatTB(bytes: number): string {
  return `${(bytes / 1e12).toFixed(2)} TB`;
}

/** "42 min" under an hour, "1 h 05 min" above it. */
export function formatCountdown(sec: number): string {
  if (sec <= 0) return 'now';
  const m = Math.floor(sec / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')} min`;
}

export function formatLatency(ms: number | null): string {
  if (ms == null) return '-';
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.round(ms)} ms`;
}

/** "3 min", "5 h", "1 d 4 h" from an age in seconds. */
export function relativeAge(sec: number): string {
  if (sec < 3600) return `${Math.max(1, Math.floor(sec / 60))} min`;
  if (sec < 86400) return `${Math.floor(sec / 3600)} h`;
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  return h ? `${d} d ${h} h` : `${d} d`;
}
```

Move the existing `formatGiB` and `formatCountdown` out of `Overview.tsx` in Task 4; until then the two copies coexist.

- [ ] **Step 5: StatusCell.tsx**

```tsx
import { Link } from 'react-router-dom';
import { StatusDot } from './StatusDot';

export type StatusTone = 'ok' | 'warn' | 'danger' | 'off';

const TONE_LABEL: Record<StatusTone, string> = { ok: 'ok', warn: 'warning', danger: 'problem', off: 'unavailable' };
const BORDER: Record<StatusTone, string> = {
  ok: 'border-border', warn: 'border-warn/40', danger: 'border-danger/40', off: 'border-border',
};
const GLOW: Record<StatusTone, string> = {
  ok: '', off: '',
  warn: 'rgba(198,178,83,0.4)', danger: 'rgba(209,71,71,0.4)',
};

/** One cell of the Overview status strip: dot, label, number, one reason
 *  line, and a link that renders only when something needs attention. */
export function StatusCell({ tone, label, value, sub, href, linkLabel }: {
  tone: StatusTone; label: string; value: string; sub?: string; href?: string; linkLabel?: string;
}) {
  const alert = tone === 'warn' || tone === 'danger';
  return (
    <div role="group" aria-label={`${label}: ${TONE_LABEL[tone]}`}
      className={`relative flex min-h-[96px] flex-col gap-1.5 overflow-hidden rounded-xl border bg-card px-3.5 py-3 ${BORDER[tone]}`}>
      {alert && (
        <span aria-hidden="true" className="pointer-events-none absolute -right-5 -top-8 h-20 w-28 rounded-full opacity-50 blur-[38px]"
          style={{ background: GLOW[tone] }} />
      )}
      <div className="relative flex items-center gap-2 text-xs text-muted">
        {tone === 'off' ? <span className="block h-[7px] w-[7px] rounded-full bg-white/30" /> : <StatusDot tone={tone} />}
        {label}
      </div>
      <div className="relative font-mono text-xl font-medium text-body">{value}</div>
      {sub && <div className="relative text-[11px] text-muted">{sub}</div>}
      {alert && href && linkLabel && (
        <Link to={{ hash: href.replace(/^#/, '') }} className="relative mt-auto text-[11px] text-accent-light hover:underline">{linkLabel}</Link>
      )}
    </div>
  );
}
```

Check how other pages build hash links (`Link to={{ hash: 'filter-rules' }}` in `customCards.tsx`): a hash with a query, `library?view=attention`, must survive; `AdminLayout` splits the hash on `?`, so pass the hash string as is. Export `StatusCell` and `StatusTone` from `primitives/index.ts`.

- [ ] **Step 6: StatusStrip.tsx and ScraperStrip.tsx**

```tsx
import type { HealthService, OverviewPayload } from '../../../api';
import { StatusCell } from '../../../components/primitives';
import type { StatusTone } from '../../../components/primitives';
import { relativeAge } from './format';

const ADD_WARN_AT = 45;

export function StatusStrip({ status, services, loading, error }: {
  status: OverviewPayload['status'] | undefined;
  services: HealthService[] | undefined;
  loading: boolean;
  error: boolean;
}) {
  const off = error || (!loading && !status);
  const v = (s: string) => (loading ? '-' : off ? 'unavailable' : s);
  const tone = (t: StatusTone): StatusTone => (loading || off ? 'off' : t);

  const enabled = (services ?? []).filter((s) => s.status !== 'disabled');
  const down = enabled.filter((s) => s.status !== 'ok');
  const scrapersOn = (status?.scrapers ?? []).filter((s) => s.state !== 'disabled');
  const scrapersDown = scrapersOn.filter((s) => s.state === 'down');
  const adds = status?.torbox_adds;
  const q = status?.queue;
  const approvals = status?.approvals;

  return (
    <div className="grid gap-2" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
      <StatusCell tone={services === undefined ? 'off' : down.length ? 'danger' : 'ok'} label="Services"
        value={services === undefined ? 'unavailable' : `${enabled.length - down.length}/${enabled.length}`}
        sub={services === undefined ? undefined : down.length ? down.map((s) => `${s.name} down`).join(', ') : enabled.map((s) => s.name).join(', ')}
        href="#settings" linkLabel="Open Settings" />
      <StatusCell tone={tone(scrapersDown.length ? 'warn' : 'ok')} label="Scrapers"
        value={v(`${scrapersOn.length - scrapersDown.length}/${scrapersOn.length}`)}
        sub={status && scrapersDown.length ? `${scrapersDown.map((s) => s.name).join(', ')} down` : undefined}
        href="#scrapers" linkLabel="Open Scrapers" />
      <StatusCell tone={tone(adds && adds.uncached >= ADD_WARN_AT ? 'warn' : 'ok')} label="TorBox adds"
        value={v(adds ? `${adds.uncached} / ${adds.limit}` : '-')}
        sub={adds ? `uncached this hour, ${adds.cached} cached` : undefined}
        href="#settings" linkLabel="Open Settings" />
      <StatusCell tone={tone(status && status.failures_7d > 0 ? 'danger' : 'ok')} label="Failures 7d"
        value={v(String(status?.failures_7d ?? 0))}
        href="#library?view=attention" linkLabel="Open failures" />
      <StatusCell tone={tone(q && q.retry > 0 ? 'warn' : 'ok')} label="Queue"
        value={v(String((q?.retry ?? 0) + (q?.wanted ?? 0)))}
        sub={q ? (q.retry ? `${q.retry} retrying, ${q.wanted} wanted` : 'retry queue empty') : undefined}
        href="#library?view=queue" linkLabel="Open queue" />
      <StatusCell tone={tone(status && status.attention > 0 ? 'warn' : 'ok')} label="Attention"
        value={v(String(status?.attention ?? 0))}
        sub={status ? 'degraded or stuck titles' : undefined}
        href="#library?view=attention" linkLabel="Open Library" />
      <StatusCell tone={tone(approvals && approvals.pending > 0 ? 'warn' : 'ok')} label="Approvals"
        value={v(String(approvals?.pending ?? 0))}
        sub={approvals?.oldest_age_sec != null ? `oldest ${relativeAge(approvals.oldest_age_sec)}` : approvals ? 'nothing waiting' : undefined}
        href="#requests" linkLabel="Review requests" />
    </div>
  );
}
```

`ScraperStrip.tsx`:

```tsx
import type { OverviewPayload } from '../../../api';
import { StatusDot } from '../../../components/primitives';
import { formatLatency } from './format';

const TONE = { ok: 'ok', slow: 'warn', down: 'danger' } as const;

export function ScraperStrip({ scrapers }: { scrapers: OverviewPayload['status']['scrapers'] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs" aria-label="Scraper state">
      {scrapers.map((s) => {
        const tone = s.state in TONE ? TONE[s.state as keyof typeof TONE] : null;
        const dim = s.state === 'disabled' || s.state === 'unknown';
        return (
          <span key={s.name} aria-label={`${s.name}: ${s.state}`} className={`inline-flex items-center gap-1.5 ${dim ? 'opacity-50' : ''}`}>
            {tone ? <StatusDot tone={tone} /> : <span className="block h-[7px] w-[7px] rounded-full bg-white/30" />}
            <span className="text-body">{s.name}</span>
            <span className="font-mono text-[11px] text-muted">
              {s.state === 'ok' || s.state === 'slow' ? formatLatency(s.latency_ms) : s.state}
            </span>
          </span>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 7: Run, mutation-check, commit**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/pages/admin/overview src/components/primitives/StatusCell.test.tsx`
Mutations: render the link regardless of tone (StatusCell test fails); change `ADD_WARN_AT` to 46 (strip test fails). Restore.

```bash
git add frontend/src/api.ts frontend/src/components/primitives/StatusCell.tsx frontend/src/components/primitives/StatusCell.test.tsx frontend/src/components/primitives/index.ts frontend/src/pages/admin/overview/format.ts frontend/src/pages/admin/overview/StatusStrip.tsx frontend/src/pages/admin/overview/StatusStrip.test.tsx frontend/src/pages/admin/overview/ScraperStrip.tsx frontend/src/pages/admin/overview/ScraperStrip.test.tsx
git commit -m "feat(overview): status strip and scraper strip with the StatusCell primitive

Claude-Session: https://claude.ai/code/session_017Cc8iouqJoYhUcnJhhgapA"
```

---

### Task 3: ActivityBand and LibraryBand

**Files:**
- Create: `frontend/src/pages/admin/overview/ActivityBand.tsx`, `LibraryBand.tsx`
- Test: `ActivityBand.test.tsx`, `LibraryBand.test.tsx` alongside

**Interfaces:**
- Consumes: `OverviewPayload` (Task 2), `ActivityEvent`, `TorBoxUsage` from `api.ts`, `formatTB`, `formatGiB` from `format.ts`, `Card`, `StatTile` from primitives.
- Produces: `ActivityBand` props `{ activity: OverviewPayload['activity'] | undefined; events: ActivityEvent[] | undefined; loading: boolean }`; `LibraryBand` props `{ library: OverviewPayload['library'] | undefined; torbox: TorBoxUsage | undefined; loading: boolean }`; `eventPill(event: string): { label: string; tone: 'ok' | 'warn' | 'danger' | 'neutral' } | null` exported from `ActivityBand.tsx`.

- [ ] **Step 1: Write the failing tests**

`ActivityBand.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import { ActivityBand, eventPill } from './ActivityBand';

const activity = {
  plays: { today: 4, week: 23, titles_today: 3, titles_week: 17 },
  requests_7d: { total: 11, succeeded: 9, failed: 2, success_rate: 81.8 },
  egress: { proxied_bytes: 210_000_000_000, estimated_bytes: 1_630_000_000_000 },
};
const events = [
  { id: 1, created_at: '2026-09-08 10:41:00', event: 'played', title: 'Severance S02E04', message: 'by anna', success: true },
  { id: 2, created_at: '2026-09-08 10:05:00', event: 'swapped', title: 'Heat (1995)', message: '1080p to 2160p', success: true },
  { id: 3, created_at: '2026-09-08 08:30:00', event: 'wanted', title: 'Dune Part Two', message: 'no cached release', success: false },
  { id: 4, created_at: '2026-09-08 07:58:00', event: 'mystery', title: 'X', message: '', success: true },
];

describe('ActivityBand', () => {
  it('renders the five tiles with the documented formats', () => {
    render(<MemoryRouter><ActivityBand activity={activity} events={events} loading={false} /></MemoryRouter>);
    expect(screen.getByText('4')).toBeInTheDocument();
    expect(screen.getByText('3 titles')).toBeInTheDocument();
    expect(screen.getByText('23')).toBeInTheDocument();
    expect(screen.getByText('17 titles')).toBeInTheDocument();
    expect(screen.getByText('11')).toBeInTheDocument();
    expect(screen.getByText('9 ok, 2 failed')).toBeInTheDocument();
    expect(screen.getByText('82%')).toBeInTheDocument();
    expect(screen.getByText('1.84 TB')).toBeInTheDocument();
    expect(screen.getByText('0.21 TB proxied, 1.63 TB estimated')).toBeInTheDocument();
  });

  it('renders the feed with pills by event family and a link to the logs', () => {
    render(<MemoryRouter><ActivityBand activity={activity} events={events} loading={false} /></MemoryRouter>);
    expect(screen.getByText('Severance S02E04')).toBeInTheDocument();
    expect(screen.getByText('play')).toBeInTheDocument();
    expect(screen.getByText('swap')).toBeInTheDocument();
    expect(screen.getByText('wanted')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'All activity' })).toHaveAttribute('href', expect.stringContaining('logs'));
  });

  it('maps events to pills and leaves unknown events without one', () => {
    expect(eventPill('played')).toEqual({ label: 'play', tone: 'ok' });
    expect(eventPill('upgraded')).toEqual({ label: 'upgrade', tone: 'neutral' });
    expect(eventPill('failed')).toEqual({ label: 'failed', tone: 'danger' });
    expect(eventPill('mystery')).toBeNull();
  });
});
```

`LibraryBand.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import { LibraryBand } from './LibraryBand';

const library = {
  movies: 312, episodes: 1940, series: 64, wanted: 7, upcoming: 2,
  qualities: { '2160p': 38, '1080p': 55, '720p': 6 },
  consistency: { db_items: 2252, strm_without_db: 1, db_without_strm: 0, arr_mirrored: 312, arr_total: 312,
    last_cleanup: { ran_at: '2026-09-08 03:00:00', deleted: 0 } },
};
const torbox = { usage: { torrent_count: 128, total_bytes: 3_400_000_000_000, total_gb: 3400, states: {} }, plan: 'Pro' };

describe('LibraryBand', () => {
  it('renders size tiles, quality shares and consistency', () => {
    render(<MemoryRouter><LibraryBand library={library} torbox={torbox} loading={false} /></MemoryRouter>);
    expect(screen.getByText('312')).toBeInTheDocument();
    expect(screen.getByText('1,940')).toBeInTheDocument();
    expect(screen.getByText('64 series')).toBeInTheDocument();
    expect(screen.getByText('2 upcoming')).toBeInTheDocument();
    expect(screen.getByText('128 torrents')).toBeInTheDocument();
    expect(screen.getByText('56%')).toBeInTheDocument();  // 55 of 99, rounded
    expect(screen.getByText('312/312')).toBeInTheDocument();
    expect(screen.getByText('1')).toHaveClass('text-warn');
    expect(screen.getByRole('link', { name: 'Run integrity check' })).toHaveAttribute('href', expect.stringContaining('maintenance'));
  });

  it('shows the TorBox tile as unavailable when the list failed', () => {
    render(<MemoryRouter><LibraryBand library={library} torbox={undefined} loading={false} /></MemoryRouter>);
    expect(screen.getByText('unavailable')).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/admin/overview`. Expected: FAIL, modules not found.

- [ ] **Step 3: ActivityBand.tsx**

```tsx
import { Link } from 'react-router-dom';
import type { ActivityEvent, OverviewPayload } from '../../../api';
import { Card, StatTile } from '../../../components/primitives';
import { formatTB } from './format';

type PillTone = 'ok' | 'warn' | 'danger' | 'neutral';
const PILLS: Record<string, { label: string; tone: PillTone }> = {
  played: { label: 'play', tone: 'ok' },
  swapped: { label: 'swap', tone: 'neutral' },
  upgraded: { label: 'upgrade', tone: 'neutral' },
  added: { label: 'request', tone: 'ok' },
  requested: { label: 'request', tone: 'ok' },
  approved: { label: 'request', tone: 'ok' },
  wanted: { label: 'wanted', tone: 'warn' },
  failed: { label: 'failed', tone: 'danger' },
  scraper: { label: 'scraper', tone: 'danger' },
  cleanup: { label: 'job', tone: 'neutral' },
  purged: { label: 'removed', tone: 'neutral' },
};
const PILL_CLASS: Record<PillTone, string> = {
  ok: 'text-ok border-ok/40', warn: 'text-warn border-warn/40', danger: 'text-danger border-danger/40', neutral: 'text-muted border-border',
};

export function eventPill(event: string) {
  return PILLS[event] ?? null;
}

function clock(ts: string): string {
  const m = ts.match(/(\d{2}):(\d{2})/);
  return m ? `${m[1]}:${m[2]}` : ts;
}

export function ActivityBand({ activity, events, loading }: {
  activity: OverviewPayload['activity'] | undefined; events: ActivityEvent[] | undefined; loading: boolean;
}) {
  const p = activity?.plays;
  const r = activity?.requests_7d;
  const e = activity?.egress;
  const v = (s: string) => (loading || !activity ? '-' : s);
  return (
    <div className="grid gap-3 lg:grid-cols-[1.1fr_1fr]">
      <Card>
        <div className="mb-3 text-sm font-semibold text-body">Watching and requesting</div>
        <div className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))' }}>
          <StatTile value={v(String(p?.today ?? 0))} label="Plays today" sub={p ? `${p.titles_today} titles` : undefined} />
          <StatTile value={v(String(p?.week ?? 0))} label="Plays this week" sub={p ? `${p.titles_week} titles` : undefined} />
          <StatTile value={v(String(r?.total ?? 0))} label="Requests 7d" sub={r ? `${r.succeeded} ok, ${r.failed} failed` : undefined}
            glow={r && r.failed > 0 ? 'danger' : undefined} />
          <StatTile value={v(r ? `${Math.round(r.success_rate)}%` : '-')} label="Success rate 7d" glow="ok" />
          <StatTile value={v(e ? formatTB(e.proxied_bytes + e.estimated_bytes) : '-')} label="Egress this month"
            sub={e ? `${formatTB(e.proxied_bytes)} proxied, ${formatTB(e.estimated_bytes)} estimated` : undefined} />
        </div>
      </Card>
      <Card>
        <div className="mb-3 text-sm font-semibold text-body">Recent activity</div>
        {events === undefined ? (
          <p className="text-xs text-muted">Loading…</p>
        ) : events.length === 0 ? (
          <p className="text-xs text-muted">No activity yet</p>
        ) : (
          <div className="divide-y divide-border text-xs">
            {events.slice(0, 8).map((ev) => {
              const pill = eventPill(ev.event);
              return (
                <div key={ev.id} className="grid grid-cols-[52px_1fr_auto] items-baseline gap-2.5 py-1.5 first:pt-0">
                  <span className="font-mono text-[11px] text-white/30">{clock(ev.created_at)}</span>
                  <span className="min-w-0 truncate text-muted">
                    <span className="font-medium text-body">{ev.title}</span>{ev.message ? ` ${ev.message}` : ''}
                  </span>
                  {pill && <span className={`rounded-full border px-1.5 py-px text-[10px] uppercase tracking-wide ${PILL_CLASS[pill.tone]}`}>{pill.label}</span>}
                </div>
              );
            })}
          </div>
        )}
        <Link to={{ hash: 'logs' }} className="mt-3 block text-[11px] text-accent-light hover:underline">All activity</Link>
      </Card>
    </div>
  );
}
```

Read `db.log_activity` call sites (`grep -rn 'log_activity("' *.py`) and extend `PILLS` with every event name that exists (the map above is the minimum); keep unknown names without a pill.

- [ ] **Step 4: LibraryBand.tsx**

```tsx
import { Link } from 'react-router-dom';
import type { OverviewPayload, TorBoxUsage } from '../../../api';
import { Card, StatTile } from '../../../components/primitives';
import { formatGiB } from './format';

const nf = new Intl.NumberFormat('en-US');

export function LibraryBand({ library, torbox, loading }: {
  library: OverviewPayload['library'] | undefined; torbox: TorBoxUsage | undefined; loading: boolean;
}) {
  const v = (s: string) => (loading || !library ? '-' : s);
  const q = Object.entries(library?.qualities ?? {}).sort((a, b) => b[1] - a[1]);
  const total = q.reduce((s, [, n]) => s + n, 0) || 1;
  const c = library?.consistency;
  return (
    <div className="grid gap-3 lg:grid-cols-3">
      <Card>
        <div className="mb-3 text-sm font-semibold text-body">Size</div>
        <div className="grid grid-cols-2 gap-2.5">
          <StatTile value={v(nf.format(library?.movies ?? 0))} label="Movies" />
          <StatTile value={v(nf.format(library?.episodes ?? 0))} label="Episodes" sub={library ? `${library.series} series` : undefined} />
          <StatTile value={v(String(library?.wanted ?? 0))} label="Wanted" sub={library ? `${library.upcoming} upcoming` : undefined} />
          <StatTile value={torbox ? formatGiB(torbox.usage.total_bytes) : 'unavailable'} label="On TorBox"
            sub={torbox ? `${torbox.usage.torrent_count} torrents` : undefined} />
        </div>
      </Card>
      <Card>
        <div className="mb-3 text-sm font-semibold text-body">Quality of what landed</div>
        {q.length === 0 ? <p className="text-xs text-muted">No data yet</p> : (
          <div className="space-y-1.5 text-xs">
            {q.map(([label, n]) => (
              <div key={label} className="grid grid-cols-[56px_1fr_40px] items-center gap-2.5">
                <span className="text-muted">{label}</span>
                <div className="h-1.5 overflow-hidden rounded-full bg-white/5">
                  <div className="h-full rounded-full bg-accent" style={{ width: `${Math.round((100 * n) / total)}%` }} />
                </div>
                <span className="text-right font-mono text-body">{Math.round((100 * n) / total)}%</span>
              </div>
            ))}
          </div>
        )}
        <p className="mt-2 text-[11px] text-white/30">Requests that succeeded, by resolution.</p>
      </Card>
      <Card>
        <div className="mb-3 text-sm font-semibold text-body">Consistency</div>
        {!c ? <p className="text-xs text-muted">{loading ? 'Loading…' : 'unavailable'}</p> : (
          <div className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 text-xs">
            <span className="text-muted">DB items</span><span className="text-right font-mono text-body">{nf.format(c.db_items)}</span>
            <span className="text-muted">strm without DB row</span><span className={`text-right font-mono ${c.strm_without_db > 0 ? 'text-warn' : 'text-body'}`}>{c.strm_without_db}</span>
            <span className="text-muted">DB row without strm</span><span className={`text-right font-mono ${c.db_without_strm > 0 ? 'text-warn' : 'text-body'}`}>{c.db_without_strm}</span>
            <span className="text-muted">Arr mirror</span><span className="text-right font-mono text-body">{c.arr_mirrored}/{c.arr_total}</span>
            <span className="text-muted">Last cleanup</span>
            <span className="text-right font-mono text-body">{c.last_cleanup ? `${c.last_cleanup.ran_at.slice(11, 16)}, ${c.last_cleanup.deleted} removed` : 'never'}</span>
          </div>
        )}
        <Link to={{ hash: 'maintenance' }} className="mt-3 block text-[11px] text-accent-light hover:underline">Run integrity check</Link>
      </Card>
    </div>
  );
}
```

The `text-warn` assertion in the test targets the `1` cell; if `getByText('1')` is ambiguous with another "1" on the band, scope it with `within` on the Consistency card.

- [ ] **Step 5: Run, mutation-check, commit**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/pages/admin/overview`
Mutations: `eventPill` returns a pill for unknown events (test fails); the quality percentage uses `n` instead of `100*n/total` (56% test fails). Restore.

```bash
git add frontend/src/pages/admin/overview/ActivityBand.tsx frontend/src/pages/admin/overview/ActivityBand.test.tsx frontend/src/pages/admin/overview/LibraryBand.tsx frontend/src/pages/admin/overview/LibraryBand.test.tsx
git commit -m "feat(overview): activity and library bands

Claude-Session: https://claude.ai/code/session_017Cc8iouqJoYhUcnJhhgapA"
```

---

### Task 4: TorboxCard, ReferenceSection, page composition, bundle

**Files:**
- Create: `frontend/src/pages/admin/overview/TorboxCard.tsx`, `ReferenceSection.tsx`, `reference/MetricsPanel.tsx`, `reference/EndpointsPanel.tsx`, `reference/FoldersPanel.tsx`
- Modify: `frontend/src/pages/admin/Overview.tsx` (rewrite as composition), `frontend/src/pages/admin/Overview.test.tsx` (rewrite)
- Test: `TorboxCard.test.tsx`, `ReferenceSection.test.tsx`
- Build: `static/app/` (commit)

**Interfaces:**
- Consumes: Tasks 2 and 3 components and `format.ts`; `api.torboxQuota`, `api.torboxUsage`, `api.health`, `api.webhookSecret`, `api.metricsSummary`, `api.storage`, `api.activity`, `api.overview`.
- Produces: `TorboxCard` props `{ adds: OverviewPayload['status']['torbox_adds'] | undefined; byReason: Record<string, number> | undefined; usage: TorBoxUsage | undefined; streamFront: boolean | undefined; recentStreams: number | undefined; last429At: string | null | undefined; idleMinutes: number | null }`; `ReferenceSection` props `{ id: 'metrics' | 'endpoints' | 'folders'; title: string; hint: string; children: (open: boolean) => React.ReactNode }`.

- [ ] **Step 1: Write the failing tests**

`ReferenceSection.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, beforeEach } from 'vitest';
import { ReferenceSection } from './ReferenceSection';

describe('ReferenceSection', () => {
  beforeEach(() => localStorage.clear());

  it('is closed by default and renders its body only once opened', async () => {
    let opened = false;
    render(<ReferenceSection id="metrics" title="Metrics, 30 days" hint="latency">{(open) => { opened = open; return <p>body</p>; }}</ReferenceSection>);
    expect(opened).toBe(false);
    await userEvent.click(screen.getByText('Metrics, 30 days'));
    expect(opened).toBe(true);
    expect(localStorage.getItem('mycelium.overview.metrics')).toBe('1');
  });

  it('remembers an open state', () => {
    localStorage.setItem('mycelium.overview.folders', '1');
    let opened = false;
    render(<ReferenceSection id="folders" title="Top folders" hint="">{(open) => { opened = open; return null; }}</ReferenceSection>);
    expect(opened).toBe(true);
  });
});
```

`TorboxCard.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { TorboxCard } from './TorboxCard';

const usage = { usage: { torrent_count: 128, total_bytes: 3_400_000_000_000, total_gb: 3400, states: { completed: 121, downloading: 1, stalled: 6 } }, plan: 'Pro' };

describe('TorboxCard', () => {
  it('merges budget, library and streaming into one card', () => {
    render(<TorboxCard adds={{ uncached: 3, cached: 41, limit: 60, resets_in_sec: 2520 }} byReason={{ 'catbox-search': 2, processor: 1 }}
      usage={usage} streamFront recentStreams={2} last429At={null} idleMinutes={90} />);
    expect(screen.getByText('3 / 60')).toBeInTheDocument();
    expect(screen.getByText('41 cached adds this hour, not limited by TorBox. Resets in 42 min.')).toBeInTheDocument();
    expect(screen.getByText('catbox-search')).toBeInTheDocument();
    expect(screen.getByText('128')).toBeInTheDocument();
    expect(screen.getByText('Pro')).toBeInTheDocument();
    expect(screen.getByText('Stalled')).toBeInTheDocument();
    expect(screen.getByText('Go')).toBeInTheDocument();
    expect(screen.getByText('after 90 min')).toBeInTheDocument();
    expect(screen.getByText('none since start')).toBeInTheDocument();
  });

  it('shows the last 429 as a relative time and the Flask front when the Go front is off', () => {
    const t = new Date(Date.now() - 3 * 86400 * 1000).toISOString().replace(/\.\d+Z$/, 'Z');
    render(<TorboxCard adds={undefined} byReason={undefined} usage={undefined} streamFront={false} recentStreams={0} last429At={t} idleMinutes={null} />);
    expect(screen.getByText('3 d ago')).toBeInTheDocument();
    expect(screen.getByText('Flask')).toBeInTheDocument();
    expect(screen.getAllByText('unavailable').length).toBeGreaterThanOrEqual(1);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/admin/overview`. Expected: modules not found.

- [ ] **Step 3: ReferenceSection.tsx**

```tsx
import { useState } from 'react';

const KEY = 'mycelium.overview.';

function readOpen(id: string): boolean {
  try { return localStorage.getItem(KEY + id) === '1'; } catch { return false; }
}

/** A collapsed reference block: closed by default, state remembered per id,
 *  body rendered through a function so its query can be enabled on open. */
export function ReferenceSection({ id, title, hint, children }: {
  id: 'metrics' | 'endpoints' | 'folders'; title: string; hint: string; children: (open: boolean) => React.ReactNode;
}) {
  const [open, setOpen] = useState(() => readOpen(id));
  const toggle = (next: boolean) => {
    setOpen(next);
    try { localStorage.setItem(KEY + id, next ? '1' : '0'); } catch { /* storage unavailable */ }
  };
  return (
    <details open={open} onToggle={(e) => toggle((e.currentTarget as HTMLDetailsElement).open)}
      className="rounded-xl border border-border bg-card">
      <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-sm font-semibold text-body">
        {title}<span className="text-xs font-normal text-white/30">{hint}</span>
      </summary>
      <div className="px-4 pb-4">{children(open)}</div>
    </details>
  );
}
```

jsdom fires `toggle` on `details` when the `open` attribute changes through a click on the summary; if the click test does not flip the state in jsdom, handle `onClick` on the summary with `e.preventDefault()` and `toggle(!open)` instead, and keep the `open` attribute controlled.

- [ ] **Step 4: TorboxCard.tsx**

```tsx
import type { OverviewPayload, TorBoxUsage } from '../../../api';
import { Card } from '../../../components/primitives';
import { formatCountdown, formatGiB, relativeAge } from './format';

function Row({ k, v, tone }: { k: string; v: string; tone?: 'warn' | 'ok' }) {
  return (<><span className="text-muted">{k}</span><span className={`text-right font-mono ${tone === 'warn' ? 'text-warn' : tone === 'ok' ? 'text-ok' : 'text-body'}`}>{v}</span></>);
}

function ago(iso: string): string {
  const sec = Math.max(0, Math.floor((Date.now() - Date.parse(iso)) / 1000));
  return `${relativeAge(sec)} ago`;
}

const STATE_LABEL: Record<string, string> = { completed: 'Ready', cached: 'Ready', downloading: 'Downloading', stalled: 'Stalled', meta_dl: 'Fetching metadata', uploading: 'Seeding', paused: 'Paused' };

export function TorboxCard({ adds, byReason, usage, streamFront, recentStreams, last429At, idleMinutes }: {
  adds: OverviewPayload['status']['torbox_adds'] | undefined; byReason: Record<string, number> | undefined;
  usage: TorBoxUsage | undefined; streamFront: boolean | undefined; recentStreams: number | undefined;
  last429At: string | null | undefined; idleMinutes: number | null;
}) {
  const states = Object.entries(usage?.usage.states ?? {}).sort((a, b) => b[1] - a[1]);
  return (
    <Card>
      <div className="mb-3 text-sm font-semibold text-body">TorBox</div>
      <div className="grid gap-5 text-xs lg:grid-cols-3">
        <div>
          {adds ? (
            <>
              <div className="mb-2 flex items-baseline justify-between"><span className="text-muted">Uncached adds this hour</span><span className="font-mono text-body">{adds.uncached} / {adds.limit}</span></div>
              <div className="h-1.5 overflow-hidden rounded-full bg-white/5"><div className="h-full rounded-full bg-accent" style={{ width: `${Math.min(100, Math.round((100 * adds.uncached) / (adds.limit || 1)))}%` }} /></div>
              <p className="mt-1.5 text-[11px] text-white/30">{adds.cached} cached adds this hour, not limited by TorBox. Resets in {formatCountdown(adds.resets_in_sec)}.</p>
              {byReason && Object.keys(byReason).length > 0 && (
                <div className="mt-2.5 grid grid-cols-[1fr_auto] gap-x-4 gap-y-1">
                  {Object.entries(byReason).sort((a, b) => b[1] - a[1]).map(([k, n]) => <Row key={k} k={k} v={String(n)} />)}
                </div>
              )}
            </>
          ) : <p className="text-muted">unavailable</p>}
        </div>
        <div className="grid grid-cols-[1fr_auto] content-start gap-x-4 gap-y-1">
          {usage ? (
            <>
              <Row k="Torrents" v={String(usage.usage.torrent_count)} />
              <Row k="Total size" v={formatGiB(usage.usage.total_bytes)} />
              {usage.plan && <Row k="Plan" v={usage.plan} />}
              {states.map(([s, n]) => <Row key={s} k={STATE_LABEL[s] ?? s} v={String(n)} tone={s === 'stalled' ? 'warn' : undefined} />)}
            </>
          ) : <span className="text-muted">unavailable</span>}
        </div>
        <div className="grid grid-cols-[1fr_auto] content-start gap-x-4 gap-y-1">
          <Row k="Stream front" v={streamFront === undefined ? '-' : streamFront ? 'Go' : 'Flask'} tone={streamFront ? 'ok' : undefined} />
          <Row k="Streamed in last 15 min" v={recentStreams === undefined ? '-' : String(recentStreams)} />
          <Row k="Idle cleanup" v={idleMinutes ? `after ${idleMinutes} min` : '-'} />
          <Row k="Last 429" v={last429At === undefined ? '-' : last429At ? ago(last429At) : 'none since start'} />
        </div>
      </div>
    </Card>
  );
}
```

`idleMinutes` comes from the settings schema payload? No: the Overview does not load settings. Pass `null` from the page for now and show "-" (the spec's mockup line "after 90 min" is only reachable when a value is available); do not add a settings fetch to the Overview. Keep the prop so a later task can feed it.

- [ ] **Step 5: Reference panels**

Move the three card bodies out of the current `Overview.tsx` verbatim into `reference/MetricsPanel.tsx` (props: `metrics: MetricsSummary | undefined; loading: boolean`), `reference/EndpointsPanel.tsx` (props: `secret: { secret: string } | undefined; loading: boolean; error: boolean`, including `EndpointRow`), and `reference/FoldersPanel.tsx` (props: `folders: StorageFolder[] | undefined; loading: boolean`). The `EndpointsPanel` copy button stays. Add one line under the endpoints: "Also on Settings, where the secret can be rotated." with `<Link to={{ hash: 'settings' }}>`.

- [ ] **Step 6: Overview.tsx composition**

```tsx
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api';
import { StatusStrip } from './overview/StatusStrip';
import { ScraperStrip } from './overview/ScraperStrip';
import { ActivityBand } from './overview/ActivityBand';
import { LibraryBand } from './overview/LibraryBand';
import { TorboxCard } from './overview/TorboxCard';
import { ReferenceSection } from './overview/ReferenceSection';
import { MetricsPanel } from './overview/reference/MetricsPanel';
import { EndpointsPanel } from './overview/reference/EndpointsPanel';
import { FoldersPanel } from './overview/reference/FoldersPanel';

function Band({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3" aria-label={title}>
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="text-xs font-semibold uppercase tracking-[0.08em] text-muted">{title}</h2>
        {hint && <span className="text-xs text-white/30">{hint}</span>}
      </div>
      {children}
    </section>
  );
}

export default function Overview() {
  const overviewQ = useQuery({ queryKey: ['admin-overview'], queryFn: api.overview, refetchInterval: 30_000 });
  const healthQ = useQuery({ queryKey: ['admin-health'], queryFn: api.health, refetchInterval: 30_000 });
  const activityQ = useQuery({ queryKey: ['admin-activity'], queryFn: api.activity, refetchInterval: 60_000 });
  const torboxUsageQ = useQuery({ queryKey: ['admin-torbox-usage'], queryFn: api.torboxUsage, retry: false });
  const quotaQ = useQuery({ queryKey: ['admin-torbox-quota'], queryFn: api.torboxQuota, retry: false });
  const o = overviewQ.data;

  return (
    <div className="space-y-7">
      <Band title="Right now" hint="refreshes every 30 s; quiet rows stay quiet">
        <StatusStrip status={o?.status} services={healthQ.data?.services} loading={overviewQ.isLoading} error={overviewQ.isError} />
        {o && <ScraperStrip scrapers={o.status.scrapers} />}
      </Band>
      <Band title="Activity" hint="what people did, and what it cost">
        <ActivityBand activity={o?.activity} events={activityQ.data?.events} loading={overviewQ.isLoading} />
      </Band>
      <Band title="Library" hint="what is on the shelf">
        <LibraryBand library={o?.library} torbox={torboxUsageQ.data} loading={overviewQ.isLoading} />
      </Band>
      <Band title="TorBox">
        <TorboxCard adds={o?.status.torbox_adds} byReason={quotaQ.data?.by_reason} usage={torboxUsageQ.data}
          streamFront={healthQ.data?.stream_front} recentStreams={o?.torbox.recent_streams} last429At={o?.torbox.last_429_at} idleMinutes={null} />
      </Band>
      <Band title="Reference" hint="collapsed by default; state remembered">
        <div className="space-y-3">
          <ReferenceSection id="metrics" title="Metrics, 30 days" hint="latency, quality added, source win rate, failures">
            {(open) => <MetricsLoader open={open} />}
          </ReferenceSection>
          <ReferenceSection id="endpoints" title="Integration endpoints" hint="Seerr, TorBox, Catbox prefix, webhook secret">
            {(open) => <EndpointsLoader open={open} />}
          </ReferenceSection>
          <ReferenceSection id="folders" title="Top folders" hint="largest media folders by strm count">
            {(open) => <FoldersLoader open={open} />}
          </ReferenceSection>
        </div>
      </Band>
    </div>
  );
}

function MetricsLoader({ open }: { open: boolean }) {
  const q = useQuery({ queryKey: ['admin-metrics-summary'], queryFn: api.metricsSummary, retry: false, enabled: open });
  return <MetricsPanel metrics={q.data} loading={q.isLoading} />;
}
function EndpointsLoader({ open }: { open: boolean }) {
  const q = useQuery({ queryKey: ['admin-webhook-secret'], queryFn: api.webhookSecret, retry: false, enabled: open });
  return <EndpointsPanel secret={q.data} loading={q.isLoading} error={q.isError} />;
}
function FoldersLoader({ open }: { open: boolean }) {
  const q = useQuery({ queryKey: ['admin-storage'], queryFn: api.storage, retry: false, enabled: open });
  return <FoldersPanel folders={q.data?.folders} loading={q.isLoading} />;
}
```

Remove the now-unused `formatGiB`/`formatCountdown` and the `torboxList`, `retryQueue`, `libraryHealth`, `stats` queries from the page (the endpoints stay in `api.ts` for other callers; check `grep -rn "api.torboxList\|api.retryQueue\|api.libraryHealth\|api.stats(" frontend/src` and leave the helpers if anything else uses them).

- [ ] **Step 7: Rewrite Overview.test.tsx**

Keep the `vi.mock` block, replacing `stats` with an `overview` fixture matching the payload type (status with one down scraper and 2 failures, activity with 4 plays today, library with 312 movies, torbox with 2 recent streams and null last 429), keep `health`, `activity`, `torboxUsage`, `torboxQuota`, `metricsSummary`, `storage`, `webhookSecret`, `session`; drop `stats`, `torboxList`, `retryQueue`, `libraryHealth`. Tests:

```tsx
describe('Overview tab', () => {
  it('renders the five bands in order with the status strip first', async () => {
    renderIt();
    await waitFor(() => expect(screen.getByRole('group', { name: 'Failures 7d: problem' })).toBeInTheDocument());
    const bands = screen.getAllByRole('region').map((r) => r.getAttribute('aria-label'));
    expect(bands).toEqual(['Right now', 'Activity', 'Library', 'TorBox', 'Reference']);
  });

  it('feeds the bands from the aggregated payload', async () => {
    renderIt();
    expect(await screen.findByText('Plays today')).toBeInTheDocument();
    expect(screen.getByText('312')).toBeInTheDocument();
    expect(screen.getByText('Streamed in last 15 min')).toBeInTheDocument();
  });

  it('keeps the reference sections closed and does not fetch them until opened', async () => {
    renderIt();
    await screen.findByText('Plays today');
    expect(api.metricsSummary).not.toHaveBeenCalled();
    await userEvent.click(screen.getByText('Metrics, 30 days'));
    await waitFor(() => expect(api.metricsSummary).toHaveBeenCalledTimes(1));
  });

  it('has exactly one TorBox card', async () => {
    renderIt();
    await screen.findByText('Plays today');
    expect(screen.queryByText('TorBox quota')).not.toBeInTheDocument();
    expect(screen.queryByText('TorBox Usage')).not.toBeInTheDocument();
    expect(screen.getAllByText('TorBox').length).toBeGreaterThanOrEqual(1);
  });
});
```

Make the mocked `metricsSummary` a `vi.fn(() => Promise.resolve(...))` so the call count assertion works. `section` elements with an `aria-label` expose the `region` role.

- [ ] **Step 8: Run everything, build, commit**

Run: `cd frontend && npx tsc --noEmit && npx vitest run && npm run build`; then from the repo root the full backend suite (unchanged, sanity).
Mutations: make `ReferenceSection` default to open (closed-by-default test fails); render two TorBox cards (single-card test fails). Restore.

```bash
git add frontend/src/pages/admin/Overview.tsx frontend/src/pages/admin/Overview.test.tsx frontend/src/pages/admin/overview static/app
git commit -m "feat(overview): five-band page composition with collapsed reference sections

Claude-Session: https://claude.ai/code/session_017Cc8iouqJoYhUcnJhhgapA"
```

---

### Task 5: Docs and changelog

**Files:**
- Modify: `README.md` (the admin dashboard description; grep `Overview` to find it), `CHANGELOG.md`

- [ ] **Step 1: README**

Where the README describes the admin Overview (grep `Overview` and `admin dashboard`), replace the sentence or bullet with: "The Overview opens with a status strip (services, scrapers, TorBox adds, failures, queue, titles needing attention, pending approvals), then activity (plays today and this week, requests, egress), the library, one TorBox card, and collapsed reference sections." No dashes.

- [ ] **Step 2: CHANGELOG**

Under `## [Unreleased]`:

```markdown
### Changed

- The admin Overview is rebuilt as five bands, problems first. A status
  strip shows services, scrapers, TorBox adds, failures, the queue,
  titles needing attention and pending approvals, each with a link to
  the tab that fixes it and a glow only when something is wrong. New
  figures: plays today and this week (from the egress rows), pending
  approvals with the oldest age, titles needing attention, per-scraper
  state and latency, titles streamed in the last 15 minutes, and the
  last TorBox 429. The two TorBox cards are one card; metrics, the
  integration endpoints and the top folders are collapsed sections that
  remember their state and load only when opened. Everything the
  database can answer comes from one new `GET /ui/api/overview` call.
```

- [ ] **Step 3: Check and commit**

Run `grep -n $'\xe2\x80\x94' README.md CHANGELOG.md` (the UTF-8 bytes of U+2014) and confirm no new em-dash (two pre-existing ones in CHANGELOG.md are known).

```bash
git add README.md CHANGELOG.md
git commit -m "docs: Overview redesign

Claude-Session: https://claude.ai/code/session_017Cc8iouqJoYhUcnJhhgapA"
```
