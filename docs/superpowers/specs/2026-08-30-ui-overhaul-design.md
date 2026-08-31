# UI overhaul: AIOStreams-style redesign

**Date:** 2026-08-30
**Status:** draft, awaiting review
**Branch:** `feat/ui-overhaul`, off `main`
**Mockup:** claude.ai design project `6cde5310-be34-459c-a3b0-9d8f36c38763`,
file `Mycelium Redesign.dc.html` (1,196 lines, read via DesignSync)
**Builds on:** `docs/superpowers/plans/2026-08-30-filter-rules-editor.md` (C2,
executed; the editor it produced is ported rather than rebuilt, see
"Filter rules")

## Problem

The Mycelium web UI is three interfaces wearing one URL.

1. A React SPA (27 files, 4,950 lines) serving Discover, Library, Watchlist,
   Search, Requests, Wanted and Settings.
2. A Jinja admin dashboard (`templates/ui.html`, 2,297 lines) with eight tabs,
   embedded in the SPA as an iframe.
3. A Jinja setup wizard (`templates/setup.html`, 531 lines) and login page
   (`templates/login.html`, 98 lines) on the pre-auth path.

They do not share a palette, a type scale, an icon set or a component
vocabulary. The SPA uses emoji for navigation. `AdminTabs.tsx` carries a
comment admitting that neither the React nor the Jinja admin fully replaces the
other, so it renders both behind a tab switcher rather than choosing.

Separately, C2 built a chip editor for the 35 filter settings C1 introduced,
and it lives in the Jinja admin: `static/admin/filter_rules.js`, loaded by
`templates/ui.html` and covered by 34 tests. It works. It is also the single
largest piece of interaction logic tied to the surface being replaced, so the
port has to carry it across without losing it.

## Goals

Redesign all eleven screens in the mockup against one design system, port the
three server-rendered surfaces to React, and fold the C2 filter editor in so
that panel is built once rather than twice.

## Non-goals

- A "why was this release not picked" view. C1 produces a `Verdict` per rejected
  candidate and nothing displays it. Surfacing it needs either verdict
  persistence (new table, retention policy) or re-running the ranker on demand
  (re-scraping, slow, rate limited). That is a subsystem, not a panel. Inherited
  verbatim from the C2 spec's own non-goals.
- Deleting the Jinja templates. They stay in the image this release. See
  "Safety net".
- Mobile-first rework. The current responsive behaviour (drawer under `lg`) is
  preserved, not redesigned.
- Any change to the catbox, scraping, or strm-generation pipelines beyond the
  one timing wrapper described under "Scraper health".

## Decisions taken during brainstorming

| Question | Decision |
|---|---|
| How much of the mockup? | Everything, one project. All eleven screens including the three Jinja ports. |
| C2 overlap | Fold C2 into the redesign as a single Admin tab, built once. Taken on the belief that C2 was unbuilt; it is in fact shipped, so the tab ports the existing editor and reuses its pure state model instead of rebuilding it. The decision stands and gets cheaper. |
| Panels with no backend | Build all three: request quota, live log, scraper health. |
| Migration strategy | Convert in place for the eight React screens. Flagged parallel cutover for Admin, Manual, Setup and Login. |

The third decision was taken on a cost estimate that turned out pessimistic.
Scraper health was described as needing instrumentation across three scraper
modules. It does not: `scrapers.py` holds a single registry
(`_SCRAPERS = [debridio, zilean, torrentio]` behind `_active()`), so the timing
wrapper goes in one place. The decision stands and gets cheaper.

## Design system

### Tokens

`tailwind.config.js` carries the palette. A new `frontend/src/design/tokens.css`
carries the alpha-composited values Tailwind expresses badly: every pill
background in the mockup is an `rgba()` over a dark ground, not a flat hex.

| Token | Current | New |
|---|---|---|
| `bg` | `#0a0e14` | `#070707` |
| `sidebar` | `#141a23` | `#0b0b0b` |
| `card` | `#141a23` | `#0f0f0f` to `#151515` |
| `border` | `#1e2632` | `rgba(255,255,255,0.09)` |
| `accent` | `#6366f1` | `#6152df` |
| `accent-light` | (none) | `#9f92ff` |
| `accent-pale` | `#22d3ee` | `#c7c2ff` |
| `ok` | `#10b981` | `#7bd0a7` (dot `#57a181`) |
| `warn` | `#f59e0b` | `#dacd8a` (dot `#c6b253`) |
| `danger` | `#ef4444` | `#e48181` (dot `#d14747`) |
| `text` | `#ffffff` | `#e6e6e6` |
| `muted` | `#6b7785` | `rgba(255,255,255,0.5)` |

Retired: `accent-2`, `teal`, `mint`, `amber`, `info`. Any usage found during
conversion maps to the table above.

### Typography

Inter for the interface, JetBrains Mono for anything numeric, hash-like or
code-like (attempt counts, env var names, log timestamps, info hashes, shell
commands in the manual).

Both fonts are **self-hosted from `static/fonts/`**, not loaded from
`fonts.googleapis.com`. The mockup uses the Google CDN; this is a self-hosted
application and its users should not make third-party requests to render a
page. Subset to latin and latin-ext, woff2, `font-display: swap`, preloaded
in `frontend/index.html`.

### Icons

`frontend/src/design/icons.tsx` exports one component per icon, built from the
SVG path data in the mockup's `SCREENS` array: discover, library, watchlist,
search, requests, wanted, settings, admin, manual, setup, login. Replaces all
nine navigation emoji. Stroke-based, `currentColor`, 24x24 viewBox.

### Primitives

`frontend/src/components/primitives/`, one file each, each independently
testable and used by at least two screens:

| Primitive | Responsibility |
|---|---|
| `Pill` | Five states: `ready`, `materializing`, `queued`, `failed`, `lazy`. Background, foreground and border per state. |
| `Chip` | Filter chips (selected and unselected) and the removable variant the filter editor needs. |
| `StatTile` | Value, label, optional sub-line, optional coloured radial glow. |
| `DataTable` | Header row, body rows, column alignment, empty state. |
| `Toggle` | 38x22 pill switch with knob, on and off. |
| `Card` | Surface, hairline border, radius, padding. |
| `StatusDot` | 7px dot with matching glow, three colours. |

Built and tested before any screen consumes them.

## Shell

`Layout.tsx` (289 lines) splits into `Sidebar.tsx`, `Topbar.tsx`, `NavItem.tsx`
and `RegionPicker.tsx` under `frontend/src/components/shell/`.

**Sidebar:** 224px to 248px. Two groups, `Browse` and `Manage`. Settings moves
from Browse to Manage, matching the mockup. Navigation items carry live counts
(Watchlist, My Requests, Wanted). Active item gets
`background: rgba(97,82,223,0.16)` and an inset 2px left rule in
`accent-light`. The version line and user block at the foot become a user card:
avatar initials, username, role pill.

**Topbar:** breadcrumb becomes `MYCELIUM / <crumb>` plus the page title, a
TorBox status pill, the region picker, and `⌘K` affordance on the search field.

**One request, not three.** The nav counts and the TorBox pill are needed on
every page. They come from a single new endpoint (see "Backend additions")
cached by React Query with a 60 second `staleTime`, not from three separate
calls.

## The eight React screens

Governing rule: **every number on screen maps to a real source, or it does not
ship.** The mockup invents metrics that have no origin in this codebase. The
substitution table under "Metrics" is binding.

### Discover

Adds a full-bleed hero above the existing rows: backdrop image, an eyebrow
(`Featured`, `Trending #1 this week`), title, rating, year, runtime, genres, a
quality badge, and three actions (Request title, Watchlist, Trailer). Sourced
from `discover/trending` for the top result and `discover/details` for its
runtime and genres.

Provider chips move above the rows into a labelled "Streaming services" strip
with the existing explanatory line. `PosterGrid` and `PosterCard` restyle in
place: corner badges (`IN LIBRARY` green, `REQUESTED` purple), rating, title,
year.

### Library

Currently a poster grid over `library-movies` and `library-series-episodes`.
Adds:

- A filter chip row: All, Movies, Series, Materialized, Lazy (STRM), Needs repair.
- Four stat tiles (see "Metrics").
- A table view alongside the grid, toggled: Title, Year, Quality, State, Added.
  State renders as `Pill` from the item's `playability_state`.

### Watchlist

60 lines today. Adds source cards for Trakt and MDBList (icon, connection
status pill, account or list detail, last sync, item count) from
`trakt/status` and `mdblist/status`, with a `Sync now` action calling the
existing `trakt/sync` and `mdblist/sync`. Posters gain the badge treatment.

### Search

Result rows gain overview text, rating, a state pill and a `Details` action
alongside the existing add action. Facet chips (Movies, Series, decade,
In library) are computed client-side from the result set, not from a new
endpoint. Result count and elapsed time are measured in the client.

### Requests

Already a table over `my-requests`, `pending-requests` and `failed-requests`.
Adds:

- A quota card: used, limit, reset date, from the new `me/quota` endpoint.
- Three stat tiles: Awaiting review, Approved, Denied, counted from
  `user-requests`. The approval workflow already exists
  (`ui_api_user_request_approve`, `ui_api_user_request_deny`).

### Wanted

Already splits movies and episodes across `wanted-movies` and
`wanted-episodes`. The layout makes the split explicit, with counts in each
section header. Attempt counts colour-ramp: under 5 neutral, 5 to 9 gold,
10 and over red. `Retry all now` calls the existing `wanted-recheck`.

### Settings

469 lines, currently a flat plugin grid. Splits into two sections:

- **Integrations:** connection cards for watchlist sources and playback
  targets. Icon, name, status pill, description, detail line, enable toggle,
  Configure action. Driven by the existing plugin registry.
- **Preferences:** account-scoped rows, label plus hint plus control, over
  `me/preferences` and `me/region`.

### Login

Restyled to the mockup: logo, the tagline "the hidden network beneath your
media library", username and password fields, Sign in, an `or` divider, and
Continue with OIDC.

`Login.tsx` is unreachable today. Flask registers `/login` before the SPA
catch-all, so `login_view()` wins the URL and the React page never renders.
Making it reachable is part of the flagged cutover below.

## The four ported surfaces

### Admin

Eight Jinja tabs, six mockup tabs, and they are not the same six. Reconciled to
nine React tabs, dropping nothing (the original count of eight omitted a home
for the runtime settings editor, found during Plan 3 preparation):

| React tab | Source |
|---|---|
| Overview | Jinja `overview` plus `releases`, changelog folded in as a panel |
| Users | Jinja `users` plus `Admin.tsx` user management |
| Requests | Jinja `requests` |
| Filter rules | New. The C2 editor. |
| Scrapers | New. Health panel. |
| Logs | Jinja `logs` |
| Maintenance | Jinja `maintenance`, whose lower half is the repair history |
| Blacklist | Jinja `blacklist` |
| Settings | Jinja `settings`: the runtime settings editor over `settings.all_for_ui()`, minus the `filter_rules` group which becomes its own tab |

`Admin.tsx` (745 lines) becomes one file per tab under
`frontend/src/pages/admin/`, with a shared `AdminLayout.tsx` holding the tab
strip.

**The first admin task is a written feature inventory**, tab by tab, of both
the Jinja dashboard and `Admin.tsx`, checked off as each control finds a home
in the React version. The `AdminTabs.tsx` comment is a standing warning that
these two surfaces have diverged; porting without an inventory loses
functionality silently.

`AdminTabs.tsx` and its iframe are deleted once the inventory is discharged.

### Filter rules

A port of the shipped C2 editor, not a rebuild. `static/admin/filter_rules.js`
exports a pure state model (`parseList`, `serializeList`, `buildState`,
`assign`, `reorder`, `availableFor`, `invalidValues`, `isEmpty`,
`toFormFields`, `visibleChips`, `displayValue`) alongside its DOM renderers.
The state model is framework-agnostic and moves to the React tab unchanged;
only `renderPanel`, `renderCollapsed`, `syncHiddenInputs` and
`initFilterRules`, which are DOM-specific, are replaced by React components.
Behaviour is preserved exactly:

- One panel per category, seven panels: RESOLUTION, SOURCE, ENCODE, VISUAL_TAG,
  AUDIO_TAG, AUDIO_CHANNELS, LANGUAGE.
- Four chip rows per panel: Preferred, Excluded, Required, Included.
- A `strict` toggle per panel.
- Values added from a dropdown of that category's vocabulary, not typed. This
  is the point of C2: typing a value blind meant `settings.set()` rejected a
  typo only after saving.
- Long chip lists collapse behind a `+N more` control at `CHIP_VISIBLE_LIMIT`.
- Preferred chips carry their own reorder arrows, since order is the tie-break.
- The Included row carries a standing warning that it overrides every other
  rule in every category.
- Panel header shows the category's total value count.

`tests/js/filter_rules.test.js` (34 tests) covers the state model. Those tests
must keep passing against the ported module unchanged: if the port needs them
edited, the state model was altered and the port is no longer behaviour
preserving.

### Manual

Replaces the `/docs/install-guide.html` iframe with a React docs page: a
12-entry table-of-contents sidebar (What is Mycelium, Full vs Lite, Features,
Mycelium Spore, Quick start, Proxmox / NAS guide, Architecture, Security,
Configuration, Observability, TorBox API rate limits, FAQ), scroll-spy
highlighting, and a link out to the README on GitHub.

Content renders from the existing files under `docs/`, not from a second copy.
Code blocks use JetBrains Mono with a `$` prompt affordance for shell lines.

### Setup wizard

Four steps, rendered in React at `/setup`, replacing `templates/setup.html`.

The POST endpoints (`/setup/save`, `/setup/skip`, `/setup/test/<kind>`) already
return JSON and are **not changed**. This is a view swap. Each step keeps its
`Test` button against the existing `/setup/test/<kind>`.

The GET route changes to serve `_spa_index()` when the flag is on. The SPA is
already reachable pre-auth (the catch-all has no auth guard, the API enforces
auth), so no gating change is needed.

## Safety net

Setup and Login sit on the first-run and authentication paths. There is no SSH
to the VPS. A regression on either is the one failure mode that cannot be
recovered remotely, so:

1. **The cutover flag is an environment variable, not a runtime setting.** A
   runtime toggle stored in SQLite is unreachable if login is what broke.
   `UI_V2` in `config.py`, default `false`, read at startup.
2. **The Jinja routes stay reachable permanently** at `/admin/classic`,
   `/setup/classic` and `/login/classic`, independent of the flag's value.
   That is the way back in, and it survives the flag being wrong.
3. **The Jinja templates are not deleted in this release.** They ship alongside
   the React versions. Deletion is a follow-up, after the React versions are
   confirmed working on the VPS.

Rollback is therefore: unset `UI_V2`, redeploy. If even that is impossible,
`/login/classic` still serves the working Jinja login.

## Refresh policy

The Jinja dashboard called `location.reload()` on a two-minute timer, gated on
ten seconds of idleness that only `click` and `keydown` reset. Reading and
scrolling never counted, so the reload was effectively unconditional. It threw
away scroll position, the open tab and any half-typed input, and it existed for
one reason: the repair half of the Maintenance tab was server-rendered and had
no JSON endpoint behind it.

That is fixed on `main` ahead of this project (`GET /ui/api/repair` plus a
`refreshRepair()` patcher). The rule it establishes binds the React admin:

1. **No route ever reloads itself.** `location.reload()` does not appear in the
   codebase. `tests/test_admin_refresh.py` fails if it comes back.
2. **Background refetch keeps rendered data mounted.** A refresh in flight never
   falls back to a loading state over content that is already on screen.
3. **Polling runs only while its panel is visible** and stops when it is not.
4. **Anything polling faster than 10 seconds carries a reason in the code.** The
   logs panel at 5 seconds is the only such case, and it stops when its tab is
   hidden.
5. **Rebuilt rows re-apply active filters.** Replacing a table body drops
   whatever a search box had hidden. React handles this by construction; the
   rule is recorded because the Jinja version got it wrong.

## Backend additions

Four endpoints. All JSON, all under the existing auth decorators.

### `GET /ui/api/shell-summary`

```json
{
  "counts": {"watchlist": 38, "requests": 3, "wanted": 11},
  "torbox": {"state": "ok", "label": "TorBox online"}
}
```

`state` is one of `ok`, `degraded`, `down`, derived from the existing TorBox
rate-limit bookkeeping in `torbox.py`. Serves the sidebar counts and the topbar
pill in one call.

### `GET /ui/api/me/quota`

```json
{"used": 14, "limit": 25, "resets_at": "2026-09-08T00:00:00Z", "unlimited": false}
```

`limit` is `users.quota_monthly`, which already exists. `used` counts the
current user's rows in `user_requests` since the start of the current calendar
month. `unlimited` is true when `quota_monthly` is 0, which is the existing
"no cap" encoding; the card renders as "unlimited" and hides the bar.

### `GET /ui/api/scraper-health`

```json
{"scrapers": [
  {"name": "Torrentio", "latency_ms": 212, "state": "ok", "samples": 40},
  {"name": "Zilean (DMM)", "latency_ms": 480, "state": "ok", "samples": 40},
  {"name": "Debridio", "latency_ms": 1421, "state": "slow", "samples": 12}
]}
```

Only scrapers returned by `scrapers._active()` appear. The mockup's MediaFusion
and Comet do not exist in this codebase and are not shown.

**Instrumentation:** one timing wrapper inside `scrapers.py`, around each
`_fetch_*` call in `fetch_candidates`. Records name, elapsed milliseconds and
success into a bounded in-process ring buffer (last 50 calls per scraper).
In-process is correct here: the app runs `--workers 1 --threads 16`, so there
is exactly one process, and the existing catbox locks and caches already rely
on that. The buffer is not persisted; an empty buffer after restart renders as
`unknown`, not as an outage.

**State derivation:** `ok` when the rolling median is under 1000ms and the last
call succeeded. `slow` when the median is 1000ms or more. `down` when the last
three calls raised. `unknown` when there are no samples. `ScrapersUnavailable`
already exists in `scrapers.py` and already distinguishes "searched and found
nothing" from "could not search", which is the distinction this panel needs.

### `GET /ui/api/logs`

```json
{"lines": [{"time": "20:11:25", "level": "INFO", "msg": "..."}]}
```

Parsed from the same source `/ui/logs` already reads. Query params `limit`
(default 200, max 1000) and `level` (minimum level filter). The panel polls at
5 second intervals while the Logs tab is visible and stops when it is not.
Server-sent events are deliberately not used: polling a bounded endpoint is
simpler, survives the Coolify proxy without buffering surprises, and the log
panel is an admin convenience rather than a monitoring system.

## Metrics

Binding substitution table. Left column is what the mockup shows; right column
is what ships.

### Admin overview tiles

| Mockup | Ships as | Source |
|---|---|---|
| Active streams (3, "1 transcoding / 2 direct play") | **Dropped.** Mycelium 302s MKV playback straight to the TorBox CDN and is not in the data path, so it cannot know. Replaced by **Requests 7d** (succeeded and failed). | `stats.get_overview().requests` |
| Queue depth (11, "4 running / 7 waiting") | **Queue depth** (retry queue rows plus active wanted items) | `db` retry_queue count, `stats.get_overview().wanted.active` |
| TorBox usage (318 GB, "13% of plan allowance") | **TorBox library** (item count and summed size). The plan allowance is not exposed by the TorBox API, so the percentage is dropped. | `/ui/api/torbox-list` |
| Failures 24h (6, "5 filter rejects / 1 timeout") | **Failures 7d**, with the breakdown taken from `playability_state` reasons (`TB_429`, `ADD_FAILED`, `TIMEOUT`, `NO_RELEASE`) | `stats.get_overview().requests.failed_7d`, `playability_state` |

### Library tiles

| Mockup | Ships as | Source |
|---|---|---|
| Titles (1,284, "+18 this week") | **Titles**, delta from requests created in the last 7 days | `stats.get_overview().library.movie_count + series_count` |
| Episodes (9,431, "+204 this week") | **Episodes**, same delta basis | `stats.get_overview().library.episode_count` |
| Materialized (412 GB "of 6.1 TB catalogued") | **Catalogued size** only. "Materialized" bytes are not tracked; catbox releases torrents after idle and Mycelium does not hold the files. | summed size from `/ui/api/torbox-list` |
| Cache hit rate (96.2%) | **Dropped.** No source. Replaced by **Success rate 7d**, which exists and means something. | `stats.get_overview().requests.success_rate_7d` |

### Requests tiles

| Mockup | Ships as | Source |
|---|---|---|
| Awaiting review (3) | as shown | `user-requests` where status is pending |
| Approved (9) | as shown | `user-requests` where status is approved |
| Denied (2) | as shown | `user-requests` where status is denied |

## File structure

```
frontend/src/
  design/
    tokens.css              new: alpha-composited surfaces, pill backgrounds
    icons.tsx               new: 11 nav icons plus action icons
  components/
    primitives/             new: Pill, Chip, StatTile, DataTable,
                                 Toggle, Card, StatusDot
    shell/                  new: Sidebar, Topbar, NavItem, RegionPicker
    DetailModal/            split from DetailModal.tsx (545 lines):
                            index, Seasons, Cast, Similar, StreamingOn
    PosterCard.tsx          restyled in place
    PosterGrid.tsx          restyled in place
  pages/
    admin/                  new: AdminLayout plus one file per tab
                            Overview, Users, Requests, FilterRules,
                            Scrapers, Logs, Maintenance, Blacklist
    Setup.tsx               new: four-step wizard
    Manual.tsx              new: docs page with ToC
    Discover.tsx  Library.tsx  Watchlist.tsx  Search.tsx
    Requests.tsx  Wanted.tsx   Settings.tsx   Login.tsx
```

Deleted at the end of the project: `pages/AdminTabs.tsx`, `pages/Admin.tsx`
(replaced by `pages/admin/`).

Deleted in a **later** release, once confirmed on the VPS: `templates/ui.html`,
`templates/setup.html`, `templates/login.html`.

## Testing

**Python (pytest):** the four new endpoints, each with an authenticated and an
unauthenticated case. The scraper timing wrapper: latency recorded on success,
state transitions across ok / slow / down / unknown, ring buffer bounded at 50,
and a scraper raising does not break `fetch_candidates`. The quota calculation
across a month boundary and with `quota_monthly = 0`. New file
`tests/test_ui_endpoints.py`, plus additions to `tests/test_scrapers.py`.

**JavaScript (`tests/js/`):** the filter rules editor. Adding and removing chips
per state, the strict toggle, the vocabulary dropdown offering only valid values
for its category, and the Included warning rendering. Extends the existing
`filter_rules.test.js`.

**React components (Vitest):** the repo has no way to test a component today,
and none of the 4,950 existing frontend lines are covered. This project adds
`vitest`, `jsdom`, `@testing-library/react` and `@testing-library/jest-dom` as
devDependencies, configured in the existing `frontend/vite.config.ts`. Every
primitive is tested for its variants; every ported admin tab is tested for the
controls it renders, which is what stops a control disappearing silently during
the port.

**Manual verification on the VPS**, in order, because these cannot be tested
locally against real data: `/login/classic` still works with `UI_V2` on; the
React login authenticates; `/setup` renders and its Test buttons pass; each
admin tab's controls act on real data.

Every task ends with `npm run build` and the built output under `static/app/`
committed, since the Dockerfile copies it when the npm build is skipped.

## Risks

| Risk | Mitigation |
|---|---|
| Broken login or setup locks you out of a remote host with no SSH | Env-var flag, permanent `/classic` routes, Jinja templates retained this release |
| Jinja admin functionality lost in the port | Written feature inventory as the first admin task, checked off control by control |
| The build output under `static/app/` drifts from source | Every task rebuilds and commits it |
| 4,950 lines of frontend rewritten at once | Convert in place, one screen per task, each independently shippable |
| Scraper timing wrapper slows the scraping path | Wrapper records into an in-process ring buffer, no I/O, no lock held across the network call |

## Follow-ups, explicitly out of scope

1. Delete `templates/ui.html`, `templates/setup.html`, `templates/login.html`
   once the React versions are confirmed on the VPS.
2. The rejected-candidate verdict view, inherited from the C2 spec's non-goals.
3. Mobile-specific layouts beyond the existing drawer behaviour.
