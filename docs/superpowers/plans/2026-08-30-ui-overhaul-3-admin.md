# UI Overhaul, Plan 3: Admin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the split-brain admin (a 2,297-line Jinja dashboard in an iframe next to a 745-line half-wired React page) with one native React admin of nine tabs, losing no functionality, and add the two data sources it needs: scraper health and structured logs.

**Architecture:** A written feature inventory of both existing surfaces comes first and is the discharge checklist for the whole plan; nothing ships until every inventoried control has a home. `pages/admin/` holds one file per tab under an `AdminLayout` tab strip. The Filter rules tab ports the shipped C2 editor's pure state model with a behavioural-equivalence test against the original, because the Jinja side still needs the original file until Plan 4. Two backend additions: a timing ring buffer inside `scrapers.py` feeding `GET /ui/api/scraper-health`, and a structured `GET /ui/api/logs`.

**Tech Stack:** React 18, TypeScript, React Query 5, the Plan 1 primitives, Vitest; Python 3.12 / Flask for the two endpoints.

**Spec:** `docs/superpowers/specs/2026-08-30-ui-overhaul-design.md`

**Plan 3 of 4.** Requires Plans 1 and 2 (complete on `feat/ui-overhaul` at 450cea8). Plan 4 (pre-auth cutover) follows and deletes the Jinja templates' routes from the SPA path; the Jinja `/admin` stays reachable throughout this plan.

## Global Constraints

- **Never use em-dashes**, anywhere, in code or prose. Use a comma, a colon, parentheses, or " - ".
- **The repository is public.** No passwords, tokens, API keys or IP addresses in any commit.
- **Work on branch `feat/ui-overhaul`.** Do not commit to `main`.
- **No `Co-Authored-By` lines.** Every commit message body ends with exactly:
  `Claude-Session: https://claude.ai/code/session_01S7W5TTdnwd8hdgj3L3dnnx`
- **`static/app/` rebuilds land at the final task only.**
- **Nothing from the inventory may be dropped.** A control with no home is a blocking defect, not a judgment call. If a control genuinely cannot be ported (needs missing data), it is listed in the final task's report as retained-in-Jinja with the reason.
- **Every number rendered maps to a real endpoint.** The Admin overview substitution table in the spec is binding; it is copied into Task 6.
- **Refresh policy:** no reloads; spinners gate on `isLoading`, never `isFetching`; polling only while the panel is visible (the Logs tab polls at 5s and must stop when hidden); anything faster than 10s carries a code comment.
- **Existing endpoints are consumed, not changed**, except the two additions (scraper-health, logs). The settings save path stays `POST /ui/settings` form-encoded exactly as the Jinja page uses it.
- **Tests:** Python via `./.venv-sdd/bin/python -m pytest tests/ -q` (nothing may `import app`; routes asserted against source). Frontend `cd frontend && npm test`. The 34 tests in `tests/js/filter_rules.test.js` must pass UNCHANGED throughout; editing them means the port broke behaviour.
- `npx tsc --noEmit` has exactly 4 pre-existing errors (`usePluginSlots.ts` x3, `Watchlist.tsx` x1). None may be added; clearing them is welcome.
- Python suite baseline entering this plan: 456 passed. Frontend baseline: 67 tests.

## Reconciliation map (binding starting point; Task 1 verifies and extends it)

| React tab | Absorbs |
|---|---|
| Overview | Jinja `overview` (health dots, stat tiles per the substitution table, quality bars, TorBox quota, activity feed, webhook secret + Copy) plus Jinja `releases` as a changelog panel |
| Users | Jinja `users` (table, create) plus `Admin.tsx` users CRUD (role, quota, enabled, auto-approve toggles, delete) |
| Requests | Jinja `requests` (all-requests table with Delete and Remove-from-library) plus `Admin.tsx` pending approvals (approve/deny) plus `Admin.tsx` `AutoApprovePanel` (genre rules, run now) |
| Filter rules | the C2 editor, ported (Task 10) |
| Scrapers | new health panel (Task 2's endpoint) plus the Jinja Zilean controls (`zileanStatus`, `zileanSync`, `zileanImport`) |
| Logs | new structured log panel (Task 3's endpoint) |
| Maintenance | Jinja `maintenance`: all 14 action forms/buttons, the repair history (summary + table, from `/ui/api/repair`), plus the JS-driven `add-magnet`, `torbox-delete`, `backup-restore`, `show-override-delete` controls, plus `Admin.tsx` `ArrImportPanel` (Radarr/Sonarr test + import) and `MaintenancePanel` |
| Blacklist | Jinja `blacklist` (table plus per-hash clear) |
| Settings | Jinja `settings`: the runtime settings editor over `GET /ui/api/settings` (`settings.all_for_ui()` groups) minus the `filter_rules` group, Save all via `POST /ui/settings`, Run auto-add now, plus `Admin.tsx` `DiscoverGenreTabsPanel` |

## File Structure

| File | Responsibility |
|---|---|
| `docs/superpowers/specs/assets/2026-08-31-admin-inventory.md` | create (Task 1): the checklist |
| `scraper_metrics.py` | create: ring buffer + state derivation |
| `scrapers.py` | modify: timing wrapper around each scraper call |
| `app.py` | modify: `GET /ui/api/scraper-health`, `GET /ui/api/logs` |
| `log_buffer.py` | modify: structured accessor |
| `tests/test_scraper_metrics.py`, `tests/test_logs_endpoint.py` | create |
| `frontend/src/api.ts` | modify: clients for the new endpoints plus any admin endpoint not yet wrapped |
| `frontend/src/pages/admin/AdminLayout.tsx` | create: tab strip + outlet |
| `frontend/src/pages/admin/{Overview,Users,Requests,FilterRules,Scrapers,Logs,Maintenance,Blacklist,Settings}.tsx` | create: one tab each |
| `frontend/src/pages/admin/filterRulesModel.ts` | create: typed port of the C2 pure state model |
| `frontend/src/App.tsx` | modify: `/admin` renders AdminLayout |
| Deleted at the end | `frontend/src/pages/Admin.tsx`, `frontend/src/pages/AdminTabs.tsx` |

---

### Task 1: The feature inventory

**Files:**
- Create: `docs/superpowers/specs/assets/2026-08-31-admin-inventory.md`

**Interfaces:**
- Consumes: `templates/ui.html` (the eight `tab-pane` divs AND the page's shared JS, which drives controls the pane markup does not show: `approveReq`, `denyReq`, `deleteRequest`, `purgeRequest`, `toggleAuto`, `toggleAutoApprove`, `toggleEnabled`, `arrTest`, `arrRun`, `arrStatus`, `zileanStatus`, `zileanSync`, `zileanImport`, `addMagnet`/`/ui/add-magnet`, `/ui/torbox-delete`, `/ui/backup-restore`, `/ui/blacklist-clear/<hash>`, `/ui/show-override-delete/<imdb>`, plus `refreshHealth`, `refreshOverview`, `refreshRepair`, `refreshTorbox`, pagination and sort helpers); `frontend/src/pages/Admin.tsx` (745 lines).
- Produces: the checklist every later task checks its controls against, and the final task discharges.

- [ ] **Step 1: Walk the Jinja dashboard**

Read `templates/ui.html` end to end. For every user-visible control (button, form, toggle, input, auto-refreshing panel, keyboard shortcut), record one checklist line:

```markdown
- [ ] <tab>: <control label> -> <endpoint or JS function> -> planned home: <React tab>
```

Use the reconciliation map in this plan's header for the planned homes; a control the map does not cover gets the best-fitting tab and a `(placement chosen by inventory)` marker.

- [ ] **Step 2: Walk Admin.tsx**

Same treatment for every control in `frontend/src/pages/Admin.tsx`. Where a control duplicates a Jinja one (approve/deny, user toggles), record them as one line with both sources named.

- [ ] **Step 3: Cross-check against the API surface**

Run: `grep -oE '"/ui/[a-z-]+"' app.py | sort -u` and `grep -oE "'/ui/api/[a-z/-]+'" frontend/src/api.ts | sort -u`. Any admin-facing POST route reachable from neither surface's controls gets a checklist line marked `(orphan route, verify before porting)`.

- [ ] **Step 4: Summarize**

End the file with counts: total controls, per planned tab, orphans. No control may lack a planned home.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/assets/2026-08-31-admin-inventory.md
git commit -m "docs: admin feature inventory, the discharge checklist for plan 3"
```

---

### Task 2: Scraper metrics and the health endpoint

**Files:**
- Create: `scraper_metrics.py`
- Modify: `scrapers.py` (the `merge_candidates` executor block, lines 99-110)
- Modify: `app.py` (after `ui_api_me_quota`)
- Modify: `frontend/src/api.ts`
- Test: `tests/test_scraper_metrics.py`

**Interfaces:**
- Consumes: `scrapers._SCRAPERS` / `scrapers._active()`; `health_cache.is_up(name)`.
- Produces:
  - `scraper_metrics.record(name: str, elapsed_ms: float, ok: bool) -> None`
  - `scraper_metrics.get_health(active: list[str]) -> list[dict]`, each dict `{"name": str, "latency_ms": int | None, "state": "ok" | "slow" | "down" | "unknown", "samples": int}`
  - HTTP `GET /ui/api/scraper-health` returning `{"scrapers": [...]}` for the active scrapers only.
  - TS: `api.scraperHealth(): Promise<ScraperHealth>` with `export type ScraperHealth = { scrapers: { name: string; latency_ms: number | null; state: 'ok' | 'slow' | 'down' | 'unknown'; samples: number }[] }`.

- [ ] **Step 1: Write the failing test**

`tests/test_scraper_metrics.py`:

```python
"""The Scrapers admin tab shows per-scraper latency and state.

The buffer is in-process and unpersisted on purpose: the app runs one
gunicorn worker, and an empty buffer after restart must read as unknown,
never as an outage.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import scraper_metrics


@pytest.fixture(autouse=True)
def _clean():
    scraper_metrics.reset()
    yield
    scraper_metrics.reset()


def test_no_samples_reads_unknown_not_down():
    (h,) = scraper_metrics.get_health(["torrentio"])
    assert h == {"name": "torrentio", "latency_ms": None, "state": "unknown", "samples": 0}


def test_fast_and_succeeding_reads_ok():
    for _ in range(5):
        scraper_metrics.record("torrentio", 212.0, True)
    (h,) = scraper_metrics.get_health(["torrentio"])
    assert h["state"] == "ok"
    assert h["latency_ms"] == 212
    assert h["samples"] == 5


def test_median_at_or_over_1000ms_reads_slow():
    for ms in (900, 1400, 1500):
        scraper_metrics.record("debridio", ms, True)
    (h,) = scraper_metrics.get_health(["debridio"])
    assert h["state"] == "slow"


def test_three_consecutive_failures_read_down():
    scraper_metrics.record("zilean", 100, True)
    for _ in range(3):
        scraper_metrics.record("zilean", 3000, False)
    (h,) = scraper_metrics.get_health(["zilean"])
    assert h["state"] == "down"


def test_a_success_resets_the_failure_streak():
    for _ in range(3):
        scraper_metrics.record("zilean", 3000, False)
    scraper_metrics.record("zilean", 150, True)
    (h,) = scraper_metrics.get_health(["zilean"])
    assert h["state"] != "down"


def test_the_ring_buffer_is_bounded_at_50():
    for i in range(80):
        scraper_metrics.record("torrentio", float(i), True)
    (h,) = scraper_metrics.get_health(["torrentio"])
    assert h["samples"] == 50


def test_only_requested_scrapers_appear_in_order():
    scraper_metrics.record("torrentio", 100, True)
    out = scraper_metrics.get_health(["debridio", "torrentio"])
    assert [h["name"] for h in out] == ["debridio", "torrentio"]


def test_the_wrapper_records_and_reraises():
    """merge_candidates must still see the exception; a scraper failure that
    the wrapper swallowed would be counted as an empty success upstream."""
    def boom(*a, **k):
        raise RuntimeError("upstream 502")

    timed = scraper_metrics.timed("torrentio", boom)
    with pytest.raises(RuntimeError):
        timed("movie", "tt1", None, None, None)
    (h,) = scraper_metrics.get_health(["torrentio"])
    assert h["samples"] == 1


def test_the_endpoint_is_registered():
    with open(os.path.join(os.path.dirname(__file__), "..", "app.py"), encoding="utf-8") as f:
        src = f.read()
    assert '@app.get("/ui/api/scraper-health")' in src
    assert "scraper_metrics.get_health(" in src


def test_the_scraper_calls_go_through_the_wrapper():
    with open(os.path.join(os.path.dirname(__file__), "..", "scrapers.py"), encoding="utf-8") as f:
        src = f.read()
    assert "scraper_metrics.timed(" in src
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv-sdd/bin/python -m pytest tests/test_scraper_metrics.py -q`
Expected: FAIL, no module `scraper_metrics`.

- [ ] **Step 3: Implement the module**

`scraper_metrics.py`:

```python
"""Rolling per-scraper call timings for the admin Scrapers tab.

In-process and unpersisted by design: the app runs one gunicorn worker
(the in-process catbox locks already rely on that), and history that did
not survive a restart must read as unknown, never as an outage.
"""
import statistics
import threading
import time
from collections import deque

_MAX_SAMPLES = 50
_SLOW_MS = 1000
_DOWN_AFTER = 3

_lock = threading.Lock()
_samples: dict[str, deque] = {}


def reset() -> None:
    with _lock:
        _samples.clear()


def record(name: str, elapsed_ms: float, ok: bool) -> None:
    with _lock:
        _samples.setdefault(name, deque(maxlen=_MAX_SAMPLES)).append((elapsed_ms, ok))


def timed(name: str, fn):
    """Wrap a scraper fetch so its latency and outcome are recorded.

    Re-raises: merge_candidates counts failures itself, and a swallowed
    exception would read upstream as an empty success.
    """
    def run(*args, **kwargs):
        t0 = time.monotonic()
        try:
            out = fn(*args, **kwargs)
        except Exception:
            record(name, (time.monotonic() - t0) * 1000, False)
            raise
        record(name, (time.monotonic() - t0) * 1000, True)
        return out
    return run


def get_health(active: list[str]) -> list[dict]:
    out = []
    with _lock:
        for name in active:
            buf = list(_samples.get(name, ()))
            if not buf:
                out.append({"name": name, "latency_ms": None, "state": "unknown", "samples": 0})
                continue
            median = statistics.median(ms for ms, _ in buf)
            recent = [ok for _, ok in buf[-_DOWN_AFTER:]]
            if len(recent) == _DOWN_AFTER and not any(recent):
                state = "down"
            elif median >= _SLOW_MS:
                state = "slow"
            else:
                state = "ok"
            out.append({"name": name, "latency_ms": int(median), "state": state, "samples": len(buf)})
    return out
```

- [ ] **Step 4: Wire the wrapper into scrapers.py**

In `merge_candidates`, the executor submits `fn` directly:

```python
        futures = {ex.submit(fn, media_type, imdb_id, season, episode, timeout): name
                   for name, fn in active}
```

becomes

```python
        futures = {ex.submit(scraper_metrics.timed(name, fn),
                             media_type, imdb_id, season, episode, timeout): name
                   for name, fn in active}
```

with `import scraper_metrics` added to the module imports. Nothing else in the file changes.

- [ ] **Step 5: Add the route and client**

`app.py`, after `ui_api_me_quota`:

```python
@app.get("/ui/api/scraper-health")
def ui_api_scraper_health():
    """Rolling latency and state per active scraper, for the admin tab."""
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import scrapers as _scrapers
    active = [name for name, _ in _scrapers._active()]
    return jsonify(scrapers=scraper_metrics.get_health(active))
```

with `import scraper_metrics` beside the other imports. In `frontend/src/api.ts` add the `ScraperHealth` type and `scraperHealth` member per the Interfaces block, matching the file's `http` helper style.

- [ ] **Step 6: Run the tests**

Run: `./.venv-sdd/bin/python -m pytest tests/test_scraper_metrics.py tests/test_scrapers.py tests/test_scraper_outage.py -q` then the full suite.
Expected: new tests pass, the existing scraper tests still pass (the wrapper must not change merge semantics), full suite 466.

- [ ] **Step 7: Commit**

```bash
git add scraper_metrics.py scrapers.py app.py frontend/src/api.ts tests/test_scraper_metrics.py
git commit -m "feat(api): per-scraper latency ring buffer and health endpoint"
```

---

### Task 3: The structured logs endpoint

**Files:**
- Modify: `log_buffer.py`
- Modify: `app.py` (after `ui_api_scraper_health`)
- Modify: `frontend/src/api.ts`
- Test: `tests/test_logs_endpoint.py`

**Interfaces:**
- Consumes: `log_buffer._buffer` lines formatted `%(asctime)s %(levelname)s [%(name)s] %(message)s`.
- Produces:
  - `log_buffer.get_structured(limit: int = 200, min_level: str | None = None) -> list[dict]`, each `{"time": "HH:MM:SS", "level": "INFO", "name": "mycelium", "msg": str}`, newest last.
  - HTTP `GET /ui/api/logs?limit=&level=` returning `{"lines": [...]}`, limit clamped to 1000, admin-only.
  - TS: `api.adminLogs(limit?: number, level?: string): Promise<{ lines: LogLine[] }>` with `export type LogLine = { time: string; level: string; name: string; msg: string }`.

- [ ] **Step 1: Write the failing test**

`tests/test_logs_endpoint.py`:

```python
"""The Logs admin tab polls a structured feed instead of raw lines.

Parsing lives next to the buffer because the format string lives there;
a malformed line (multi-line traceback continuation) must never crash the
endpoint, it rides along as message-only.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import log_buffer


def _fill(lines):
    log_buffer._buffer.clear()
    log_buffer._buffer.extend(lines)


def test_lines_parse_into_time_level_name_msg():
    _fill(["2026-08-31 20:11:25,123 INFO [mycelium] started up"])
    (line,) = log_buffer.get_structured()
    assert line == {"time": "20:11:25", "level": "INFO", "name": "mycelium", "msg": "started up"}


def test_a_malformed_line_survives_as_message_only():
    _fill(["Traceback (most recent call last):"])
    (line,) = log_buffer.get_structured()
    assert line["msg"] == "Traceback (most recent call last):"
    assert line["level"] == ""


def test_min_level_filters_below_it():
    _fill([
        "2026-08-31 20:00:00,000 DEBUG [x] noise",
        "2026-08-31 20:00:01,000 INFO [x] info",
        "2026-08-31 20:00:02,000 WARNING [x] warn",
        "2026-08-31 20:00:03,000 ERROR [x] boom",
    ])
    levels = [l["level"] for l in log_buffer.get_structured(min_level="WARNING")]
    assert levels == ["WARNING", "ERROR"]
    # malformed lines are level "" and survive any filter: hiding a traceback
    # because it has no level would hide exactly what the reader came for
    _fill(["party time", "2026-08-31 20:00:00,000 DEBUG [x] noise"])
    assert [l["msg"] for l in log_buffer.get_structured(min_level="ERROR")] == ["party time"]


def test_limit_takes_the_newest():
    _fill([f"2026-08-31 20:00:00,000 INFO [x] m{i}" for i in range(10)])
    out = log_buffer.get_structured(limit=3)
    assert [l["msg"] for l in out] == ["m7", "m8", "m9"]


def test_the_endpoint_is_registered_and_admin_only():
    with open(os.path.join(os.path.dirname(__file__), "..", "app.py"), encoding="utf-8") as f:
        src = f.read()
    import re
    m = re.search(r'@app\.get\("/ui/api/logs"\)(.{0,400})', src, re.S)
    assert m
    assert "auth.is_admin()" in m.group(1)
    assert "get_structured(" in m.group(1)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv-sdd/bin/python -m pytest tests/test_logs_endpoint.py -q`
Expected: FAIL, `get_structured` missing.

- [ ] **Step 3: Implement**

Append to `log_buffer.py`:

```python
_LEVEL_ORDER = {"DEBUG": 10, "INFO": 20, "WARNING": 30, "ERROR": 40, "CRITICAL": 50}
_LINE_RE = None


def get_structured(limit: int = 200, min_level: str | None = None) -> list[dict]:
    """Parsed view of the buffer for the admin Logs tab, newest last.

    Malformed lines (traceback continuations) carry level "" and pass every
    filter: hiding a traceback because it has no level would hide exactly
    what the reader came for.
    """
    global _LINE_RE
    import re
    if _LINE_RE is None:
        _LINE_RE = re.compile(
            r"^(\d{4}-\d{2}-\d{2} (\d{2}:\d{2}:\d{2})),\d+ (\w+) \[([^\]]*)\] (.*)$"
        )
    threshold = _LEVEL_ORDER.get(min_level or "", 0)
    out = []
    for raw in list(_buffer):
        m = _LINE_RE.match(raw)
        if m:
            level = m.group(3)
            if _LEVEL_ORDER.get(level, 0) < threshold:
                continue
            out.append({"time": m.group(2), "level": level, "name": m.group(4), "msg": m.group(5)})
        else:
            out.append({"time": "", "level": "", "name": "", "msg": raw})
    return out[-max(1, min(int(limit), 1000)):]
```

`app.py`, after the scraper-health route:

```python
@app.get("/ui/api/logs")
def ui_api_logs():
    """Structured log feed for the admin Logs tab; polls at 5s while visible."""
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    limit = request.args.get("limit", default=200, type=int)
    level = request.args.get("level") or None
    return jsonify(lines=log_buffer.get_structured(limit=limit, min_level=level))
```

Add the TS client per the Interfaces block.

- [ ] **Step 4: Run the tests**

Run: `./.venv-sdd/bin/python -m pytest tests/test_logs_endpoint.py -q` then the full suite.
Expected: 5 new pass; suite 471.

- [ ] **Step 5: Commit**

```bash
git add log_buffer.py app.py frontend/src/api.ts tests/test_logs_endpoint.py
git commit -m "feat(api): structured admin log feed with level filter"
```

---

### Task 4: AdminLayout and routing

**Files:**
- Create: `frontend/src/pages/admin/AdminLayout.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/pages/admin/AdminLayout.test.tsx`

**Interfaces:**
- Consumes: react-router.
- Produces: `AdminLayout` default export rendering a tab strip and the active tab's component; `export const ADMIN_TABS: { id: string; label: string; component: React.ComponentType }[]` in this exact order: overview Overview, users Users, requests Requests, filter-rules "Filter rules", scrapers Scrapers, logs Logs, maintenance Maintenance, blacklist Blacklist, settings Settings. The active tab lives in the URL hash (`/admin#users`) so a refresh and deep links keep the tab, matching the Jinja dashboard's hash behaviour. Until Tasks 5-11 land, each tab renders a stub component (`<p className="text-muted text-sm">Coming in this plan.</p>`); each later task replaces exactly its own stub.

- [ ] **Step 1: Write the failing test**

`frontend/src/pages/admin/AdminLayout.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import AdminLayout, { ADMIN_TABS } from './AdminLayout';

function renderIt(hash = '') {
  return render(
    <MemoryRouter initialEntries={[`/admin${hash}`]}>
      <AdminLayout />
    </MemoryRouter>,
  );
}

describe('AdminLayout', () => {
  it('declares the nine tabs in order', () => {
    expect(ADMIN_TABS.map((t) => t.id)).toEqual([
      'overview', 'users', 'requests', 'filter-rules', 'scrapers',
      'logs', 'maintenance', 'blacklist', 'settings',
    ]);
  });

  it('renders the strip and defaults to Overview', () => {
    renderIt();
    for (const t of ADMIN_TABS) {
      expect(screen.getByRole('tab', { name: t.label })).toBeInTheDocument();
    }
    expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute('aria-selected', 'true');
  });

  it('opens the tab named in the URL hash', () => {
    renderIt('#blacklist');
    expect(screen.getByRole('tab', { name: 'Blacklist' })).toHaveAttribute('aria-selected', 'true');
  });

  it('switches tabs on click and writes the hash', async () => {
    renderIt();
    await userEvent.click(screen.getByRole('tab', { name: 'Users' }));
    expect(screen.getByRole('tab', { name: 'Users' })).toHaveAttribute('aria-selected', 'true');
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npm test -- AdminLayout`
Expected: FAIL, cannot resolve.

- [ ] **Step 3: Implement**

`AdminLayout.tsx`: a `useLocation`/`useNavigate` pair reading `location.hash.slice(1)` (falling back to `overview` when absent or unknown), a strip of `role="tab"` buttons styled like the mockup's admin tabs (`padding 14px, font-medium text-xs, active: text-white with inset 0 -2px 0 #9f92ff box-shadow, inactive: text-muted`), navigating with `navigate({ hash: id }, { replace: true })`, and the active component rendered below. Stubs for all nine tabs defined in the same file for now; each later task moves its tab into its own file and imports it here.

In `App.tsx`, replace the `admin` route element `<AdminTabs />` with `<AdminLayout />` (import from `./pages/admin/AdminLayout`). Leave `AdminTabs.tsx` and `Admin.tsx` on disk; the final task deletes them after the inventory is discharged.

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npm test`
Expected: all green (Plan 2 suites untouched).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/admin/ frontend/src/App.tsx
git commit -m "feat(admin): nine-tab AdminLayout behind /admin with hash routing"
```

---

### Task 5: Users tab

**Files:**
- Create: `frontend/src/pages/admin/Users.tsx`
- Modify: `frontend/src/pages/admin/AdminLayout.tsx` (swap the stub)
- Test: `frontend/src/pages/admin/Users.test.tsx`

**Interfaces:**
- Consumes: `api.users`, and the user mutation members `Admin.tsx` already uses (find them: `grep -n "users\|updateUser\|deleteUser\|createUser" frontend/src/api.ts`); primitives `Card`, `Pill`, `Toggle`, `DataTable`.
- Produces: `Users` default export, no props.

Port from `Admin.tsx` lines 30-279 (users table, per-user role/quota/enabled/auto-approve editing, delete with confirm, `CreateUserForm`) and the Jinja users tab (verify against the inventory that nothing exists there beyond what `Admin.tsx` has; the inventory says create + toggles). Restyle: the table via `DataTable` columns User (avatar initials + name, per the mockup), Role (select or pill), Quota used (the user's `quota_monthly`; "unlimited" when 0), Enabled (`Toggle`), Auto-approve (`Toggle`), Actions. Keep every mutation and its invalidations byte-compatible: same endpoints, same payload shapes. The local `Toggle` helper in `Admin.tsx` dies; the primitive replaces it.

- [ ] **Step 1: Write the failing test**

`frontend/src/pages/admin/Users.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi } from 'vitest';
import Users from './Users';

vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return {
    ...actual,
    api: {
      ...actual.api,
      users: () => Promise.resolve({ users: [
        { id: 1, username: 'adam', role: 'admin', quota_monthly: 0, enabled: 1, auto_approve: 1 },
        { id: 2, username: 'guest', role: 'user', quota_monthly: 25, enabled: 1, auto_approve: 0 },
      ] }),
      session: () => Promise.resolve({ authenticated: true, user: { username: 'adam', role: 'admin' } }),
    },
  };
});

function renderIt() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><Users /></QueryClientProvider>);
}

describe('Users tab', () => {
  it('lists every user with role and quota', async () => {
    renderIt();
    await waitFor(() => {
      expect(screen.getByText('adam')).toBeInTheDocument();
      expect(screen.getByText('guest')).toBeInTheDocument();
      expect(screen.getByText('unlimited')).toBeInTheDocument();
      expect(screen.getByText('25')).toBeInTheDocument();
    });
  });

  it('offers the create form', async () => {
    renderIt();
    await waitFor(() => expect(screen.getByRole('button', { name: /create/i })).toBeInTheDocument());
  });
});
```

Adapt the mocked `users` payload to the real `api.users` return shape (read it in `api.ts`); adapt mock fields, never assertions.

- [ ] **Step 2: Run to verify it fails**, implement per the port description, run `cd frontend && npm test`, all green, tsc at 4.

- [ ] **Step 3: Check the inventory**

Tick every Users line in `docs/superpowers/specs/assets/2026-08-31-admin-inventory.md` this tab now covers, in the same commit.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/admin/ docs/superpowers/specs/assets/2026-08-31-admin-inventory.md
git commit -m "feat(admin): native Users tab"
```

---

### Task 6: Overview tab

**Files:**
- Create: `frontend/src/pages/admin/Overview.tsx`
- Modify: `frontend/src/pages/admin/AdminLayout.tsx` (swap the stub)
- Modify: `frontend/src/api.ts` (clients for `/ui/api/health`, `/ui/api/activity`, `/ui/api/webhook-secret`, `/ui/api/torbox-list` if absent; check first)
- Test: `frontend/src/pages/admin/Overview.test.tsx`

**Interfaces:**
- Consumes: `api.stats` (shape proven in Plan 2), `/ui/api/health` (`{services: [{name, status}]}`), `/ui/api/activity` (`{events}`), `/ui/api/webhook-secret` (`{secret, source}`, admin-gated), the releases list (served inside the Jinja template today; expose it: add to this task a tiny route `GET /ui/api/releases` returning `jsonify(releases=RELEASES)` in `app.py` plus a source-asserting line in `tests/test_ui_endpoints_misc.py` you create with the same no-import-app pattern as `tests/test_quota.py`); `StatTile`, `StatusDot`, `Card`, `Pill`.
- Produces: `Overview` default export.

**Binding metric substitution table (from the spec):**

| Tile | Value | Source |
|---|---|---|
| Requests 7d | `succeeded_7d` ok / `failed_7d` fail as the sub-line, total as the value | `api.stats().requests` |
| Queue depth | retry queue rows + active wanted | `/ui/api/retry-queue` count if a GET exists (check `grep -n "retry-queue" app.py`), else `stats.wanted.active` alone with the sub-line "active wanted"; state which in the report |
| TorBox library | item count, summed size formatted GiB | `api.torboxList()` (add client if missing; render "unavailable" on error, never crash the tab) |
| Failures 7d | `failed_7d` | `api.stats().requests` |

Also ports: the health dot row (statuses via `StatusDot`, `ok -> ok`, `down -> danger`, else `warn`), the quality distribution bars (from `stats.qualities`, percentage bars in `bg-accent`), the activity feed (last 20, time + event + title, `text-xs` rows), the webhook secret with a Copy button (`navigator.clipboard.writeText`), and a Releases panel listing `version / date / notes` from the new releases endpoint.

Refresh: `refetchInterval: 30_000` on stats and health (matches the Jinja cadence), none elsewhere. Spinners gate on `isLoading` only.

- [ ] **Step 1: failing test** with mocked `stats`, `health`, `activity`, `releases` asserting: the four tiles render their values; no "Active streams" or "Cache hit rate" text anywhere (the dropped mockup tiles must not sneak back); the health row shows one dot per service; the changelog lists a version. Follow the Plan 2 mock pattern (spread `actual.api`).
- [ ] **Step 2**: run to fail, implement, `npm test` green, tsc at 4, Python suite still green (the releases route + its source test).
- [ ] **Step 3**: tick the Overview and Releases inventory lines. Commit:

```bash
git add frontend/src/pages/admin/ frontend/src/api.ts app.py tests/ docs/superpowers/specs/assets/2026-08-31-admin-inventory.md
git commit -m "feat(admin): native Overview tab with the real-metric tiles"
```

---

### Task 7: Requests tab

**Files:**
- Create: `frontend/src/pages/admin/Requests.tsx`
- Modify: `frontend/src/pages/admin/AdminLayout.tsx`
- Modify: `frontend/src/api.ts` (client for `/ui/api/requests/all` if absent)
- Test: `frontend/src/pages/admin/Requests.test.tsx`

**Interfaces:**
- Consumes: `/ui/api/requests/all` (the Jinja table's source), the delete and purge endpoints (`/ui/api/requests/<id>/delete`, `/ui/api/requests/<id>/purge`), `api.userRequests('pending')` + approve/deny members (in `api.ts`, used by `Admin.tsx`), `api.autoApproveGenreRules` + save + run-now; `DataTable`, `Pill`, `statusLabel`/`statusToPillState` from primitives.
- Produces: `Requests` default export.

Three sections, top to bottom:
1. **Pending approvals**: port of `Admin.tsx`'s panel (approve/deny buttons per row, requester shown). Empty state "No requests awaiting review".
2. **All requests**: the Jinja table (title, imdb mono, type, status pill via the shared helpers, added date, Delete and Remove-from-library buttons with the same `confirm()` copy the Jinja version uses; both invalidate the list on success). Client-side search box filtering title/imdb, like the Jinja `data-filter`.
3. **Auto-approve rules**: port of `AutoApprovePanel` (genre rules editor + Run now), mutations byte-compatible.

- [ ] **Step 1: failing test**: mock `requestsAll` (two rows, one `success` one `failed`), `userRequests` (one pending row), assert: both sections render, the failed row shows the Failed pill, the pending row offers Approve and Deny buttons, typing in the search box hides the non-matching row.
- [ ] **Step 2**: run to fail, implement, all suites green, tsc 4.
- [ ] **Step 3**: tick inventory lines (Jinja requests, approveReq/denyReq, deleteRequest/purgeRequest, AutoApprovePanel). Commit `feat(admin): native Requests tab with approvals and auto-approve rules`.

---

### Task 8: Maintenance and Blacklist tabs

**Files:**
- Create: `frontend/src/pages/admin/Maintenance.tsx`, `frontend/src/pages/admin/Blacklist.tsx`
- Modify: `frontend/src/pages/admin/AdminLayout.tsx`
- Modify: `frontend/src/api.ts` (POST helpers for the maintenance actions and blacklist; most are plain `POST /ui/<action>` form posts today - wrap them as `http(path, {method:'POST'})` members; the repair feed client for `/ui/api/repair`)
- Test: `frontend/src/pages/admin/Maintenance.test.tsx`, `frontend/src/pages/admin/Blacklist.test.tsx`

**Interfaces:**
- Consumes: the 14 Jinja maintenance actions (`/ui/repair-all`, `/ui/run-cleanup`, `/ui/auto-upgrade`, `/ui/pack-consolidate`, `/ui/merge-series`, `/ui/sync-movies`, `/ui/library-import`, `/ui/refresh-images`, `/ui/generate-nfos`, `/ui/db-vacuum`, `/ui/recovery`, plus the JS `fixImdbTitles`, `repairTvshowTitles` -> `/ui/api/repair-tvshow-titles`, `clearRetryQueue` -> `/ui/api/retry-queue/clear`), `/ui/api/repair` (summary + items, from the 0.7.7 work), `/ui/add-magnet`, `/ui/torbox-delete`, `/ui/backup-restore`, `/ui/show-override-delete/<imdb>`, `ArrImportPanel`'s endpoints (`arr-import/*`), the blacklist list route (find it: `grep -n "blacklist" app.py | grep route`) and `/ui/blacklist-clear/<hash>`; `Card`, `DataTable`, `Pill`.
- Produces: `Maintenance`, `Blacklist` default exports.

**Maintenance layout:** action cards grouped as the Jinja page groups them (Library / Repair / Database / Danger), each button a mutation POST with a pending state and the same `confirm()` guard text where the Jinja form had one (`onsubmit="return confirm(...)"`, copy the strings verbatim from `templates/ui.html`); below them the repair history (five summary stats + the repair table with search, fed by `/ui/api/repair`, `refetchInterval: 120_000` matching the Jinja cadence); then the ArrImportPanel port; then Add magnet (input + submit), TorBox delete, Backup restore, Show override delete, each a small card.

**Blacklist:** table of hashes (hash mono truncated, failures, last error, last try) with a per-row Clear button posting to `/ui/blacklist-clear/<hash>`.

- [ ] **Step 1: failing tests**: Maintenance asserts the four group headings render, a named action button exists per group (pick Run cleanup, Repair strm files, Vacuum DB, Recovery wizard), the repair summary renders from a mocked `/ui/api/repair` payload, and the confirm-guarded action does NOT fire its mutation when `window.confirm` is mocked false. Blacklist asserts rows render and Clear exists per row.
- [ ] **Step 2**: run to fail, implement, suites green, tsc 4.
- [ ] **Step 3**: tick the inventory lines (largest single set). Commit `feat(admin): native Maintenance and Blacklist tabs`.

---

### Task 9: Scrapers and Logs tabs

**Files:**
- Create: `frontend/src/pages/admin/Scrapers.tsx`, `frontend/src/pages/admin/Logs.tsx`
- Modify: `frontend/src/pages/admin/AdminLayout.tsx`
- Modify: `frontend/src/api.ts` (zilean status/sync/import clients if absent)
- Test: `frontend/src/pages/admin/Scrapers.test.tsx`, `frontend/src/pages/admin/Logs.test.tsx`

**Interfaces:**
- Consumes: `api.scraperHealth` (Task 2), `api.adminLogs` (Task 3), the zilean endpoints the Jinja JS calls (`zileanStatus`/`zileanSync`/`zileanImport`: find their routes with `grep -n "zilean" app.py | grep route`); `Card`, `Pill`, `StatusDot`, `DataTable`.
- Produces: `Scrapers`, `Logs` default exports.

**Scrapers:** one row per scraper: `StatusDot` (ok -> ok, slow -> warn, down/unknown -> danger/muted), name, median latency in mono ("212 ms", "1.4 s" over 1000, "-" when null), state `Pill` (ok -> ready, slow -> queued, down -> failed, unknown -> lazy), sample count in muted. `refetchInterval: 30_000`. Below: the Zilean panel (status readout, Sync now, Import from Postgres) ported from the Jinja controls.

**Logs:** level filter chips (All, INFO, WARNING, ERROR), a mono scroll region rendering `time level [name] msg` with level colours (`INFO -> ok`, `WARNING -> warn`, `ERROR -> danger` on the level token), auto-scroll to bottom on new data unless the user scrolled up, and **polling at 5s only while visible**: `refetchInterval: 5_000` combined with `document.visibilityState` via React Query's `refetchIntervalInBackground: false` default PLUS pausing when the tab component unmounts (which hash-switching does automatically since only the active tab renders). A code comment carries the 5s justification per the refresh policy.

- [ ] **Step 1: failing tests**: Scrapers asserts three mocked scrapers render with their latencies and the down one shows the failed pill. Logs asserts mocked lines render, the ERROR filter hides INFO lines (client-side is fine: pass `level` to the query and mock accordingly), and the poll interval is 5000 (assert on the component's exported `LOGS_POLL_MS` constant to keep it testable).
- [ ] **Step 2**: run to fail, implement, suites green, tsc 4.
- [ ] **Step 3**: tick inventory lines (zilean controls, logs viewer). Commit `feat(admin): native Scrapers and Logs tabs`.

---

### Task 10: Filter rules tab

**Files:**
- Create: `frontend/src/pages/admin/filterRulesModel.ts`
- Create: `frontend/src/pages/admin/FilterRules.tsx`
- Modify: `frontend/src/pages/admin/AdminLayout.tsx`
- Test: `frontend/src/pages/admin/filterRulesModel.test.ts`, `frontend/src/pages/admin/FilterRules.test.tsx`

**Interfaces:**
- Consumes: `static/admin/filter_rules.js` (the shipped C2 editor: pure model `parseList, serializeList, buildState, assign, reorder, assignedValues, availableFor, invalidValues, isEmpty, toFormFields, displayValue, visibleChips, STATE_NAMES, STATE_LABELS, LANGUAGE_NAMES, CHIP_VISIBLE_LIMIT`), `GET /ui/api/settings` (the `filter_rules` group: 35 items with `key`, `kind`, `options`, `value`), `POST /ui/settings` form-encoded `setting_<KEY>` fields; `Chip`, `Toggle`, `Card`.
- Produces: `FilterRules` default export.

**The port ruling (binding):** the Jinja settings page still loads `static/admin/filter_rules.js` until Plan 4 deletes the templates, so the file cannot move. The pure state model is REWRITTEN in TypeScript as `filterRulesModel.ts`, function-for-function, and behavioural equivalence is proven by test: `filterRulesModel.test.ts` `require()`s the original via `createRequire` and asserts, for a matrix of operations, that the TS port returns deeply-equal results. The original file and its 34 node tests stay byte-identical; `node --test tests/js/filter_rules.test.js` still passing unchanged is part of this task's gate.

- [ ] **Step 1: the equivalence test**

`filterRulesModel.test.ts`: `import { createRequire } from 'node:module'; const legacy = createRequire(import.meta.url)('../../../../static/admin/filter_rules.js');` then for each of: `parseList` on `"1080p, 2160p ,"` and `""`; `buildState` -> `assign` a value to each of the four states -> `toFormFields`; `reorder` up and down at the edges; `availableFor` and `invalidValues` with overlapping assignments; `visibleChips` under and over `CHIP_VISIBLE_LIMIT`; `displayValue` for a language code and a plain value: assert `expect(ported.X(...)).toEqual(legacy.X(...))`. Run to fail (module missing), then port.

- [ ] **Step 2: port the model**

`filterRulesModel.ts`: the pure functions from `static/admin/filter_rules.js` translated to typed TS (no DOM code: `renderPanel`, `renderCollapsed`, `syncHiddenInputs`, `initFilterRules` are NOT ported; React replaces them). Keep semantics identical; the equivalence test is the referee.

- [ ] **Step 3: the component**

`FilterRules.tsx`: fetch the `filter_rules` group from `/ui/api/settings`; seven category panels (RESOLUTION, SOURCE, ENCODE, VISUAL_TAG, AUDIO_TAG, AUDIO_CHANNELS, LANGUAGE), each a `Card` with: header (category name, total value count, `Toggle` for `_STRICT`), four chip rows (Preferred with reorder arrows on each chip, Excluded, Required, Included with the standing warning "overrides every other rule in every category - use deliberately" in `text-warn text-[11px]`), values added from a dropdown of `availableFor(state)`, removable via `Chip onRemove`, long rows collapsed behind `+N more` per `visibleChips`. Save all: one button building `toFormFields` for every category and POSTing form-encoded to `/ui/settings` (match the Jinja submission exactly: `application/x-www-form-urlencoded`, `setting_<KEY>` names, plus whatever CSRF field the existing form sends: read the Jinja form's hidden fields first). `FilterRules.test.tsx` asserts: seven panels render from a mocked settings payload; adding a value via the dropdown appends a chip; the Included row shows the warning; save serializes a changed category into `setting_RESOLUTION_PREFERRED` form data (spy on fetch).

- [ ] **Step 4**: `cd frontend && npm test` green including equivalence; `node --test tests/js/filter_rules.test.js` 34 unchanged; tsc 4. Tick the inventory's filter-rules lines. Commit `feat(admin): native Filter rules tab porting the C2 editor model`.

---

### Task 11: Settings tab

**Files:**
- Create: `frontend/src/pages/admin/Settings.tsx`
- Modify: `frontend/src/pages/admin/AdminLayout.tsx`
- Test: `frontend/src/pages/admin/Settings.test.tsx`

**Interfaces:**
- Consumes: `GET /ui/api/settings` (all groups from `settings.all_for_ui()`: each group `{id, title, items:[{key, kind, value, options, hot_reload, overridden, ...}]}`; read `settings.py:485` for the exact shape), `POST /ui/settings` (form-encoded, same contract as Task 10), `/ui/api/auto-add-now`, and `Admin.tsx`'s `DiscoverGenreTabsPanel` (ported whole); `Card`, `Toggle`, `Chip`.
- Produces: `Settings` default export (the ADMIN settings tab; distinct from `pages/Settings.tsx`, the user-facing page).

Renders every group EXCEPT `filter_rules` (Task 10 owns it): group cards in `all_for_ui` order, each item a row (label = key, hot-reload lightning vs restart-required warning glyphs exactly as the Jinja page shows them, override marker when `overridden`), controls by `kind`: bool -> `Toggle`, enum -> select over `options`, list -> comma text input, everything else -> text input. One sticky "Save all" bar POSTing the full form-encoded set (changed keys only is NOT the Jinja behaviour; it posts everything: match it). "Run auto-add now" beside it. The `mode` group's custom card treatment in the Jinja page (radio-style cards) is ported as a radio row. Then `DiscoverGenreTabsPanel` moved from `Admin.tsx` verbatim in behaviour, restyled.

- [ ] **Step 1: failing test**: mocked settings payload with two groups (one bool item, one enum item) asserts both groups render, the bool renders a checkbox role, the enum a combobox, `filter_rules` group is absent even when the payload contains it, and Save all posts form-encoded data containing `setting_<KEY>` for both items (fetch spy).
- [ ] **Step 2**: run to fail, implement, suites green, tsc 4.
- [ ] **Step 3**: tick inventory lines (settings groups, Save all, auto-add now, genre tabs). Commit `feat(admin): native runtime Settings tab`.

---

### Task 12: Discharge and gate

**Files:**
- Delete: `frontend/src/pages/Admin.tsx`, `frontend/src/pages/AdminTabs.tsx`
- Modify: `docs/superpowers/specs/assets/2026-08-31-admin-inventory.md` (final state)
- Modify: `static/app/` (rebuild)

- [ ] **Step 1: Discharge the inventory**

Open the inventory. Every line must be ticked or carry an explicit `retained-in-Jinja: <reason>` annotation. An unticked, unannotated line is a BLOCKED state: report it instead of proceeding.

- [ ] **Step 2: Delete the superseded pages**

`git rm frontend/src/pages/Admin.tsx frontend/src/pages/AdminTabs.tsx`. Run `grep -rn "pages/Admin'\|pages/AdminTabs" frontend/src` - nothing may import them.

- [ ] **Step 3: Full sweep**

```bash
./.venv-sdd/bin/python -m pytest tests/ -q          # expect 471
node --test tests/js/filter_rules.test.js            # expect 34, file unchanged: git diff --quiet tests/js/ static/admin/
cd frontend && npm test && npx tsc --noEmit          # all green; 4 pre-existing errors
grep -rnE "text-red-|bg-red-|text-green-|bg-green-|text-yellow-|bg-yellow-|text-blue-|bg-blue-|zinc-|indigo-" frontend/src/pages/admin --include='*.tsx'   # nothing
```

- [ ] **Step 4: Build and commit**

```bash
cd frontend && npm run build
cd .. && git add -A && git commit -m "feat(admin): the native admin replaces the split-brain pair

Admin.tsx and AdminTabs.tsx retire; the Jinja dashboard remains reachable
at /admin via Flask until plan 4 completes the cutover."
```

State in the report: the discharged inventory counts, any retained-in-Jinja lines with reasons, and that in-browser verification of every tab against live data is deferred to the user (spec: manual VPS verification list).

## Done when

- The inventory is fully discharged (ticked or annotated).
- All suites green: 471 Python, 34 JS (file untouched), frontend all passing, tsc at 4.
- `/admin` in the SPA renders the nine-tab native admin; `Admin.tsx` and `AdminTabs.tsx` are gone.
- `static/app/` rebuilt and committed.
