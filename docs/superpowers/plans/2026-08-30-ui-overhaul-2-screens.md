# UI Overhaul, Plan 2: The React Screens Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle and relayout the seven reachable React screens (Discover, Library, Watchlist, Search, Requests, Wanted, Settings) plus the poster components and DetailModal, against the Plan 1 design system, and add the `me/quota` endpoint the Requests screen needs.

**Architecture:** Every screen is assembled from the Plan 1 primitives (`Pill`, `Chip`, `StatTile`, `DataTable`, `Card`, `Toggle`, `StatusDot`) and tokens; no new colours, no new spacing systems. New visual structures (the Discover hero, the Watchlist source cards, the Requests quota card) are new components with their own Vitest files. `DetailModal.tsx` (545 lines) splits into a directory of focused files. Pages keep their existing queries and mutations; this plan changes what they render, not what they fetch, except where the spec adds data (quota).

**Tech Stack:** React 18, TypeScript, Tailwind 3.4 (Plan 1 palette), React Query 5, Vitest + Testing Library, Flask 3 / Python 3.12 for the quota endpoint.

**Spec:** `docs/superpowers/specs/2026-08-30-ui-overhaul-design.md`

**Plan 2 of 4.** Requires Plan 1 (complete on `feat/ui-overhaul` at 3c5e58c). Plans 3 (Admin) and 4 (pre-auth cutover) follow.

**Ruling carried from Plan 1:** `Login.tsx` is NOT in this plan even though the spec counts it among the eight React screens. It is unreachable until Plan 4's cutover makes Flask stop serving `/login`, so its restyle lands there, next to the change that makes it visible. Its old-palette logo SVG stays until then.

**Ruling carried from Plan 1 (binding on every page task):** `border` and `muted` changed KIND in the palette (opaque hex to rgba), so every `/NN` opacity-modifier usage of them (`border-border/50`, `placeholder-muted/60`, `text-muted/70`, ...) silently changed meaning. Every task that touches a page file must sweep that file for `/` modifiers on `border`, `muted`, `accent`, `ok`, `warn`, `danger` and replace them with the unmodified token unless the task text says otherwise.

## Global Constraints

- **Never use em-dashes**, anywhere, in code or prose. Use a comma, a colon, parentheses, or " - ". Applies to code comments, commit messages and documentation.
- **The repository is public.** No passwords, tokens, API keys or IP addresses in any commit.
- **Work on branch `feat/ui-overhaul`.** Do not commit to `main`.
- **No `Co-Authored-By` lines.** Every commit message body ends with exactly:
  `Claude-Session: https://claude.ai/code/session_01S7W5TTdnwd8hdgj3L3dnnx`
- **`static/app/` rebuilds land at the final task only** (Task 11), matching the Plan 1 ruling; interim tasks do not run `npm run build`.
- **Every number rendered maps to a real endpoint** or it is not rendered. The metric substitution table in the spec is binding; the relevant rows are copied into Tasks 5 and 8.
- **Refresh policy (spec):** no route ever reloads itself; background refetch keeps rendered data mounted (never swap mounted content for a spinner on refetch: gate spinners on `isLoading`, never `isFetching`); polling only while the panel is visible.
- **Tests:** Python via `./.venv-sdd/bin/python -m pytest tests/ -q` (venv lacks APScheduler: nothing may `import app`; route registration is asserted against `app.py` source). Frontend via `cd frontend && npm test`. JS via `node --test tests/js/filter_rules.test.js`.
- `npx tsc --noEmit` has exactly 6 pre-existing errors in `PosterCard.tsx`, `usePluginSlots.ts`, `Watchlist.tsx`. Tasks that rewrite those files are expected to FIX their share; no task may add new errors.
- **Do not change any query key, mutation, or endpoint a page already uses** unless the task text says so; this plan is presentation plus the one new endpoint.

## File Structure

| File | Responsibility |
|---|---|
| `quota.py` | create: quota payload builder, importable without Flask |
| `app.py` | modify: `GET /ui/api/me/quota` beside `ui_api_shell_summary` |
| `tests/test_quota.py` | create |
| `frontend/src/api.ts` | modify: `myQuota()` + `QuotaInfo` type |
| `frontend/src/components/PosterCard.tsx` | rewrite: token badges, fixes its pre-existing tsc error |
| `frontend/src/components/PosterGrid.tsx` | restyle in place |
| `frontend/src/components/DetailModal/` | split of `DetailModal.tsx`: `index.tsx`, `Header.tsx`, `Seasons.tsx`, `Cast.tsx`, `Similar.tsx` |
| `frontend/src/components/discover/Hero.tsx` | create |
| `frontend/src/components/watchlist/SourceCard.tsx` | create |
| `frontend/src/components/requests/QuotaCard.tsx` | create |
| `frontend/src/pages/*.tsx` | restyled per task |

Deleted at the end: `frontend/src/components/DetailModal.tsx` (replaced by the directory).

---

### Task 1: The quota endpoint

**Files:**
- Create: `quota.py`
- Modify: `app.py` (immediately after `ui_api_shell_summary`)
- Modify: `frontend/src/api.ts`
- Test: `tests/test_quota.py`

**Interfaces:**
- Consumes: `db.count_user_requests_this_month(user_id) -> int` (exists, `db.py:1656`), `auth.current_user_record()`, the `users` row field `quota_monthly` (0 means unlimited).
- Produces:
  - Python: `quota.get_quota(user: dict | None) -> dict` returning `{"used": int, "limit": int, "resets_at": "YYYY-MM-01T00:00:00Z", "unlimited": bool}`.
  - HTTP: `GET /ui/api/me/quota`.
  - TypeScript: `api.myQuota(): Promise<QuotaInfo>` with `export type QuotaInfo = { used: number; limit: number; resets_at: string; unlimited: boolean }`.

Task 8 consumes `api.myQuota` for the quota card.

- [ ] **Step 1: Write the failing test**

`tests/test_quota.py`:

```python
"""The Requests page shows 'N of M requests, resets in X days'.

limit comes from users.quota_monthly, where 0 has always meant 'no cap';
the endpoint surfaces that as unlimited=true rather than a zero limit the
UI would render as '14 of 0'.
"""
import os
import sys
from datetime import datetime, timezone

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db
import quota


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


def _user(quota_monthly=25):
    uid = db.create_user("adam", "x" * 32, role="user", quota_monthly=quota_monthly)
    return {"id": uid, "quota_monthly": quota_monthly}


def test_shape_for_a_capped_user_with_no_requests():
    d = quota.get_quota(_user(25))
    assert d["used"] == 0
    assert d["limit"] == 25
    assert d["unlimited"] is False


def test_used_counts_only_this_users_rows_this_month():
    u = _user(25)
    other = db.create_user("someone", "y" * 32, role="user")
    db.create_user_request(u["id"], "tt0000001", None, "A", "movie")
    db.create_user_request(u["id"], "tt0000002", None, "B", "movie")
    db.create_user_request(other, "tt0000003", None, "C", "movie")

    assert quota.get_quota(u)["used"] == 2


def test_zero_quota_means_unlimited_not_a_zero_cap():
    d = quota.get_quota(_user(0))
    assert d["unlimited"] is True
    assert d["limit"] == 0


def test_resets_at_is_the_first_of_next_month_utc():
    d = quota.get_quota(_user(25))
    resets = datetime.fromisoformat(d["resets_at"].replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    assert resets > now
    assert resets.day == 1
    assert resets.hour == 0 and resets.minute == 0
    assert (resets.year, resets.month) in {
        (now.year, now.month % 12 + 1),
        (now.year + 1, 1),
    }


def test_a_userless_session_gets_the_unlimited_shape():
    """Trusted-proxy logins can have no user row. The card hides itself on
    unlimited, which is the right rendering for 'we cannot attribute you'."""
    d = quota.get_quota(None)
    assert d == {"used": 0, "limit": 0, "resets_at": d["resets_at"], "unlimited": True}


def test_the_endpoint_is_registered():
    with open(os.path.join(os.path.dirname(__file__), "..", "app.py"), encoding="utf-8") as f:
        src = f.read()
    assert '@app.get("/ui/api/me/quota")' in src
    assert "quota.get_quota(" in src
```

Check `db.create_user` and `db.create_user_request` signatures with `grep -n "def create_user\b\|def create_user_request" db.py` before running; adapt the fixture calls to the real positional order (they exist, `db.py:1481` and `db.py:1603`), never the assertions.

- [ ] **Step 2: Run it to verify it fails**

Run: `./.venv-sdd/bin/python -m pytest tests/test_quota.py -q`
Expected: FAIL, `No module named 'quota'`.

- [ ] **Step 3: Implement**

`quota.py`:

```python
"""Monthly request quota for the Requests page card.

users.quota_monthly of 0 has always meant 'no cap'; that surfaces here as
unlimited=true so the UI hides the card instead of rendering '14 of 0'.
"""
from datetime import datetime, timezone


def _first_of_next_month() -> str:
    now = datetime.now(timezone.utc)
    year, month = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    return f"{year:04d}-{month:02d}-01T00:00:00Z"


def get_quota(user: dict | None) -> dict:
    import db

    limit = int(user.get("quota_monthly") or 0) if user else 0
    used = db.count_user_requests_this_month(user["id"]) if user else 0
    return {
        "used": used,
        "limit": limit,
        "resets_at": _first_of_next_month(),
        "unlimited": limit == 0,
    }
```

In `app.py`, immediately after the `ui_api_shell_summary` handler:

```python
@app.get("/ui/api/me/quota")
def ui_api_me_quota():
    """Monthly request quota for the current user, for the Requests page."""
    return jsonify(quota.get_quota(auth.current_user_record()))
```

with `import quota` beside the other module imports.

- [ ] **Step 4: Run the tests**

Run: `./.venv-sdd/bin/python -m pytest tests/test_quota.py -q` then the full suite `./.venv-sdd/bin/python -m pytest tests/ -q`
Expected: 6 new tests pass; full suite 456 passed.

- [ ] **Step 5: Add the client**

In `frontend/src/api.ts`, beside `myRequests`:

```ts
  myQuota: () => http<QuotaInfo>('/ui/api/me/quota'),
```

and with the exported types:

```ts
export type QuotaInfo = { used: number; limit: number; resets_at: string; unlimited: boolean };
```

Run: `cd frontend && npm test` (all green, nothing consumed it yet).

- [ ] **Step 6: Commit**

```bash
git add quota.py app.py tests/test_quota.py frontend/src/api.ts
git commit -m "feat(api): monthly request quota endpoint for the Requests page"
```

---

### Task 2: PosterCard and PosterGrid restyle

**Files:**
- Rewrite: `frontend/src/components/PosterCard.tsx`
- Modify: `frontend/src/components/PosterGrid.tsx`
- Test: `frontend/src/components/PosterCard.test.tsx`

**Interfaces:**
- Consumes: tokens; `tmdbImg.poster`; `useWatched`.
- Produces: `PosterCard({ item, onClick, status }: { item: TmdbItem; onClick: (item: TmdbItem) => void; status?: string | null })`, default export, signature unchanged so every caller keeps working.

The spec's badge treatment: corner badges `IN LIBRARY` (green, `rgba(37,140,96,0.85)` bg) and `REQUESTED` (purple, `rgba(97,82,223,0.88)` bg), white text, backdrop blur. The current `STATUS_STYLES` map uses Tailwind stock colours (`bg-green-600`, `bg-yellow-600`, `bg-blue-600`, `bg-red-600`) that bypass the palette.

This file also carries 2 of the 6 pre-existing tsc errors; the rewrite must leave `npx tsc --noEmit` with only the 4 errors in `usePluginSlots.ts` and `Watchlist.tsx`.

- [ ] **Step 1: Find the pre-existing tsc errors**

Run: `cd frontend && npx tsc --noEmit 2>&1 | grep PosterCard`
Note both errors; the rewrite fixes them (they are type-level, not behavioural).

- [ ] **Step 2: Write the failing test**

`frontend/src/components/PosterCard.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import PosterCard from './PosterCard';
import type { TmdbItem } from '../types';

vi.mock('../hooks/useWatched', () => ({ useWatched: () => new Set(['tt0000001']) }));

const item = (over: Partial<TmdbItem> = {}): TmdbItem => ({
  tmdb_id: 1, media_type: 'movie', title: 'Dune', year: '2021', rating: 8.1,
  votes: 100, popularity: 5, overview: '', poster_path: null, backdrop_path: null,
  ...over,
});

describe('PosterCard badges', () => {
  it('shows IN LIBRARY for success and available', () => {
    for (const status of ['success', 'available']) {
      const { unmount } = render(<PosterCard item={item()} onClick={() => {}} status={status} />);
      expect(screen.getByText('IN LIBRARY')).toBeInTheDocument();
      unmount();
    }
  });

  it('shows REQUESTED for pending', () => {
    render(<PosterCard item={item()} onClick={() => {}} status="pending" />);
    expect(screen.getByText('REQUESTED')).toBeInTheDocument();
  });

  it('shows WANTED, UPCOMING and FAILED in token colours, never stock tailwind', () => {
    const { container } = render(<PosterCard item={item()} onClick={() => {}} status="failed" />);
    expect(screen.getByText('FAILED')).toBeInTheDocument();
    expect(container.innerHTML).not.toMatch(/bg-(green|yellow|blue|red)-\d/);
  });

  it('renders no badge for an unknown status', () => {
    const { container } = render(<PosterCard item={item()} onClick={() => {}} status="bogus" />);
    expect(container.querySelector('[data-badge]')).toBeNull();
  });

  it('still marks watched items', () => {
    render(<PosterCard item={item({ imdb_id: 'tt0000001' } as any)} onClick={() => {}} />);
    expect(screen.getByTitle('Watched')).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd frontend && npm test -- PosterCard`
Expected: FAIL (current badges render `In library`, not `IN LIBRARY`).

- [ ] **Step 4: Rewrite the badge map and card chrome**

In `PosterCard.tsx`, replace `STATUS_STYLES` and `StatusBadge` with:

```tsx
const BADGES: Record<string, { bg: string; label: string }> = {
  success:   { bg: 'rgba(37,140,96,0.85)',  label: 'IN LIBRARY' },
  available: { bg: 'rgba(37,140,96,0.85)',  label: 'IN LIBRARY' },
  pending:   { bg: 'rgba(97,82,223,0.88)',  label: 'REQUESTED' },
  wanted:    { bg: 'rgba(198,178,83,0.85)', label: 'WANTED' },
  upcoming:  { bg: 'rgba(97,82,223,0.55)',  label: 'UPCOMING' },
  failed:    { bg: 'rgba(209,71,71,0.85)',  label: 'FAILED' },
};

function StatusBadge({ status }: { status: string }) {
  const s = BADGES[status];
  if (!s) return null;
  return (
    <div
      data-badge
      className="absolute top-2 left-2 rounded-md px-1.5 py-1 text-[9px] font-semibold tracking-wide
                 text-white backdrop-blur-sm"
      style={{ background: s.bg }}
    >
      {s.label}
    </div>
  );
}
```

Card chrome edits, keeping everything else (placeholder gradient, watched dot, TV/Movie corner tag, title gradient) as it is:
- root button: `rounded-lg` becomes `rounded-xl`; keep the hover translate and shadow.
- the TV/Movie tag: `bg-accent/90` stays for TV, `bg-black/70` stays for Movie.
- rating chip: `bg-warn/90 text-black` becomes an inline style `background: 'rgba(198,178,83,0.9)', color: '#070707'` (the `/90` modifier on the now-solid `warn` is fine, but the inline form keeps it identical to the badge family; either way remove nothing else).
- watched dot: `bg-green-500/90` becomes inline `background: 'rgba(37,140,96,0.9)'`.
- fix the two tsc errors found in Step 1 (typically the `imdb_id` access on `TmdbItem`: add `imdb_id?: string | null` to the `TmdbItem` interface in `types.ts` if that is what tsc names, and type `useWatched`'s return where accessed).

In `PosterGrid.tsx`: `rounded-lg` on nothing to change structurally; sweep the file for `/NN` modifiers per the carried ruling (`from-bg/90` on the scroll affordances is a modifier on `bg`, which stayed an opaque hex: keep it) and leave the rest alone.

- [ ] **Step 5: Run the tests and the type check**

Run: `cd frontend && npm test -- PosterCard && npx tsc --noEmit 2>&1 | grep -c "error TS"`
Expected: tests pass; error count is 4 and none mention PosterCard.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/PosterCard.tsx frontend/src/components/PosterGrid.tsx frontend/src/components/PosterCard.test.tsx frontend/src/types.ts
git commit -m "feat(ui): poster badges move to the token palette

IN LIBRARY green and REQUESTED purple per the mockup, and the stock
tailwind greens and yellows leave the codebase. Also clears the two
pre-existing tsc errors this file carried."
```

---

### Task 3: DetailModal split and restyle

**Files:**
- Create: `frontend/src/components/DetailModal/index.tsx`, `Header.tsx`, `Seasons.tsx`, `Cast.tsx`, `Similar.tsx`
- Delete: `frontend/src/components/DetailModal.tsx`
- Test: `frontend/src/components/DetailModal/DetailModal.test.tsx`

**Interfaces:**
- Consumes: primitives (`Pill`, `Card`); existing queries inside the modal (details, watchlist, session) unchanged.
- Produces: default export `DetailModal({ tmdbId, mediaType, onClose, onSelectItem })` with the exact current signature, re-exported from `DetailModal/index.tsx` so the existing `import DetailModal from '../components/DetailModal'` in Discover, Library, Watchlist and Search resolves to the directory without any caller edits.

This is a refactor-then-restyle, in that order: FIRST mechanically split the 545-line file into the directory with zero behaviour change and verify, THEN restyle.

- [ ] **Step 1: Write the seam test**

`frontend/src/components/DetailModal/DetailModal.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import DetailModal from './index';

vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return {
    ...actual,
    api: {
      ...actual.api,
      details: () => Promise.resolve({
        tmdb_id: 1, media_type: 'movie', title: 'Dune', year: '2021', rating: 8.1,
        overview: 'Sand.', poster_path: null, backdrop_path: null, runtime: 155,
        genres: ['Sci-Fi'], cast: [], similar: [], seasons: [],
        library_status: 'success', imdb_id: 'tt1160419',
      }),
      watchlist: () => Promise.resolve({ items: [] }),
      session: () => Promise.resolve({ authenticated: true, user: { username: 'adam', role: 'admin' } }),
    },
  };
});

function renderModal() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <DetailModal tmdbId={1} mediaType="movie" onClose={() => {}} onSelectItem={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('DetailModal after the split', () => {
  it('renders title, overview and metadata from the details query', async () => {
    renderModal();
    await waitFor(() => expect(screen.getByText('Dune')).toBeInTheDocument());
    expect(screen.getByText('Sand.')).toBeInTheDocument();
  });

  it('renders nothing at all when closed', () => {
    const qc = new QueryClient();
    const { container } = render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <DetailModal tmdbId={null} mediaType={null} onClose={() => {}} onSelectItem={() => {}} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    expect(container.innerHTML).toBe('');
  });
});
```

Before finalizing the mock, read the top 60 lines of the current `DetailModal.tsx` and the `TmdbDetail` type in `types.ts`; the mocked `details` payload must satisfy the fields the component destructures, or the test fails for mock reasons. Adjust the mock payload fields, never the two assertions.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npm test -- DetailModal`
Expected: FAIL, cannot resolve `./index`.

- [ ] **Step 3: Mechanical split**

Read `frontend/src/components/DetailModal.tsx` fully. Create the directory and move code with NO edits beyond imports:

- `DetailModal/index.tsx`: the default component, its queries, the keyboard/escape handling, the modal shell and backdrop, composing the section components below. Also move `LibraryButton` here (it is only used by the header actions).
- `DetailModal/Header.tsx`: the poster + title + metadata row + action buttons block (the `flex flex-col sm:flex-row gap-6` region and its children), exported as `Header` taking exactly the props it reads (`detail`, plus the callbacks and query data it uses; derive the prop list from what the moved JSX references).
- `DetailModal/Seasons.tsx`: the seasons section (`<h3>Seasons</h3>` region).
- `DetailModal/Cast.tsx`: the cast strip (`<h3>Cast</h3>` region) including its PersonModal wiring if the state lives there; if the `PersonModal` state lives in the parent, pass the setter down.
- `DetailModal/Similar.tsx`: the "You might also like" strip and the "Streaming on" block (one file, two small exports `Similar` and `StreamingOn`).

Delete `frontend/src/components/DetailModal.tsx`. The import specifier `'../components/DetailModal'` now resolves to the directory's `index.tsx`; verify no caller changes are needed with `grep -rn "components/DetailModal" frontend/src --include='*.tsx' | grep -v "components/DetailModal/"`.

- [ ] **Step 4: Verify the split alone**

Run: `cd frontend && npm test && npx tsc --noEmit 2>&1 | grep -c "error TS"`
Expected: all tests pass including the new ones; error count 4 (the pre-existing usePluginSlots + Watchlist ones), nothing from the new directory.

Commit the mechanical split on its own:

```bash
git add frontend/src/components/DetailModal/ && git rm frontend/src/components/DetailModal.tsx
git commit -m "refactor(ui): split the 545-line DetailModal into a directory

Mechanical move, no behaviour change; the directory index keeps the old
import specifier working for all four callers."
```

- [ ] **Step 5: Restyle**

Now restyle the split files with tokens:
- modal surface: `bg-card border border-border rounded-xl`; backdrop `bg-black/70 backdrop-blur-sm`.
- the status/quality chips row in the header: replace ad-hoc spans with `Pill` where the value is one of the five states, plain token-coloured spans otherwise.
- section headings (`Seasons`, `Cast`, `You might also like`, `Streaming on`): `text-[11px] font-semibold uppercase tracking-wider text-muted mb-2`.
- action buttons: primary `bg-accent hover:bg-accent-light text-white rounded-lg px-4 py-2 text-sm font-medium`; secondary same shape with `bg-transparent border border-border text-body hover:border-accent-light/50` (this `/50` on `accent-light`, an opaque hex, is fine).
- sweep every moved file for `/NN` modifiers on `border` and `muted` per the carried ruling.

Run: `cd frontend && npm test` (all green).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/DetailModal/
git commit -m "feat(ui): DetailModal restyled to the token palette"
```

---

### Task 4: Discover hero

**Files:**
- Create: `frontend/src/components/discover/Hero.tsx`
- Modify: `frontend/src/pages/Discover.tsx`
- Test: `frontend/src/components/discover/Hero.test.tsx`

**Interfaces:**
- Consumes: `api.trending('all', 'week')` (`{ results: TmdbItem[] }`), `api.details(type, id)` (`TmdbDetail` with `runtime?: number`, `genres?: string[]`), `tmdbImg.backdrop` (w1280), `Pill`.
- Produces: `Hero({ onRequest, onOpen }: { onRequest: (item: TmdbItem) => void; onOpen: (item: TmdbItem) => void })` named export. `Discover.tsx` renders it above the existing rows.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/discover/Hero.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi } from 'vitest';
import { Hero } from './Hero';

const top = {
  tmdb_id: 42, media_type: 'movie', title: 'Dune: Part Three', year: '2026',
  rating: 8.4, votes: 900, popularity: 99, overview: 'Sand again.',
  poster_path: null, backdrop_path: '/bd.jpg', library_status: null,
};

vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return {
    ...actual,
    api: {
      ...actual.api,
      trending: () => Promise.resolve({ results: [top] }),
      details: () => Promise.resolve({ ...top, runtime: 166, genres: ['Sci-Fi', 'Adventure'] }),
    },
  };
});

function renderHero() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <Hero onRequest={() => {}} onOpen={() => {}} />
    </QueryClientProvider>,
  );
}

describe('Hero', () => {
  it('features the top trending title with its metadata', async () => {
    renderHero();
    await waitFor(() => expect(screen.getByText('Dune: Part Three')).toBeInTheDocument());
    expect(screen.getByText('Trending #1 this week')).toBeInTheDocument();
    expect(screen.getByText('8.4')).toBeInTheDocument();
    expect(screen.getByText('2h 46m')).toBeInTheDocument();
    expect(screen.getByText(/Sci-Fi/)).toBeInTheDocument();
  });

  it('offers Request and Watchlist actions', async () => {
    renderHero();
    await waitFor(() => expect(screen.getByRole('button', { name: 'Request title' })).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Watchlist' })).toBeInTheDocument();
  });

  it('renders nothing while trending has not resolved', () => {
    const { container } = renderHero();
    expect(container.textContent).toBe('');
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npm test -- Hero`
Expected: FAIL, cannot resolve `./Hero`.

- [ ] **Step 3: Implement**

`frontend/src/components/discover/Hero.tsx`:

```tsx
import { useQuery } from '@tanstack/react-query';
import { api, tmdbImg } from '../../api';
import type { TmdbItem } from '../../types';

function fmtRuntime(min?: number) {
  if (!min) return null;
  return `${Math.floor(min / 60)}h ${min % 60}m`;
}

export function Hero({
  onRequest,
  onOpen,
}: {
  onRequest: (item: TmdbItem) => void;
  onOpen: (item: TmdbItem) => void;
}) {
  const { data: trending } = useQuery({
    queryKey: ['trending', 'all', 'week'],
    queryFn: () => api.trending('all', 'week'),
    staleTime: 5 * 60_000,
  });
  const top = trending?.results?.[0];
  const { data: detail } = useQuery({
    queryKey: ['hero-detail', top?.media_type, top?.tmdb_id],
    queryFn: () => api.details(top!.media_type, top!.tmdb_id),
    enabled: !!top,
    staleTime: 5 * 60_000,
  });

  if (!top) return null;

  const backdrop = tmdbImg.backdrop(top.backdrop_path);
  const runtime = fmtRuntime(detail?.runtime);
  const genres = detail?.genres?.slice(0, 3).join(' · ');

  return (
    <section
      className="relative -mx-4 lg:-mx-8 mb-8 overflow-hidden"
      aria-label="Featured title"
    >
      {backdrop && (
        <img
          src={backdrop}
          alt=""
          aria-hidden="true"
          className="absolute inset-0 h-full w-full object-cover"
        />
      )}
      <div className="absolute inset-0 bg-gradient-to-r from-bg via-bg/70 to-transparent" />
      <div className="absolute inset-0 bg-gradient-to-t from-bg via-transparent to-transparent" />
      <div className="relative px-4 lg:px-8 py-14 lg:py-20 max-w-2xl">
        <div className="mb-3 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider">
          <span className="rounded-md px-2 py-1 text-white" style={{ background: 'rgba(97,82,223,0.88)' }}>
            Featured
          </span>
          <span className="text-accent-pale">Trending #1 this week</span>
        </div>
        <h2 className="text-3xl lg:text-4xl font-bold text-white">{top.title}</h2>
        <div className="mt-3 flex flex-wrap items-center gap-2 text-sm text-body">
          {top.rating > 0 && (
            <span className="rounded px-1.5 py-0.5 font-semibold"
                  style={{ background: 'rgba(198,178,83,0.9)', color: '#070707' }}>
              {top.rating}
            </span>
          )}
          {top.year && <span>{top.year}</span>}
          {runtime && <><span className="text-muted">&middot;</span><span>{runtime}</span></>}
          {genres && <><span className="text-muted">&middot;</span><span>{genres}</span></>}
        </div>
        {top.overview && (
          <p className="mt-3 max-w-xl text-sm leading-relaxed text-muted line-clamp-3">{top.overview}</p>
        )}
        <div className="mt-5 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => onRequest(top)}
            className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-light"
          >
            Request title
          </button>
          <button
            type="button"
            onClick={() => onOpen(top)}
            className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-body hover:border-accent-light/50"
          >
            Watchlist
          </button>
        </div>
      </div>
    </section>
  );
}
```

Note the test's third case: before the trending query resolves, the component returns `null`, so the container is empty; no skeleton, no spinner.

- [ ] **Step 4: Wire into Discover**

In `frontend/src/pages/Discover.tsx`: import `{ Hero }` and render it as the FIRST child of the page's root element, before the provider strip and rows. Wire `onOpen` to the existing detail-modal opener the rows use, and `onRequest` to the same opener (the modal carries the request action; a direct add from the hero would skip the confirmation the modal provides). Relabel the provider strip's section header to `Streaming services` with the sub-line `filter Discover by what your region carries` if the current `SectionHeader` supports a subtitle; if it does not, render the sub-line as a `text-xs text-muted` paragraph under the header. Sweep the file for `/NN` modifiers on `border`/`muted` per the carried ruling.

- [ ] **Step 5: Run the tests**

Run: `cd frontend && npm test`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/discover/ frontend/src/pages/Discover.tsx
git commit -m "feat(ui): full-bleed trending hero on Discover"
```

---

### Task 5: Library

**Files:**
- Modify: `frontend/src/pages/Library.tsx`
- Test: `frontend/src/pages/Library.test.tsx`

**Interfaces:**
- Consumes: `Chip`, `StatTile`, `DataTable`, `Pill`, `Column` from primitives; existing queries (`library-movies`, `library-series-episodes`, `session`, jellyfin items) unchanged; `api.stats()` if present in `api.ts` (check with `grep -n "stats" frontend/src/api.ts`; it exists as the `/ui/api/stats` client or add `stats: () => http<any>('/ui/api/stats')` if the grep shows only the admin variant).
- Produces: nothing consumed downstream.

Binding metric rows (from the spec's substitution table): Titles = `stats.library.movie_count + stats.library.series_count`; Episodes = `stats.library.episode_count`; Success rate 7d = `stats.requests.success_rate_7d`; the fourth mockup tile (catalogued size) requires `/ui/api/torbox-list`, which is slow and admin-flavoured: render only the three stats-backed tiles. Deltas ("+18 this week") have no per-week source in `stats.get_overview()`: do NOT render invented deltas; the tiles show value and label only.

- [ ] **Step 1: Write the failing test**

`frontend/src/pages/Library.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import Library from './Library';

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    api: {
      ...actual.api,
      stats: () => Promise.resolve({
        library: { movie_count: 12, episode_count: 300, series_count: 4 },
        requests: { total: 20, succeeded_7d: 9, failed_7d: 1, success_rate_7d: 90.0 },
        wanted: { active: 2, found: 1, give_up: 0 },
        movies_pending: 0, qualities: {},
      }),
      libraryMovies: () => Promise.resolve({ items: [] }),
      session: () => Promise.resolve({ authenticated: true, user: { username: 'adam', role: 'admin' } }),
    },
  };
});

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><Library /></MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Library stat tiles', () => {
  it('shows Titles as movies plus series, Episodes, and Success rate', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('16')).toBeInTheDocument());
    expect(screen.getByText('300')).toBeInTheDocument();
    expect(screen.getByText('90%')).toBeInTheDocument();
  });

  it('renders no invented delta lines', async () => {
    const { container } = renderPage();
    await waitFor(() => expect(screen.getByText('16')).toBeInTheDocument());
    expect(container.textContent).not.toMatch(/this week/);
  });
});
```

The existing `Library.tsx` mounts several queries (jellyfin items, trakt watched, lazy posters); the mock spreads `actual.api` so unmocked members still exist, and empty `items` keeps those panels quiet. If a query the page always fires is missing from `actual.api`'s runtime shape under jsdom, mock it to an empty resolution the same way; note each addition in the report.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npm test -- Library`
Expected: FAIL (no stat tiles exist).

- [ ] **Step 3: Implement**

In `frontend/src/pages/Library.tsx`:

1. Add the stats query and a tile row rendered above the existing tab strip:

```tsx
const { data: stats } = useQuery({ queryKey: ['stats'], queryFn: api.stats, staleTime: 60_000 });
```

```tsx
{stats && (
  <div className="mb-5 grid grid-cols-1 sm:grid-cols-3 gap-3">
    <StatTile value={String(stats.library.movie_count + stats.library.series_count)} label="Titles" glow="accent" />
    <StatTile value={String(stats.library.episode_count)} label="Episodes" />
    <StatTile value={`${Math.round(stats.requests.success_rate_7d)}%`} label="Success rate 7d" glow="ok" />
  </div>
)}
```

2. Replace the existing type-filter buttons (the `flex gap-1` group inside `MoviesPanel`, and the tab strip if it is the filter surface) with `Chip` from primitives, selected state driven by the same state variable they already toggle. The six mockup chips (All, Movies, Series, Materialized, Lazy, Needs repair) reduce to the filters the page's DATA can actually answer: the existing Movies/Series split plus All. Materialized/Lazy/Needs repair need `virtual_items` state that no current endpoint exposes per-title: do not invent them; note the omission in a code comment referencing Plan 3.
3. Add the table view. A `grid | table` toggle (two small `Chip`s right-aligned above the content, state in `useState<'grid' | 'table'>('grid')`). The table branch renders `DataTable` with columns Title, Year, Quality, State, Added over the SAME items array the grid maps, with `State` rendered as `<Pill state={...}>`: map item status `success/available` to `ready`, `pending` to `queued`, `failed` to `failed`, anything else to `lazy`. Only fields the items actually carry become columns; run the page against the real item shape (grep the component's existing `movie.` accesses) and drop any column whose field does not exist, noting it in the report.
4. Sweep the file for `/NN` modifiers on `border`/`muted` per the carried ruling; restyle any remaining raw greys to tokens.

- [ ] **Step 4: Run the tests and type check**

Run: `cd frontend && npm test -- Library && npx tsc --noEmit 2>&1 | grep -v "usePluginSlots\|Watchlist" | grep -c "error TS" || true`
Expected: Library tests pass; no NEW tsc errors (only the pre-existing files remain).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Library.tsx frontend/src/pages/Library.test.tsx
git commit -m "feat(ui): Library stat tiles, chip filters and a table view"
```

---

### Task 6: Watchlist source cards

**Files:**
- Create: `frontend/src/components/watchlist/SourceCard.tsx`
- Modify: `frontend/src/pages/Watchlist.tsx`
- Test: `frontend/src/components/watchlist/SourceCard.test.tsx`

**Interfaces:**
- Consumes: `Card`, `Pill`, `StatusDot`; `api.traktStatus()` (`{ connected, username, synced_at, configured }`), `api.traktSync()`, `api.mdblistStatus()` (`{ connected, list_ids }`), `api.mdblistSync()` (`{ ok, added }`).
- Produces: `SourceCard({ abbr, name, detail, connected, onSync, syncing }: { abbr: string; name: string; detail: string; connected: boolean; onSync?: () => void; syncing?: boolean })` named export.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/watchlist/SourceCard.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { SourceCard } from './SourceCard';

describe('SourceCard', () => {
  it('shows the source identity and detail line', () => {
    render(<SourceCard abbr="TR" name="Trakt" detail="adamlippert" connected onSync={() => {}} />);
    expect(screen.getByText('TR')).toBeInTheDocument();
    expect(screen.getByText('Trakt')).toBeInTheDocument();
    expect(screen.getByText('adamlippert')).toBeInTheDocument();
  });

  it('marks connection state as a pill', () => {
    render(<SourceCard abbr="MD" name="MDBList" detail="" connected={false} />);
    expect(screen.getByText('Not connected')).toBeInTheDocument();
  });

  it('fires onSync and disables while syncing', async () => {
    const onSync = vi.fn();
    const { rerender } = render(<SourceCard abbr="TR" name="Trakt" detail="" connected onSync={onSync} />);
    await userEvent.click(screen.getByRole('button', { name: 'Sync now' }));
    expect(onSync).toHaveBeenCalledOnce();

    rerender(<SourceCard abbr="TR" name="Trakt" detail="" connected onSync={onSync} syncing />);
    expect(screen.getByRole('button', { name: 'Syncing...' })).toBeDisabled();
  });

  it('hides the sync action when there is no handler', () => {
    render(<SourceCard abbr="MD" name="MDBList" detail="" connected />);
    expect(screen.queryByRole('button')).toBeNull();
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npm test -- SourceCard`
Expected: FAIL, cannot resolve.

- [ ] **Step 3: Implement**

`frontend/src/components/watchlist/SourceCard.tsx`:

```tsx
import { Card, Pill } from '../primitives';

export function SourceCard({
  abbr,
  name,
  detail,
  connected,
  onSync,
  syncing = false,
}: {
  abbr: string;
  name: string;
  detail: string;
  connected: boolean;
  onSync?: () => void;
  syncing?: boolean;
}) {
  return (
    <Card className="flex items-center gap-3">
      <span
        className="flex h-9 w-9 flex-none items-center justify-center rounded-lg border font-mono text-[11px] font-bold"
        style={{
          background: 'rgba(97,82,223,0.15)',
          borderColor: 'rgba(159,146,255,0.3)',
          color: '#c7c2ff',
        }}
      >
        {abbr}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="text-sm font-medium text-body">{name}</span>
          <Pill state={connected ? 'ready' : 'lazy'}>{connected ? 'Connected' : 'Not connected'}</Pill>
        </span>
        {detail && <span className="mt-0.5 block truncate text-[11px] text-muted">{detail}</span>}
      </span>
      {onSync && (
        <button
          type="button"
          onClick={onSync}
          disabled={syncing}
          className="flex-none rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-body
                     hover:border-accent-light/50 disabled:opacity-50"
        >
          {syncing ? 'Syncing...' : 'Sync now'}
        </button>
      )}
    </Card>
  );
}
```

- [ ] **Step 4: Wire into Watchlist**

In `frontend/src/pages/Watchlist.tsx`, above the poster grid (and above the empty state, so the cards render even with an empty watchlist):

```tsx
const { data: trakt } = useQuery({ queryKey: ['trakt-status'], queryFn: api.traktStatus, staleTime: 60_000 });
const { data: mdblist } = useQuery({ queryKey: ['mdblist-status'], queryFn: api.mdblistStatus, staleTime: 60_000 });
const queryClient = useQueryClient();
const traktSync = useMutation({
  mutationFn: api.traktSync,
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ['watchlist'] }),
});
const mdblistSync = useMutation({
  mutationFn: api.mdblistSync,
  onSuccess: () => queryClient.invalidateQueries({ queryKey: ['watchlist'] }),
});
```

```tsx
<div className="mb-5 grid gap-3 sm:grid-cols-2">
  {trakt && (
    <SourceCard
      abbr="TR" name="Trakt"
      detail={trakt.connected ? [trakt.username, trakt.synced_at && `synced ${trakt.synced_at.slice(0, 16)}`].filter(Boolean).join(' · ') : 'Connect in Settings'}
      connected={trakt.connected}
      onSync={trakt.connected ? () => traktSync.mutate() : undefined}
      syncing={traktSync.isPending}
    />
  )}
  {mdblist && (
    <SourceCard
      abbr="MD" name="MDBList"
      detail={mdblist.connected ? `${mdblist.list_ids.split(',').filter(Boolean).length} lists` : 'Connect in Settings'}
      connected={mdblist.connected}
      onSync={mdblist.connected ? () => mdblistSync.mutate() : undefined}
      syncing={mdblistSync.isPending}
    />
  )}
</div>
```

Check `api.traktSync` and `api.mdblistSync` invocation shape in `api.ts` (they may take no args and POST); adjust the `mutationFn` reference accordingly. Restructure the early returns so the source cards render in both the empty and populated branches (compute the grid content conditionally rather than returning before the cards). Keep the count line and grid otherwise as they are; sweep for `/NN` modifiers per the carried ruling. The emoji star in the empty state becomes `<Icon name="watchlist" className="mx-auto h-10 w-10 text-muted" />`.

- [ ] **Step 5: Run the tests**

Run: `cd frontend && npm test`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/watchlist/ frontend/src/pages/Watchlist.tsx
git commit -m "feat(ui): Trakt and MDBList source cards on the Watchlist"
```

---

### Task 7: Search results

**Files:**
- Modify: `frontend/src/pages/Search.tsx`
- Test: `frontend/src/pages/Search.test.tsx`

**Interfaces:**
- Consumes: `Chip`, `Pill`; existing `api.search` query unchanged.
- Produces: nothing downstream.

The mockup's search page is result ROWS (poster thumb, title, year, kind, state pill, overview, rating, actions) with facet chips above, replacing the poster grid. Facets are computed client-side; result count and elapsed time are measured in the client.

- [ ] **Step 1: Write the failing test**

`frontend/src/pages/Search.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import Search from './Search';

const results = [
  { tmdb_id: 1, media_type: 'movie', title: 'Blade Runner', year: '1982', rating: 8.1,
    votes: 900, popularity: 9, overview: 'Replicants.', poster_path: null, backdrop_path: null,
    library_status: 'success' },
  { tmdb_id: 2, media_type: 'tv', title: 'Blade Runner: Black Lotus', year: '2021', rating: 6.9,
    votes: 100, popularity: 3, overview: 'Anime.', poster_path: null, backdrop_path: null,
    library_status: null },
];

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    api: { ...actual.api, search: () => Promise.resolve({ results }) },
  };
});

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={['/search?q=blade']}><Search /></MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Search results', () => {
  it('renders rows with overview text, not a poster grid', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Blade Runner')).toBeInTheDocument());
    expect(screen.getByText('Replicants.')).toBeInTheDocument();
  });

  it('computes facet counts from the result set', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Movies · 1')).toBeInTheDocument());
    expect(screen.getByText('Series · 1')).toBeInTheDocument();
    expect(screen.getByText('In library · 1')).toBeInTheDocument();
  });

  it('filters by facet without a new request', async () => {
    const { container } = renderPage();
    await waitFor(() => expect(screen.getByText('Blade Runner')).toBeInTheDocument());
    (screen.getByText('Movies · 1') as HTMLElement).click();
    await waitFor(() => expect(container.textContent).not.toContain('Black Lotus'));
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npm test -- Search`
Expected: FAIL (grid rendering, no facets).

- [ ] **Step 3: Implement**

Rework the results branch of `Search.tsx` (keep the query, the debounce, the URL sync, the DetailModal exactly as they are):

1. Elapsed time: wrap the query fn to measure:

```tsx
const [elapsed, setElapsed] = useState<number | null>(null);
// inside queryFn:
queryFn: async () => {
  const t0 = performance.now();
  const r = await api.search(debouncedQ);
  setElapsed((performance.now() - t0) / 1000);
  return r.results;
},
```

2. Facets, replacing the current `typeFilter` buttons if any exist and the plain count line:

```tsx
type Facet = 'all' | 'movie' | 'tv' | 'inlib';
const [facet, setFacet] = useState<Facet>('all');
const counts = {
  movie: (data || []).filter((i) => i.media_type === 'movie').length,
  tv: (data || []).filter((i) => i.media_type === 'tv').length,
  inlib: (data || []).filter((i) => i.library_status === 'success' || i.library_status === 'available').length,
};
const filtered = (data || []).filter((i) =>
  facet === 'all' ? true
  : facet === 'inlib' ? (i.library_status === 'success' || i.library_status === 'available')
  : i.media_type === facet,
);
```

```tsx
<div className="flex flex-wrap gap-2">
  <Chip label={`All · ${(data || []).length}`} selected={facet === 'all'} onClick={() => setFacet('all')} />
  <Chip label={`Movies · ${counts.movie}`} selected={facet === 'movie'} onClick={() => setFacet('movie')} />
  <Chip label={`Series · ${counts.tv}`} selected={facet === 'tv'} onClick={() => setFacet('tv')} />
  <Chip label={`In library · ${counts.inlib}`} selected={facet === 'inlib'} onClick={() => setFacet('inlib')} />
</div>
```

The count line becomes `{filtered.length} results{elapsed != null && ` · ${elapsed.toFixed(2)}s`}` in `font-mono text-xs text-muted`.

3. Result rows replacing the grid: each row a `button` (`w-full text-left`) opening the modal:

```tsx
<div className="space-y-2">
  {filtered.map((it) => (
    <button
      key={`${it.media_type}-${it.tmdb_id}`}
      type="button"
      onClick={() => open(it)}
      className="flex w-full items-start gap-3 rounded-xl border border-border bg-card p-3 text-left
                 hover:border-accent-light/50 transition-colors"
    >
      <span className="h-20 w-14 flex-none overflow-hidden rounded-md bg-bg">
        {tmdbImg.poster(it.poster_path) && (
          <img loading="lazy" src={tmdbImg.poster(it.poster_path)!} alt="" className="h-full w-full object-cover" />
        )}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-body">{it.title}</span>
          {it.year && <span className="text-xs text-muted">{it.year}</span>}
          <span className="text-[10px] uppercase tracking-wide text-muted">{it.media_type === 'tv' ? 'Series' : 'Movie'}</span>
          {(it.library_status === 'success' || it.library_status === 'available') && <Pill state="ready">In library</Pill>}
          {it.library_status === 'pending' && <Pill state="queued">Requested</Pill>}
        </span>
        {it.overview && <span className="mt-1 block text-xs leading-relaxed text-muted line-clamp-2">{it.overview}</span>}
        {it.rating > 0 && (
          <span className="mt-1 inline-block font-mono text-[11px] text-warn">★ {it.rating}</span>
        )}
      </span>
    </button>
  ))}
</div>
```

Sweep for `/NN` modifiers per the carried ruling (the current file has `placeholder-muted`, already fixed in the Plan 1 fix wave; verify nothing regressed).

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npm test -- Search`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Search.tsx frontend/src/pages/Search.test.tsx
git commit -m "feat(ui): search becomes result rows with client-side facets"
```

---

### Task 8: Requests quota card and stat tiles

**Files:**
- Create: `frontend/src/components/requests/QuotaCard.tsx`
- Modify: `frontend/src/pages/Requests.tsx`
- Test: `frontend/src/components/requests/QuotaCard.test.tsx`

**Interfaces:**
- Consumes: `api.myQuota` + `QuotaInfo` (Task 1); `StatTile`, `StatusDot`, `Card`; existing queries (`my-requests`, `pending-requests`, `failed-requests`) unchanged, including their `refetchInterval`s (background refetch keeps content mounted, per the refresh policy).
- Produces: `QuotaCard()` named export, self-fetching.

Binding metric rows: Awaiting review / Approved / Denied are counts of the user's `user_requests` rows by status (`pending` / `approved` / `denied`), computed client-side from the `my-requests` payload the page already holds.

- [ ] **Step 1: Write the failing test**

`frontend/src/components/requests/QuotaCard.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi } from 'vitest';
import { QuotaCard } from './QuotaCard';

const quota = vi.fn();
vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return { ...actual, api: { ...actual.api, myQuota: () => quota() } };
});

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><QuotaCard /></QueryClientProvider>);
}

describe('QuotaCard', () => {
  it('shows used of limit with the reset date', async () => {
    quota.mockResolvedValue({ used: 14, limit: 25, resets_at: '2026-10-01T00:00:00Z', unlimited: false });
    renderCard();
    await waitFor(() => expect(screen.getByText('14')).toBeInTheDocument());
    expect(screen.getByText(/of 25 requests/)).toBeInTheDocument();
    expect(screen.getByText(/Resets/)).toBeInTheDocument();
  });

  it('renders nothing for an unlimited user', async () => {
    quota.mockResolvedValue({ used: 3, limit: 0, resets_at: '2026-10-01T00:00:00Z', unlimited: true });
    const { container } = renderCard();
    await waitFor(() => expect(quota).toHaveBeenCalled());
    expect(container.textContent).toBe('');
  });

  it('turns the bar warning-coloured at 80 percent', async () => {
    quota.mockResolvedValue({ used: 20, limit: 25, resets_at: '2026-10-01T00:00:00Z', unlimited: false });
    const { container } = renderCard();
    await waitFor(() => expect(screen.getByText('20')).toBeInTheDocument());
    const bar = container.querySelector('[data-quota-bar]') as HTMLElement;
    expect(bar.style.width).toBe('80%');
    expect(bar.style.background).toContain('--dot-warn');
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npm test -- QuotaCard`
Expected: FAIL, cannot resolve.

- [ ] **Step 3: Implement**

`frontend/src/components/requests/QuotaCard.tsx`:

```tsx
import { useQuery } from '@tanstack/react-query';
import { api } from '../../api';
import { Card } from '../primitives';

export function QuotaCard() {
  const { data } = useQuery({ queryKey: ['my-quota'], queryFn: api.myQuota, staleTime: 60_000 });

  if (!data || data.unlimited) return null;

  const pct = Math.min(100, Math.round((data.used / Math.max(1, data.limit)) * 100));
  const tone = pct >= 100 ? 'var(--dot-danger)' : pct >= 80 ? 'var(--dot-warn)' : '#6152df';
  const resetDay = data.resets_at.slice(0, 10);
  const daysLeft = Math.max(0, Math.ceil((Date.parse(data.resets_at) - Date.now()) / 86_400_000));

  return (
    <Card>
      <div className="text-[11px] font-semibold uppercase tracking-wider text-muted">Monthly quota</div>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="font-mono text-3xl font-semibold text-body">{data.used}</span>
        <span className="text-xs text-muted">of {data.limit} requests</span>
      </div>
      <div className="mt-3 h-1.5 overflow-hidden rounded-full" style={{ background: 'rgba(255,255,255,0.08)' }}>
        <div data-quota-bar className="h-full rounded-full" style={{ width: `${pct}%`, background: tone }} />
      </div>
      <div className="mt-2 text-[11px] text-muted" title={resetDay}>
        Resets in {daysLeft} {daysLeft === 1 ? 'day' : 'days'}
      </div>
    </Card>
  );
}
```

- [ ] **Step 4: Wire into Requests**

In `frontend/src/pages/Requests.tsx`, above the existing sections:

```tsx
const items = data?.items ?? [];
const counts = {
  pending: items.filter((r: any) => r.status === 'pending').length,
  approved: items.filter((r: any) => r.status === 'approved').length,
  denied: items.filter((r: any) => r.status === 'denied').length,
};
```

```tsx
<div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
  <QuotaCard />
  <StatTile value={String(counts.pending)} label="Awaiting review" glow="warn" />
  <StatTile value={String(counts.approved)} label="Approved" glow="ok" />
  <StatTile value={String(counts.denied)} label="Denied" glow="danger" />
</div>
```

Then restyle the page's local `StatusPill` and `LibraryPill` helpers: reimplement them over the `Pill` primitive, mapping `pending -> queued`, `approved/success/available -> ready`, `denied/failed -> failed`, anything else `-> lazy`, keeping their current labels. Sweep for `/NN` modifiers per the carried ruling. Do not touch the three panels' queries or their refetch intervals.

- [ ] **Step 5: Run the tests**

Run: `cd frontend && npm test`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/requests/ frontend/src/pages/Requests.tsx
git commit -m "feat(ui): quota card and status tiles on My Requests"
```

---

### Task 9: Wanted

**Files:**
- Modify: `frontend/src/pages/Wanted.tsx`
- Test: `frontend/src/pages/Wanted.test.tsx`

**Interfaces:**
- Consumes: `Pill`, `Card`; existing `wanted-movies` / `wanted-episodes` queries and the `wanted-recheck` action unchanged.
- Produces: nothing downstream.

The page already splits movies and episodes behind tabs and has local `Pill`/`TabBtn`/`Th` helpers. The relayout: both sections VISIBLE at once (mockup shows Movies then Episodes stacked, each with a count in its header), attempt counts colour-ramped, `Retry all now` prominent next to an "N items unresolved" line.

- [ ] **Step 1: Write the failing test**

`frontend/src/pages/Wanted.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import Wanted from './Wanted';

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    api: {
      ...actual.api,
      wantedMovies: () => Promise.resolve({ items: [
        { imdb_id: 'tt1', title: 'Movie A', reason: 'NO_RELEASE', attempts: 2, last_checked: '2026-08-30 10:00:00' },
        { imdb_id: 'tt2', title: 'Movie B', reason: 'NO_RELEASE', attempts: 11, last_checked: '2026-08-30 10:00:00' },
      ] }),
      wantedEpisodes: () => Promise.resolve({ items: [
        { imdb_id: 'tt3', title: 'Show C', season: 1, episode: 2, status: 'wanted', air_date: '2026-08-01' },
      ] }),
    },
  };
});

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><Wanted /></MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Wanted', () => {
  it('shows both sections at once with their counts', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Movie A')).toBeInTheDocument());
    expect(screen.getByText('Show C')).toBeInTheDocument();
    expect(screen.getByText(/Movies/)).toBeInTheDocument();
    expect(screen.getByText(/Episodes/)).toBeInTheDocument();
  });

  it('summarises the unresolved total with a retry action', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('3 items unresolved')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Retry all now' })).toBeInTheDocument();
  });

  it('colour-ramps attempt counts at 5 and 10', async () => {
    const { container } = renderPage();
    await waitFor(() => expect(screen.getByText('Movie B')).toBeInTheDocument());
    const low = container.querySelector('[data-attempts="2"]') as HTMLElement;
    const high = container.querySelector('[data-attempts="11"]') as HTMLElement;
    expect(low.style.color).not.toContain('e48181');
    expect(high.style.color).toContain('#e48181');
  });
});
```

Check the real `WantedMovie` / `WantedEpisode` types in `frontend/src/types.ts` before finalizing the mock rows; the mock must carry the fields the page renders (grep the component's accesses). Adjust mock fields, not assertions; if `attempts` does not exist on the movie type, find the field that carries the retry count (the page renders it today) and use that name in both mock and `data-attempts` markup.

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npm test -- Wanted`
Expected: FAIL (tabs hide one section; no summary line).

- [ ] **Step 3: Implement**

In `frontend/src/pages/Wanted.tsx`:

1. Remove the tab state and `TabBtn`; render two stacked `<section>`s, each headed:

```tsx
<div className="mb-2 flex items-center gap-2">
  <h2 className="text-sm font-semibold text-body">Movies</h2>
  <span className="rounded px-1.5 py-0.5 font-mono text-[10px] text-muted" style={{ background: 'var(--surface-subtle)' }}>
    {movies.length}
  </span>
</div>
```

and the same for Episodes.

2. Summary bar above both sections:

```tsx
<div className="mb-5 flex items-center justify-between rounded-xl border border-border bg-card px-4 py-3">
  <span className="text-sm text-body">{movies.length + episodes.length} items unresolved</span>
  <button
    type="button"
    onClick={() => recheck.mutate()}
    disabled={recheck.isPending}
    className="rounded-lg bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-light disabled:opacity-50"
  >
    {recheck.isPending ? 'Retrying...' : 'Retry all now'}
  </button>
</div>
```

wired to the existing `wanted-recheck` mutation (find its current call: `grep -n "wanted-recheck\|wantedRecheck" frontend/src/pages/Wanted.tsx frontend/src/api.ts`; if the page has no mutation yet, add one over the existing `api` client member and invalidate both wanted queries on success).

3. Attempt ramp, replacing however attempts render today:

```tsx
function attemptStyle(n: number): React.CSSProperties {
  if (n >= 10) return { background: 'rgba(209,71,71,0.14)', color: '#e48181' };
  if (n >= 5) return { background: 'rgba(198,178,83,0.13)', color: '#dacd8a' };
  return { background: 'rgba(255,255,255,0.05)', color: 'rgba(255,255,255,0.45)' };
}
// usage: <span data-attempts={n} className="rounded-md px-1.5 py-1 font-mono text-[10px]" style={attemptStyle(n)}>{n}</span>
```

4. Replace the local `Pill` helper with the primitive (`wanted -> queued`, `found -> ready`, `give_up -> failed`); keep `Th` or migrate the tables' header cells to the `DataTable` column style, whichever is the smaller diff (state the choice in the report). Sweep for `/NN` modifiers per the carried ruling.

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npm test -- Wanted`
Expected: 3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Wanted.tsx frontend/src/pages/Wanted.test.tsx
git commit -m "feat(ui): Wanted shows both backlogs with attempt ramps and retry-all"
```

---

### Task 10: Settings split

**Files:**
- Modify: `frontend/src/pages/Settings.tsx`
- Modify: `frontend/src/components/PluginSettingsCard.tsx` (restyle only)
- Test: `frontend/src/pages/Settings.test.tsx`

**Interfaces:**
- Consumes: `Card`, `Pill`, `Toggle`; existing plugin registry (`usePlugins`), `PreferencesCard`, `NotificationsCard`, and all their queries unchanged.
- Produces: nothing downstream.

The page already has the right pieces (plugin cards, `PreferencesCard`, `NotificationsCard`); the spec's change is structure and skin: an **Integrations** section (the plugin cards) and a **Preferences** section (preferences + notifications), each with the mockup's header treatment, and the plugin cards restyled to the connection-card look (icon tile, name, status pill, description, detail, toggle).

- [ ] **Step 1: Write the failing test**

`frontend/src/pages/Settings.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import Settings from './Settings';

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    api: {
      ...actual.api,
      session: () => Promise.resolve({ authenticated: true, user: { username: 'adam', role: 'admin' } }),
      settings: () => Promise.resolve({ groups: [] }),
    },
  };
});

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter><Settings /></MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Settings structure', () => {
  it('splits into Integrations and Preferences sections', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Integrations')).toBeInTheDocument());
    expect(screen.getByText('Preferences')).toBeInTheDocument();
  });

  it('describes each section', async () => {
    renderPage();
    await waitFor(() => expect(screen.getByText('Watchlist sources and playback targets')).toBeInTheDocument());
    expect(screen.getByText('Applies to your account only')).toBeInTheDocument();
  });
});
```

The page mounts plugin and settings queries; if a member the page always calls is missing from the mocked shape, mock it to an empty resolution and note it in the report (same rule as Task 5).

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npm test -- Settings`
Expected: FAIL (no section headers exist).

- [ ] **Step 3: Implement**

In `Settings.tsx`:

1. Section scaffolding:

```tsx
<section className="mb-8">
  <div className="mb-3">
    <h2 className="text-sm font-semibold text-body">Integrations</h2>
    <p className="text-xs text-muted">Watchlist sources and playback targets</p>
  </div>
  {/* existing plugin cards grid */}
</section>
<section>
  <div className="mb-3">
    <h2 className="text-sm font-semibold text-body">Preferences</h2>
    <p className="text-xs text-muted">Applies to your account only</p>
  </div>
  {/* PreferencesCard + NotificationsCard */}
</section>
```

2. Restyle `PluginCard` in `Settings.tsx` and `PluginSettingsCard.tsx` to the connection-card look, using the SourceCard visual vocabulary (icon tile with `rgba(97,82,223,0.15)` background and mono abbr, name + `Pill` status, description in `text-xs text-muted`, detail line, `Toggle` from primitives where the card has an enable switch). Preserve every existing control and mutation; this is skin, not behaviour: before committing, diff your change and confirm no `onClick`, `onChange`, `mutate` or query was removed.
3. Sweep both files for `/NN` modifiers per the carried ruling.

- [ ] **Step 4: Run the tests**

Run: `cd frontend && npm test`
Expected: all green.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Settings.tsx frontend/src/components/PluginSettingsCard.tsx frontend/src/pages/Settings.test.tsx
git commit -m "feat(ui): Settings splits into Integrations and Preferences"
```

---

### Task 11: Integration gate

**Files:**
- Modify: `static/app/` (rebuild)
- Test: everything

**Interfaces:** consumes all prior tasks; produces the shippable branch state.

- [ ] **Step 1: Full test sweep**

Run, from the repo root:

```bash
./.venv-sdd/bin/python -m pytest tests/ -q
node --test tests/js/filter_rules.test.js
cd frontend && npm test && npx tsc --noEmit
```

Expected: 456 Python passed; 34 JS; every frontend suite green; tsc shows only the pre-existing errors in `usePluginSlots.ts` and `Watchlist.tsx` MINUS any this plan's rewrites fixed (Task 2 cleared PosterCard's two; if the Watchlist edits cleared its one, so much the better; none may be NEW).

- [ ] **Step 2: Done-when greps**

```bash
grep -rn "bg-green-\|bg-yellow-\|bg-blue-\|bg-red-\|text-green-\|text-yellow-" frontend/src --include='*.tsx' | grep -v node_modules
grep -rn "border-border/\|placeholder-muted/\|text-muted/" frontend/src --include='*.tsx'
grep -rn "components/DetailModal'" frontend/src --include='*.tsx'
```

Expected: first two return nothing (stock tailwind colours and kind-changed modifiers are gone); third shows the four page imports resolving to the directory.

- [ ] **Step 3: Build and commit**

```bash
cd frontend && npm run build
cd .. && git add -A static/app frontend && git commit -m "chore(ui): rebuild static/app with the restyled screens"
```

- [ ] **Step 4: Report**

State plainly in the completion report: which tsc pre-existing errors remain, any column dropped from the Library table for lack of a field, any facet or tile omitted because its data source did not exist, and that in-browser verification is deferred to the user.

## Done when

- All suites green as listed in Task 11 Step 1.
- The Task 11 Step 2 greps come back clean.
- `static/app/` rebuilt and committed.
- Discover opens with the hero; Library shows tiles + chips + a table toggle; Watchlist shows the two source cards; Search renders rows with facets; Requests shows the quota card and three tiles; Wanted shows both backlogs with ramps; Settings shows the two sections. (In-browser confirmation by the user.)
