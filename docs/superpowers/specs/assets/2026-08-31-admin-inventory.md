# Admin feature inventory

Discharge checklist for plan `2026-08-30-ui-overhaul-3-admin`. Every control listed
here must find a home in the native React admin before that plan can finish.

Sources walked exhaustively:
- `templates/ui.html` (2365 lines) - all eight `tab-pane` divs plus the shared JS
  block at the bottom that drives controls the markup alone does not show.
- `static/admin/filter_rules.js` - the seven-category filter-rules editor loaded
  by `ui.html` and rendered into the Settings tab-pane; not literally inside
  `ui.html` but it is the entire implementation of "the filter_rules editor
  inside Jinja settings", so it is walked too.
- `frontend/src/pages/Admin.tsx` (745 lines) - every control.
- Cross-check: `grep -oE '"/ui/[a-z-]+"' app.py` and
  `grep -oE "'/ui/api/[a-z/-]+'" frontend/src/api.ts`, plus a fuller manual pass
  (see "Cross-check method" below) because both greps miss dynamic path
  segments (`<id>`, `<hash>`, `<imdb_id>`) and multi-segment `/ui/api/...`
  routes on the app.py side.

Planned-home map used (from the plan header):

- Overview <- Jinja overview (health, stats, quality bars, torbox quota,
  activity, webhook secret) + Jinja releases.
- Users <- Jinja users + Admin.tsx users CRUD.
- Requests <- Jinja requests table (delete/purge) + Admin.tsx pending
  approvals + Admin.tsx AutoApprovePanel.
- Filter rules <- the filter_rules editor inside Jinja settings.
- Scrapers <- new health panel + Jinja zilean controls.
- Logs <- Jinja logs viewer.
- Maintenance <- Jinja maintenance actions + repair history + add-magnet +
  torbox-delete + backup-restore + show-override-delete + Admin.tsx
  ArrImportPanel + MaintenancePanel.
- Blacklist <- Jinja blacklist.
- Settings <- Jinja settings groups (minus filter_rules) + Save all +
  auto-add now + Admin.tsx DiscoverGenreTabsPanel.

A control the map does not name gets the best-fitting tab plus a
`(placement chosen by inventory)` marker.

---

## Overview

- [x] Overview: stat tiles (movies, episodes, series, wanted, success rate 7d + sub-line) -> `refreshOverview()` / `GET /ui/api/stats` -> planned home: Overview (Task 6: replaced by the task-6-brief binding metric substitution table - Requests 7d / Queue depth / TorBox library / Failures 7d tiles, not a literal port of these five)
- [x] Overview: TorBox quota tile + resets-in countdown + per-reason breakdown card -> `refreshTorboxQuota()` / `GET /ui/api/torbox-quota` -> planned home: Overview (Task 6 fix round 1: ported as its own Card - budget bar, resets-in countdown, per-reason breakdown)
- [x] Overview: Service Health panel (topbar dots + card, per-service ok/down) -> `refreshHealth()` / `GET /ui/api/health` -> planned home: Overview (Task 6: ported as the health dot row, card only - no topbar dots, that's shell chrome)
- [x] Overview: Quality Distribution bars -> `refreshOverview()` / `GET /ui/api/stats` (`qualities`) -> planned home: Overview (Task 6)
- [ ] Overview: TorBox Usage card (torrent count, total size, plan, per-state badges) -> `refreshOverview()` / `GET /ui/api/torbox-usage` -> planned home: Overview (out of scope for Task 6; the TorBox library stat tile covers count + size only, from `/ui/api/torbox-list` not `/ui/api/torbox-usage`)
- [x] Overview: Performance Metrics (30d) card (avg latency, added, failed) -> `refreshOverview()` / `GET /ui/api/metrics-summary` -> planned home: Overview (Task 6 fix round 1: merged with Source Win Rate below into one "Metrics (30d)" Card - compact labelled rows per section, mono values, empty sections skipped)
- [x] Overview: Retry Queue card (next 10 pending retries) -> `refreshOverview()` / `GET /ui/api/retry-queue` -> planned home: Overview (Task 6: replaced by the Queue depth stat tile - a count, not the pending-retries list; see task-6-report.md)
- [x] Overview: Source Win Rate bars -> `refreshOverview()` / `GET /ui/api/metrics-summary` (`sources`/`unique_sources`) -> planned home: Overview (Task 6 fix round 1: folded into the "Metrics (30d)" Card as its "Source win rate" section, count + uniq count per label - same endpoint as Performance Metrics, one Card)
- [x] Overview: Library Health card (.strm count, DB count, strm minus DB, DB minus strm) -> `refreshOverview()` / `GET /ui/api/orphans` -> planned home: Overview (Task 6 fix round 1: verified against `templates/ui.html`'s `lib-health` fetch - it is `/ui/api/orphans`, a standalone endpoint not folded into any already-ported panel, so it got its own Card)
- [x] Overview: Integration Endpoints card (Seerr webhook URL, TorBox push URL, Catbox stream prefix; webhook secret reveal-on-click + Copy button) -> `populateEndpointUrls()` / `GET /ui/api/webhook-secret` -> planned home: Overview (Task 6: partial - only the webhook secret + Copy button per the brief's "also ports" list; Seerr/TorBox/Catbox URL rows and reveal-on-click are dropped, not ported)
- [x] Overview: Recent Activity feed (last 15 events) -> `refreshOverview()` / `GET /ui/api/activity` -> planned home: Overview (Task 6: last 20 per the brief, not 15)
- [x] Overview: Top Folders (.strm count) storage bars -> `refreshOverview()` / `GET /ui/api/storage` -> planned home: Overview (Task 6 fix round 1: ported as the "Top folders" Card, path + mono count rows, top 15, load-once (no refetchInterval))
- [ ] Overview: live activity toast stream (polls every 5s, toasts new events since last seen) -> `pollActivity()` / `GET /ui/api/activity` -> planned home: Overview (Task 6 fix round 1 ruling: will not be ported: duplicated by the activity feed)
- [ ] Overview: idle-gated auto-refresh (health every 30s; overview refresh every 30s once idle > 10s; repair refresh every 120s once idle) -> `setInterval(...)` -> planned home: Overview (Task 6 fix round 1 ruling: will not be ported: plumbing, not a control)
- [x] Overview: Releases changelog (expandable per-version notes, "current" badge) -> Jinja `releases` tab-pane, server-rendered from `releases`/`app_version` -> planned home: Overview (explicit in map: "+ Jinja releases") (Task 6: ported via the new `GET /ui/api/releases` route; "current" badge on the first/latest entry)
- [ ] Overview: theme toggle (dark/light, topbar icon) -> `toggleTheme()` -> planned home: Overview (placement chosen by inventory - this is global chrome, not overview-specific data, so it may end up living outside any single tab in the React shell instead) (Task 6 fix round 1 ruling: will not be ported: the new UI is deliberately single-theme)
- [ ] Overview: topbar keyboard-shortcut tab switcher (digit keys 1-0) -> `keydown` listener -> planned home: Overview (placement chosen by inventory; **stale**: only `1`/`2`/`9`/`0` still map to a real tab (overview/requests/settings/logs), `3`-`8` map to `movies`/`series`/`wanted`/`search`/`torbox`/`catbox`, none of which exist in the current 8-tab bar - see Findings) (Task 6 fix round 1 ruling: will not be ported: stale, references tabs that no longer exist)

## Requests

- [x] Requests: All Requests table (search, sort, paginate) -> `refreshRequests()` / `GET /ui/api/requests/all` -> planned home: Requests
- [x] Requests: Delete button ("forget the request, keep the files") -> `deleteRequest()` / `POST /ui/api/requests/<id>/delete` -> planned home: Requests
- [x] Requests: Remove from library (purge) button -> `purgeRequest()` / `POST /ui/api/requests/<id>/purge` -> planned home: Requests
- [ ] Requests: retry a failed request -> `POST /ui/api/requests/<id>/retry`, already wired in `frontend/src/pages/Requests.tsx` (`api.retryRequest`, outside this inventory's two named sources but confirmed live) -> planned home: Requests
- [x] Requests: Pending requests table + Approve/Deny -> Jinja `loadUsersTab()`'s "Pending requests" table (`approveReq`/`denyReq`, `POST /ui/api/user-requests/<id>/approve|deny`) **and** Admin.tsx's "Pending requests" section (`approveMut`/`denyMut`, same endpoints) -> planned home: Requests (map: "+ Admin.tsx pending approvals"; note the Jinja version currently lives inside the *Users* tab-pane, not Requests - the map moves it)
- [x] Requests: Auto-approve genre rules editor (Admin.tsx `AutoApprovePanel`: per-rule enabled toggle, media-type + genre selects, year-from/year-to, add rule, save rules, run now) -> `api.autoApproveGenreRules` / `setAutoApproveGenreRules` / `runAutoApproveNow` -> planned home: Requests (map: "+ Admin.tsx AutoApprovePanel")

## Users

- [x] Users: Create user card (username, password, role select user/admin, auto-approve select) -> Jinja `createUser()` (`POST /ui/api/users/create`) **and** Admin.tsx `CreateUserForm` (username/password inputs, role select, auto-approve checkbox, same endpoint via `api.createUser`) -> planned home: Users (map: "Admin.tsx users CRUD"; dual source, one line)
- [x] Users: all-users table (username, role, auto-approve indicator, enabled indicator, last login) -> Jinja `loadUsersTab()` (`GET /ui/api/users`) **and** Admin.tsx's users table (`useQuery(api.users)`) -> planned home: Users (dual source)
- [x] Users: Auto-approve toggle per user -> Jinja `toggleAutoApprove()` **and** Admin.tsx `Toggle` component wired to `updateMut` -> both call `POST /ui/api/users/<id>/update` -> planned home: Users (dual source; route is a template-literal fetch, `` `/ui/api/users/${id}/update` ``, in both sources)
- [x] Users: Enabled toggle per user -> Jinja `toggleEnabled()` **and** Admin.tsx `Toggle` component wired to `updateMut` -> both call `POST /ui/api/users/<id>/update` -> planned home: Users (dual source)
- [x] Users: plugin-contributed per-user field toggles (dynamic columns from `GET /ui/api/plugins` `user_fields`/`admin_fields`) -> Jinja `togglePluginField()` **and** Admin.tsx's `pluginUserFields` toggle cells wired to `updateMut` -> both call `POST /ui/api/users/<id>/update` -> planned home: Users (dual source)
- [x] Users: Delete user button (confirm) -> Jinja `deleteUser()` (invoked via a single-quoted `onclick='deleteUser(...)'` attribute so it does not match the brief's double-quote grep) **and** Admin.tsx's Delete button wired to `deleteMut` -> both call `POST /ui/api/users/<id>/delete` -> planned home: Users (dual source; route is a template-literal fetch in both sources)

## Filter rules

- [x] Filter rules: RESOLUTION category editor (strict toggle, add-to-state select, remove chip, reorder within Preferred, expand/collapse, "+N more" overflow) -> `static/admin/filter_rules.js` `initFilterRules()` -> planned home: Filter rules (Task 10: ported via `frontend/src/pages/admin/filterRulesModel.ts` + `FilterRules.tsx`; the whole-category expand/collapse for an empty category is dropped - all seven panels always render open - but the per-row "+N more" chip overflow (`visibleChips`) is ported and proven equivalent to the original by test)
- [x] Filter rules: SOURCE category editor (same control set) -> `filter_rules.js` -> planned home: Filter rules (Task 10)
- [x] Filter rules: ENCODE category editor (same control set) -> `filter_rules.js` -> planned home: Filter rules (Task 10)
- [x] Filter rules: VISUAL_TAG category editor (same control set) -> `filter_rules.js` -> planned home: Filter rules (Task 10)
- [x] Filter rules: AUDIO_TAG category editor (same control set) -> `filter_rules.js` -> planned home: Filter rules (Task 10)
- [x] Filter rules: AUDIO_CHANNELS category editor (same control set) -> `filter_rules.js` -> planned home: Filter rules (Task 10)
- [x] Filter rules: LANGUAGE category editor (same control set, plus a code-to-language-name display map) -> `filter_rules.js` -> planned home: Filter rules (Task 10)

All seven write into the same `settings-form` as hidden `setting_<CATEGORY>_<STATE>`
fields and are saved together by the Settings tab's "Save all" (`POST /ui/settings`).

## Scrapers

- [x] Scrapers: Zilean native index controls (Sync now, Import from Postgres, Status poll with inline error text) -> `zileanSync()`/`zileanImport()`/`zileanStatus()`, `POST /ui/api/zilean/sync`, `POST /ui/api/zilean/import`, `GET /ui/api/zilean/status` -> planned home: Scrapers (explicit in map)

The Zilean *configuration* fields (`ZILEAN_MODE`, Postgres host/port/user/db, etc.)
render as part of the generic settings-group table (`g.id === 'zilean_native'`) and
go to Settings per the map's "settings groups minus filter_rules" - only the action
buttons above move to Scrapers.

## Logs

- [x] Logs: log viewer box (tail last N lines, auto-scroll only if already at bottom) -> `fetchLogs()` / `GET /ui/logs` -> planned home: Logs
- [x] Logs: Auto ON/OFF toggle (5s poll cadence) -> `toggleAuto()` / `scheduleLogs()` -> planned home: Logs

## Maintenance

- [x] Maintenance: Repair strm files button -> `POST /ui/repair-all` -> planned home: Maintenance
- [x] Maintenance: Run cleanup button -> `POST /ui/run-cleanup` -> planned home: Maintenance
- [x] Maintenance: Auto-upgrade button -> `POST /ui/auto-upgrade` -> planned home: Maintenance
- [x] Maintenance: Consolidate packs button -> `POST /ui/pack-consolidate` -> planned home: Maintenance
- [x] Maintenance: Merge series button (confirm dialog) -> `POST /ui/merge-series` -> planned home: Maintenance
- [x] Maintenance: Fix IMDB titles button -> `fixImdbTitles()` / `POST /ui/api/fix-imdb-titles` -> planned home: Maintenance
- [x] Maintenance: Clear retry queue button (confirm) -> `clearRetryQueue()` / `POST /ui/api/retry-queue/clear` -> planned home: Maintenance
- [x] Maintenance: Fix library titles button (rewrites tvshow.nfo titles) -> `repairTvshowTitles()` / `POST /ui/api/repair-tvshow-titles` -> planned home: Maintenance
- [x] Maintenance: Sync Seerr button -> `POST /ui/sync-movies` -> planned home: Maintenance
- [x] Maintenance: Import TorBox library button -> `POST /ui/library-import` -> planned home: Maintenance
- [x] Maintenance: Fix covers button -> `POST /ui/refresh-images` -> planned home: Maintenance
- [x] Maintenance: Generate NFOs button -> `POST /ui/generate-nfos` -> planned home: Maintenance
- [x] Maintenance: Vacuum DB button (confirm) -> `POST /ui/db-vacuum` -> planned home: Maintenance
- [x] Maintenance: Recovery wizard button (confirm) -> `POST /ui/recovery` -> planned home: Maintenance
- [x] Maintenance: repair summary stat tiles (scanned/repaired/deleted/unfixable/last run) -> `refreshRepair()` / `GET /ui/api/repair` -> planned home: Maintenance
- [x] Maintenance: repair history table (search, sort, paginate) -> `refreshRepair()`/`initRepairPagination()` / `GET /ui/api/repair` -> planned home: Maintenance
- [ ] Maintenance: force strm rescan (topbar circular-arrow icon) -> `forceRescan()` / `POST /ui/strm-rescan` -> planned home: Maintenance (placement chosen by inventory - lives in the global topbar, not the Maintenance tab-pane, but is functionally a maintenance action)
- [ ] Maintenance: manual release search by IMDB id/season/episode + candidate list (cached badge, season-pack badge, size, seeders) -> `doSearch()` / `POST /ui/api/search-candidates` -> planned home: Maintenance (placement chosen by inventory - no live control in the current 8-tab markup reaches this, see Findings; kept because it is the only path to Add magnet, which the map places here)
- [x] Maintenance: Add magnet button (per search candidate) -> `POST /ui/add-magnet` -> planned home: Maintenance (explicit in map)
- [x] Maintenance: TorBox torrent list + per-row Delete (confirm) -> `refreshTorbox()` / `GET /ui/api/torbox-list`, `POST /ui/torbox-delete` -> planned home: Maintenance (explicit in map; no live control reaches `refreshTorbox()` currently, see Findings)
- [x] Maintenance: Radarr/Sonarr import (Test Radarr, Import Radarr, Test Sonarr, Import Sonarr, Status poll) -> Jinja `arrTest()`/`arrRun()`/`arrStatus()` (rendered under the Settings tab's `arr_import` group) **and** Admin.tsx `ArrImportPanel` (same three actions) -> planned home: Maintenance (map: "+ Admin.tsx ArrImportPanel"; dual source, one line per instructions)
- [x] Maintenance: Sync all series + episodes button (series backfill, confirm dialog) -> Admin.tsx `ArrImportPanel` / `POST /ui/api/series-backfill` -> planned home: Maintenance
- [x] Maintenance: Migrate to canonical names button (confirm) -> Admin.tsx `MaintenancePanel` / `POST /ui/api/migrate-canonical` -> planned home: Maintenance
- [x] Maintenance: Clean up duplicate strm files button -> Admin.tsx `MaintenancePanel` / `POST /ui/api/cleanup-duplicate-strms` -> planned home: Maintenance
- [x] Maintenance: Repair broken strm links button -> Admin.tsx `MaintenancePanel` / `POST /ui/api/repair-strms` -> planned home: Maintenance
- [x] Maintenance: Scan TorBox library button -> Admin.tsx `MaintenancePanel` / `POST /ui/api/torbox/scan-library` -> planned home: Maintenance
- [x] Maintenance: backup list + per-backup Restore (confirm) -> `toggleBackupList()` / `GET /ui/api/backups`, `POST /ui/backup-restore` -> planned home: Maintenance (explicit in map; no live control reaches `toggleBackupList()` currently, see Findings)
- [x] Maintenance: per-title quality-override Clear button -> `POST /ui/show-override-delete/<imdb_id>` -> planned home: Maintenance (explicit in map; reached only via the dead `refreshOverrides()` list, see Findings)
- [ ] Maintenance: per-title quality-override list + set form (view current overrides; set quality_preference/allow_4k/prefer_hevc/notes per imdb_id) -> `refreshOverrides()` / `GET /ui/api/show-overrides`, `POST /ui/show-override` -> planned home: Maintenance (placement chosen by inventory - the map only names the delete action; the list has no live control and the set form has *no* control at all, live or dead - also listed as an orphan route below)
- [ ] Maintenance: virtual items / catbox status list (title, media type, live-in-TorBox badge, play count, last played, created, info hash) -> `refreshCatbox()` / `GET /ui/api/virtual-items` -> planned home: Maintenance (placement chosen by inventory - not named in the map and no live control reaches it; closest existing admin surface, `GET /ui/api/playability-state` / `GET /ui/api/integrity`, is CLAUDE.md's own documented "open point" #4, "playability state table in UI")

## Blacklist

- [x] Blacklist: failed-hash table (search, sort, paginate) -> `refreshBlacklist()` / `GET /ui/api/blacklist` -> planned home: Blacklist
- [x] Blacklist: per-row Clear button (confirm) -> `POST /ui/blacklist-clear/<info_hash>` -> planned home: Blacklist

## Settings

- [ ] Settings: dynamic settings-group renderer (per-key text/number/checkbox/select/list inputs; hot-reload lightning-bolt vs restart-required warning badge; override-active badge; secret-field masking with "already set - type to replace") -> `refreshSettings()` / `GET /ui/api/settings`, `POST /ui/settings` -> planned home: Settings
- [ ] Settings: Deployment Mode toggle (Full vs Lite radio tiles, restart required) -> inline in `refreshSettings()` -> planned home: Settings
- [ ] Settings: restart-required banner (dirty-diff against initial values of restart-required keys) -> `settings-form` `input` listener -> planned home: Settings
- [ ] Settings: Save all button + "empty a field clears the override" hint -> `POST /ui/settings` -> planned home: Settings
- [ ] Settings: Re-run setup wizard link -> `GET /setup?rerun=1` -> planned home: Settings
- [ ] Settings: Auto-add now button -> `autoAddNow()` / `POST /ui/api/auto-add-now` -> planned home: Settings
- [ ] Settings: Discover genre tabs editor (Admin.tsx `DiscoverGenreTabsPanel`: add/edit/remove tab rows, save) -> `api.genreTabsConfig` / `setGenreTabsConfig` -> planned home: Settings (explicit in map)

Notification-channel settings (`api.setNotificationSettings`, `POST /ui/api/settings/notifications`)
are already wired in `frontend/src/pages/Settings.tsx`, a page outside this
inventory's two named sources. Not given its own checklist line here (Settings.tsx
was not part of the brief's walk scope), but confirmed non-orphan - see Findings.

---

## Orphan routes

Admin-facing POST routes under `/ui/` that neither the Jinja controls (live or
dead) nor Admin.tsx/api.ts reach. Found by reading every `@app.get`/`@app.post`
decorator in `app.py` for a `/ui/...` path (the brief's literal
`grep -oE '"/ui/[a-z-]+"'` only catches single-segment, non-dynamic routes and
misses most of these - see "Cross-check method" below) and grepping each
candidate against `templates/ui.html` and all of `frontend/src`.

- [ ] `POST /ui/set-password` (admin resets the logged-in admin's own password via a legacy form) -> planned home: Users (orphan route, verify before porting - likely superseded by the already-used `POST /ui/api/me/password`, but semantics were not diffed)
- [ ] `POST /ui/submit` (manual "add title by IMDB id + seasons" admin form) -> planned home: Maintenance (orphan route, verify before porting)
- [ ] `POST /ui/search-episode` (manual per-episode search trigger) -> planned home: Maintenance (orphan route, verify before porting)
- [ ] `POST /ui/download-movie` (manual movie download trigger) -> planned home: Maintenance (orphan route, verify before porting)
- [ ] `POST /ui/api/spore/backfill` (generate missing Spore stub .mkv/.minfo for all virtual_items) -> planned home: Maintenance (orphan route, verify before porting - Spore is not deployed on the current VPS per CLAUDE.md, so low priority)
- [ ] `POST /ui/api/spore/regenerate` (force-regenerate stub MKVs, optionally for one token) -> planned home: Maintenance (orphan route, verify before porting - same Spore caveat; CLAUDE.md documents an equivalent `docker exec ... python3 -c "import strm_generator..."` CLI path instead of this HTTP route)
- [ ] `POST /ui/test-notify` (test configured notification channels) -> planned home: Settings (orphan route, verify before porting - natural sibling of the notification settings already in `Settings.tsx`)
- [ ] `POST /ui/retry-request/<int:row_id>` (legacy form-based retry, redirects back to the dashboard) -> planned home: Requests (orphan route, verify before porting - `POST /ui/api/requests/<id>/retry` already covers this via `frontend/src/pages/Requests.tsx`, so this may be dead weight to delete rather than port)
- [ ] `POST /ui/backup-now` (trigger an immediate DB backup) -> planned home: Maintenance (orphan route, verify before porting - sibling of backup-restore, which does have a control)
- [ ] `POST /ui/trending-now` (manual trending pre-cache trigger, redirects to `#overview`) -> planned home: Overview (orphan route, verify before porting)
- [ ] `POST /ui/continue-watching` (manual continue-watching prioritization trigger, redirects to `#overview`) -> planned home: Overview (orphan route, verify before porting)
- [ ] `POST /ui/db-prune` (prune rows older than 90 days, redirects to `#overview`) -> planned home: Overview (orphan route, verify before porting)
- [ ] `POST /ui/quota-check` (manual TorBox quota check + warn, redirects to `#overview`) -> planned home: Overview (orphan route, verify before porting)
- [ ] `POST /ui/show-override` (set a per-title quality override: quality_preference/allow_4k/prefer_hevc/notes) -> planned home: Maintenance (orphan route, verify before porting - unlike its sibling `show-override-delete`, this one has no control anywhere, live or dead)

Not counted as orphans: `POST /api/run-cleanup` and `POST /api/generate-nfos`
(no `/ui` prefix) are admin-gated JSON twins of `/ui/run-cleanup` and
`/ui/generate-nfos`, which already have live Maintenance buttons. They read as
external/API automation aliases rather than a second UI surface needing its
own control, but are worth a mention if this plan ever audits the bare `/api/`
namespace too.

---

## Findings (not checklist items, context for later tasks)

1. **Dead JS in `ui.html` beyond what the brief names.** `refreshCatbox()`,
   `refreshOverrides()`, `doSearch()`/`search_imdb`/`candidates`, and the entire
   Discover/Watchlist block (`dscInitDiscover`, `loadWatchlist`,
   `dscOpenDetails`, `dscAddToLibrary`, `dscToggleWatchlist`, provider chips,
   poster grid, modal) reference DOM ids (`torbox-body`, `overrides-body`,
   `catbox-body`, `search_imdb`, `discover-*`, `watchlist-*`) that do not exist
   anywhere in the current 8-tab markup. The tab bar only has `overview`,
   `requests`, `blacklist`, `maintenance`, `settings`, `users`, `logs`,
   `releases`. Confirmed by grepping every one of those ids against the whole
   file: each only appears inside the JS function that populates it, never in
   a `<div id=...>`.
   - The TorBox/backup/override/manual-search pieces are inventoried above
     anyway because the plan's own reconciliation map names their routes
     explicitly (`torbox-delete`, `backup-restore`, `show-override-delete`,
     `add-magnet`), so the plan authors clearly intend them to be ported.
   - The Discover/Watchlist block is **not** inventoried above: it duplicates
     functionality the React SPA already has as first-class pages
     (`frontend/src/pages/Discover.tsx`, `Watchlist.tsx`, per CLAUDE.md's own
     URL-structure table), it is not an admin feature, and it is not named
     anywhere in the plan's reconciliation map. Recommend deleting it from
     `ui.html` rather than porting it, but that is a call for whoever executes
     the later Maintenance-tab task, not this inventory.
   - Several `@app.post("/ui/...")` handlers (`trending-now`,
     `continue-watching`, `db-prune`, `quota-check`) `redirect(... + "#overview")`,
     and `show-override` redirects to `#overrides` - a tab-hash that no longer
     exists at all. This is a second, independent signal (beyond "no matching
     DOM id") that the dashboard used to have more tabs than the current eight
     and lost their buttons along the way without the routes being removed.

2. **The keyboard shortcut map is half stale.** `{'1':'overview','2':'requests',
   '3':'movies','4':'series','5':'wanted','6':'search','7':'torbox','8':'catbox',
   '9':'settings','0':'logs'}` - keys `3`-`8` name tabs that do not exist in the
   current tab bar (`movies`/`series`/`wanted`/`search`/`torbox`/`catbox`), and
   even the working keys no longer match the *visual* tab order (blacklist,
   maintenance and users sit between requests and settings/logs now).

3. **Two other admin-adjacent React pages already exist outside the brief's
   named sources**, discovered only while verifying Step 3's orphan list:
   `frontend/src/pages/Settings.tsx` (494 lines, already implements the
   notification-settings mutation used above) and `frontend/src/pages/
   Requests.tsx` (implements "My requests" plus an admin-only
   `PendingApprovalsPanel`, and already calls `retryRequest`/`deleteRequest`/
   `purgeRequest`). `frontend/src/pages/AdminTabs.tsx` is the current
   `/admin`-route shell: it literally says in its own comment that Admin.tsx
   "was built but never wired into any route" and shows it in a tab next to an
   iframe of the classic Jinja dashboard - which is the exact split-brain this
   12-task plan exists to fix. None of these three files were in this task's
   walk scope (`templates/ui.html` + `frontend/src/pages/Admin.tsx` only), so
   their controls are not separately itemized above, but later tasks that
   build each React tab should read them before assuming a tab starts empty.

## Cross-check method

The brief's exact commands, run as specified:

```
grep -oE '"/ui/[a-z-]+"' app.py | sort -u
grep -oE "'/ui/api/[a-z/-]+'" frontend/src/api.ts | sort -u
```

Both are intentionally narrow (no dynamic segments, no multi-level `/ui/api/...`
paths on the app.py side) and were only a starting point. The orphan list above
comes from a fuller pass: every `@app.get(...)`/`@app.post(...)` decorator whose
path starts with `/ui/` was extracted (140 routes total; routes are defined
with `@app.get`/`@app.post`, not `@app.route`, so a plain `@app.route` grep
finds nothing), and each was grepped individually against `templates/ui.html`
and all of `frontend/src` before being called reachable or orphaned.

A fix-round correction to this method: a route or function call can be quoted
three different ways in this codebase (double quotes, single quotes, or a
backtick template literal for anything with an interpolated id), and grepping
for only one style silently drops real matches - `deleteUser()` in
`templates/ui.html` is invoked via a single-quoted `onclick='deleteUser(...)'`
attribute, and both `/ui/api/users/<id>/update` and `/ui/api/users/<id>/delete`
are only ever called as backtick template literals
(`` `/ui/api/users/${id}/update` ``) in both `templates/ui.html` and
`frontend/src/api.ts`. The reachability sweep behind every line in this
document (not just Users) was re-run checking all three quote styles, so a
missing control in the sections above means it is genuinely absent, not an
artifact of one quote style.

## Summary

Total controls inventoried: **93** (78 from the Step 1/2 walk + 15 orphan routes
from Step 3). Every line above has a planned home; none are left unplaced.

| Planned tab    | Walked (Step 1/2) | Orphans (Step 3) | Total |
|----------------|-------------------|------------------|-------|
| Overview       | 17                | 4                | 21    |
| Requests       | 6                 | 1                | 7     |
| Users          | 6                 | 1                | 7     |
| Filter rules   | 7                 | 0                | 7     |
| Scrapers       | 1                 | 0                | 1     |
| Logs           | 2                 | 0                | 2     |
| Maintenance    | 30                | 7                | 37    |
| Blacklist      | 2                 | 0                | 2     |
| Settings       | 7                 | 2                | 9     |
| **Total**      | **78**            | **15**           | **93**|

`(placement chosen by inventory)` markers used: 6 (Overview theme toggle,
Overview keyboard shortcuts, Maintenance force-rescan, Maintenance manual
search, Maintenance override list+set form, Maintenance virtual-items list).
Every other line's planned home is either named directly in the plan's
reconciliation map or is an orphan route assigned to the tab that owns its
nearest sibling feature.
