# 1.0 readiness: compatibility promise, structural refactor, docs sweep

Date: 2026-09-14. Status: approved in conversation, awaiting file review.
Closes the "1.0-gereedheid" item that has been on the list since 0.17.

## Goal

Release 1.0.0 as a version other people can build on: a written
compatibility promise over the integration endpoints and the environment
variables, a codebase whose biggest modules are split along their
responsibilities before the promise freezes anything, documentation that
matches the code from 0.17 through 0.29, an upgrade and rollback procedure,
and a report comparing Mycelium's catbox with ElfHosted's CatBox so the
post-1.0 roadmap starts from facts.

## Decisions taken

| Question | Decision |
|---|---|
| Audience of the promise | Others, not only the operator: frozen integration surface, deprecation cycle, breaking changes marked and major-bumped |
| Which routes are public | The integration routes only: `/webhook`, `/webhook/arr`, `/stream/<token>`, `/spore-stream/<token>`, `/internal/stream-resolve/<token>`, `/internal/stream-report/<token>`, `/health`, `/healthz`, `/metrics`, `/setup`, `/setup/schema`, `/setup/picker/<name>`, `/setup/save`, `/setup/test/<kind>`, `/setup/skip`, `/docs/<path>`. Everything under `/ui/api/*` and `/ui/*` is internal to the bundled SPA |
| Variable tiers | Derived from the Settings schema: supported (listed, not advanced), advanced (listed, flagged advanced), internal (`_UNLISTED_KEYS`); plus a hand-written deployment tier for the 32 variables read from the environment only |
| Refactor scope | Structural: `app.py` into blueprints per section, `catbox.py` into materialize, jobs and packs; plus safe cleanups everywhere. Behaviour unchanged, the test suite is the guard |
| Order | Review and refactor first, so the guards and the docs describe the final layout |
| Catbox comparison | A research report against ElfHosted's public CatBox documentation, rating each gap; building anything from it is post-1.0 work |
| Version | 1.0.0; the changelog links the compatibility document |

## 1. The compatibility promise: `docs/COMPATIBILITY.md`

One document, in this order:

1. **What is frozen.** The integration routes above, each with its method,
   the request it accepts and the response it returns, in prose with one
   example per route. The admin API is named as internal: it may change in
   any release without notice.
2. **Environment variables by tier.** Four tables (supported, advanced,
   deployment, internal) generated from the schema and `config.py`, each
   row: name, default, one-line meaning. The supported and advanced tables
   carry the promise; deployment variables are promised too (they are how
   the container is run); internal ones are not.
3. **The deprecation rule.** A promised variable or route is removed only
   after one minor release in which it still works and the startup log
   warns once, naming the replacement. The changelog lists it under
   `### Deprecated` in that release and under `### Removed` in the next.
4. **Breaking changes.** Anything that breaks a promised surface gets a
   `### Breaking` heading in the changelog and a major version bump.
5. **Database.** Forward migrations are idempotent; every 1.x database opens
   on any later 1.x; rolling back one minor version leaves unused columns
   and tables behind and nothing else (verified per release in
   `docs/RECOVERY.md`).
6. **Versioning.** Semantic: patch for fixes, minor for features and
   deprecations, major for breaking changes.

Guard tests in `tests/test_compatibility.py`:

- The route list in the document equals the set of routes registered
  outside the `ui` blueprints (read from the blueprint modules' source, not
  by importing `app.py`).
- The variable tables equal the schema tiers plus the deployment list in
  `config.py`; a variable in `config.py` that is in no tier fails the test.
- Every deprecated name in the startup warning map has a replacement and a
  changelog line.

## 2. Structural refactor

Preceded by one whole-codebase review (most capable model) whose findings
feed the refactor tasks. The review's output is a findings file in the
plan workspace, triaged by the controller into "this pass" and "after 1.0".

### `app.py` into blueprints

Today 3843 lines, 197 routes, sixteen commented sections. The plugin
system already registers Flask blueprints (`plugins/trakt/routes.py`), so
the pattern exists. Target layout under a new package `routes/`:

| Module | Section today | Routes |
|---|---|---|
| `routes/integration.py` | Webhook, health, metrics, docs | the frozen routes above except setup and stream |
| `routes/setup.py` | Setup wizard | `/setup*` |
| `routes/stream.py` | Catbox lazy materialization, the loopback resolve and report | `/stream`, `/spore-stream`, `/internal/*`, `/ui/api/virtual-items*` |
| `routes/admin_library.py` | Library, requests admin, release swap, TorBox accounts, maintenance triggers | `/ui/api/library*`, `/ui/api/admin/*`, `/ui/api/torbox-*`, upgrader and trending triggers |
| `routes/admin_settings.py` | Settings, scrapers, users, auto-add, arr import, webhook secret | `/ui/settings`, `/ui/api/settings*`, `/ui/api/users*`, `/ui/api/scraper*` |
| `routes/spa.py` | Discover, watchlist, user requests, SPA shell | `/ui/api/discover*`, `/ui/api/watchlist*`, `/ui/api/user-requests*`, `/`, `/app/*` |
| `app.py` | App factory, auth hooks, scheduler, startup | no routes |

Rules: a route moves verbatim, decorators and all; module-level helpers
move with the routes that use them; `app.py` keeps `create_app()` (new),
the `before_request` auth gate, the scheduler setup and the startup block.
The 60 test call sites that read `_src("app.py")` are updated to read the
module the route lives in; a helper `tests/_routes.py` resolves a route
path to its module so later moves cost one line. No route path, method,
auth check or response changes: a test `test_route_table_is_unchanged`
compares the set of `(method, path)` pairs before and after, stored as a
fixture generated at the start of the task.

### `catbox.py` into three modules

| Module | Contents |
|---|---|
| `catbox.py` | `register`, `proxy_url`, `materialize`, `_materialize_locked`, `_home`, `_adopt_or_choose`, `_auth_failed`, the fail cooldown, the scan-burst guard, the URL cache, the token and pack locks (the play path) |
| `catbox_jobs.py` | `release_idle`, `reconcile_torbox_ids`, `last_reconcile`, `_account_lists`, the cache sweep |
| `catbox_packs.py` | `_resolve_pack_files`, `_reconcile_pack`, `_detach_episode`, `_search_detached`, `_start_detached_search`, `_series_title` |

Names that other modules import (`catbox.release_idle`,
`catbox.reconcile_torbox_ids`, `catbox.last_reconcile`,
`catbox._token_lock`, `catbox._pack_lock`, `catbox.invalidate_url_cache`)
keep working through re-exports in `catbox.py` for this release, so the
scheduler, the overview and the tests need no change; the re-exports are
listed in the module docstring and removed in 1.1.

### Safe cleanups, from the review

Dead code and unused imports, duplicated helpers, misleading names,
functions over 120 lines split inside their module, comment and docstring
drift (including the "Task N replaces this" leftovers), test hygiene
(the `sys.modules` import dances consolidated into one helper in
`tests/_torbox_import.py`), and the retired `EXCLUDE_DV_P5` read in
`config.py`. Each cleanup is its own commit with the covering tests named.

## 3. Documentation sweep

Against the code from 0.17 to 0.29, file by file:

- `README.md`: the admin UI description (ten tabs, no classic UI), the
  configuration section pointing at `docs/COMPATIBILITY.md` for the full
  variable list, the account pool, season swap, Jellyfin 12, the pack
  behaviour, the removed continue-watching setting; the roadmap section
  reflects the post-1.0 list.
- `docs/install-guide.html` (rendered by the in-app manual): every
  screenshot-free step checked against the wizard and the Settings page as
  they are; removed options go.
- `docs/INTEGRATIONS.md`, `docs/SCALING.md`, `docs/RECOVERY.md`: verified
  and extended (RECOVERY per section 4).
- `.env.example`: every variable exists in `config.py`, every deployment
  variable is present with its default, order follows the tiers.
- `CHANGELOG.md`: nothing rewritten; a `## [1.0.0]` entry.

A guard test `tests/test_docs_references.py` checks that every variable
name and route path mentioned in these files exists, so a future removal
fails the suite until the docs follow.

## 4. Upgrade and rollback: `docs/RECOVERY.md`

New sections: the upgrade procedure (pull, up, watch the startup log for
the version line and migration lines), the pre-upgrade backup (a manual
`backup.run()` call documented, since the scheduled backup is periodic, not
pre-migration; a startup hook that runs `backup.run()` once when the stored
version differs from `APP_VERSION` is added and documented), rolling back
one minor version (which columns and tables each release since 0.17 added
and that older code ignores them), and what cannot be rolled back (none
today; the section says so and is kept per release). A startup log line
`Mycelium <version>, database schema from <previous version>` uses a new
`schema_version` setting written after migrations.

## 5. Catbox comparison report

A research task with no code: read ElfHosted's CatBox documentation and
the Jellyfin, Plex and Emby guides that use it; list every behaviour;
map each to Mycelium as same, different by design, or missing; rate each
missing behaviour useful or not for a four-to-six-user Jellyfin setup with
an effort estimate; note every place Mycelium's own docs describe the
catbox differently from what the code does. Deliverable:
`docs/superpowers/reports/2026-09-14-catbox-comparison.md`, committed.
Candidates known before the research: metadata probe answering before the
first play (the parked Jellyfin item), a qBittorrent-compatible API for
arr tools versus the stub files, retention handling inside TorBox's thirty
days, removal after play versus idle release, multi-debrid behaviour.

## 6. Release

`APP_VERSION = "1.0.0"`, the changelog entry (Added: the compatibility
document, the upgrade procedure; Changed: the module layout, with the
note that no route or variable changed), `releases.json`, tag `v1.0.0`,
the local notes. Release on request, as always.

## Testing

Every refactor task keeps the full suite green with no test weakened; the
route-table fixture and the re-export list are the two invariants. New
guard tests: compatibility (routes, variables, deprecations), docs
references, schema version and the pre-upgrade backup hook. Frontend
unchanged except the manual's document, so `tsc`, `vitest` and the build
run once at the end.

## Delivery

Eight tasks, subagent-driven, each reviewed: (1) whole-codebase review,
findings file; (2) `app.py` into blueprints with the route-table fixture
and the test helper; (3) `catbox.py` split with re-exports; (4) safe
cleanups from the review; (5) compatibility document, deprecation map and
guard tests; (6) upgrade and rollback: backup hook, schema version,
RECOVERY; (7) docs sweep and docs guard test; (8) catbox comparison report
(independent, may run alongside 5 to 7 since it touches no shared file).
One opus whole-branch review, one fix wave, then 1.0.0 on request. Three
to four days.

## Risks

- The blueprint split touches every route in one task. The route-table
  fixture and the 60 updated source-text tests are the net; the task is
  reviewed on the most capable model and nothing else lands between the
  split and its review.
- A promise is only as good as the next release. The guard tests make a
  silent break impossible; a deliberate one still needs the deprecation
  cycle, which the changelog convention enforces by review.
- The comparison report may show a large gap (the qBittorrent shim). That
  is roadmap input, not a 1.0 blocker.
