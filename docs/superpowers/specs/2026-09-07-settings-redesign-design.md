# Settings redesign: schema-driven admin Settings

Date: 2026-09-07. Status: approved in conversation, awaiting file review.

## Goal

Replace the admin Settings tab (one long scroll of 136 raw keys, comma-text
inputs for known vocabularies, Test buttons only for Radarr and Sonarr)
with a schema-driven page: a section sidebar, one field renderer with
proper controls, a label and help line for every setting, a Test button for
every credentialed service, pickers for values that come from a service, a
Simple/Advanced switch, dependent fields, and a search box. Modelled on the
AIOStreams configuration UI.

Non-goals for this spec: the setup wizard (a follow-up plan reuses the
field kit), the end-user "My Settings" page, the Filter rules tab (kept,
linked from Quality), JSON export/import (declined).

## Decisions taken

| Question | Decision |
|---|---|
| Layout inside the Settings tab | Left sidebar of sections, one section visible at a time as cards |
| Scope | Admin Settings plus a shared field kit; wizard follows in a second plan |
| Behaviours | Simple/Advanced switch, dependent fields hidden until enabled, search box. No export/import |
| Where field metadata lives | Backend schema in `settings.py` is the single source of truth |

## 1. Schema

Each group in `settings.py` becomes a section: `id`, `title`, one-line
`description`, `icon` (a name the frontend maps to an icon), and an ordered
list of `fields`. A field is a dict:

```python
{
  "key": "RADARR_URL",
  "label": "Radarr URL",
  "help": "Base URL Mycelium can reach Radarr on, such as http://radarr:7878.",
  "kind": "url",              # bool | int | float | str | url | path | secret
                              # | select | multiselect | ordered | custom
  "options": None,            # list of {value,label}, or a resolver name
                              # ("languages", "sort_criteria") resolved per request
  "placeholder": "http://radarr:7878",
  "unit": None,               # int/float suffix: "minutes", "hours", "GB"
  "min": None, "max": None,   # int/float only
  "advanced": False,          # hidden in Simple mode
  "depends_on": "ARR_SYNC_ENABLED",   # bool key, or "KEY=value" for a select
  "test": "radarr",           # service test this field feeds; one button per service per section
  "picker": None,             # "radarr_root_folders", "radarr_quality_profiles", ...
  "component": None,          # kind "custom": frontend component name (ModeTiles, GenreTabs, ...)
  "readonly": False,          # e.g. the generated Seerr webhook secret, shown with a copy button
}
```

`kind` is derived from the existing type buckets (`_BOOL_KEYS`, `_INT_KEYS`,
`_FLOAT_KEYS`, `_LIST_KEYS`, `_ENUM_KEYS`) so coercion and rendering cannot
disagree; `secret`, `url`, `path`, `select`, `multiselect` and `ordered` are
explicit refinements of `str`/`list`. Secret detection moves from the
frontend regex to the schema. `HOT_RELOAD` keeps driving the restart badge.

`all_for_ui()` returns sections with fields, each field carrying the
declaration plus `value`, `overridden` (a DB override exists), `hot_reload`,
and resolved `options`. Save stays one `POST /ui/settings` call with the
same coercion; an empty value clears the override as today.

Guard tests: every typed key appears in exactly one section (the auto-add
keys lose their duplicate home); every field has a non-empty `label` and
`help`; every `depends_on` names a real bool or select key; every `test`
and `picker` maps to a registered handler; `kind` agrees with the buckets;
no `--` or em-dash in any label or help.

### Sections, in order

Advanced fields are marked `*`.

1. **Mode**: Lite/full tiles (custom `ModeTiles`), `CATBOX_MODE`, `CATBOX_HOST`, lazy add, preload, idle minutes*, GC interval*.
2. **Debrid**: TorBox API key and base URL* (test `torbox`); multi-debrid toggle; RealDebrid key (test `realdebrid`, depends on multi-debrid).
3. **Scrapers**: Zilean toggle, `ZILEAN_MODE` select, external URL (test `zilean`, depends on `ZILEAN_MODE=external`), Postgres host/port/database/user/password (test `zilean_pg`, depends on `ZILEAN_MODE=native`); Debridio toggle, API key, base URL*, send-TorBox-key* (test `debridio`); Torrentio limits*.
4. **Jellyfin**: URL, API key (test `jellyfin`), `JELLYFIN_MEDIA_PATH`, refresh behaviour*.
5. **Seerr**: URL, API key (test `seerr`), `SEERR_REPORT_STATUS`, `SEERR_DECLINE_WANTED_AFTER_DAYS`, webhook secret (readonly, copy button).
6. **Radarr / Sonarr**: `ARR_SYNC_ENABLED`; per arr: URL, API key (test `radarr`/`sonarr`), root folder (picker), quality profile (picker, new keys); `ARR_STUBS_ENABLED`, `ARR_STUB_PATH` (depends on stubs); `ARR_SYNC_PURGE_ENABLED`; `ARR_SYNC_INTERVAL_MINUTES`*.
7. **Quality**: size and seeder floors, per-resolution caps, tie-break direction; a custom card `FilterRulesLink` summarising active rules and linking to the Filter rules tab.
8. **Subtitles**: OpenSubtitles key (test `opensubtitles`), languages (multiselect, resolver `languages`).
9. **Automation**: series sync, upgrader, cleanup toggles; Discover genre tabs (custom `GenreTabs`, moved from the page bottom).
10. **Auto-add**: trending/popular counts, min rating, min votes, region (select, static list shared with `RegionPicker`).
11. **Auto-approve**: daily limits, actor/genre rule rows (custom `GenreRuleRows`).
12. **Security**: session secret*, trusted proxy auth; `OIDC_ENABLED`, issuer, client id, client secret, scopes*, user claim* (test `oidc`, depend on OIDC); legacy password card (custom `LegacyPassword`, moved here).
13. **Notifications**: Discord webhook (test `discord`), Telegram token and chat id (test `telegram`), event toggles.
14. **Intervals**: every timer, all advanced. In Simple mode the section shows only the "all fields are advanced" notice.

The former `zilean_native` group folds into Scrapers as a dependent block.

## 2. Field controls

One renderer, `SettingField`, dispatches on `kind`. Every control sits in
the same frame: label left, control right, help line underneath in muted
text, an info button opening a popover when the help runs long. Badges
after the label: "restart" for non-hot-reload keys, "env" when the value
comes from the environment rather than the database.

| kind | Control |
|---|---|
| `bool` | `Toggle` (existing) |
| `int`, `float` | Number input with min/max/step and the unit as a suffix |
| `str` | Text input |
| `url` | Text input with a URL check; red hint before Save |
| `path` | Monospace text input |
| `secret` | Password input with a reveal eye; empty clears the override |
| `select` | `Select` dropdown |
| `multiselect` | Searchable multi-select with chips (type to filter, click to add, x to remove) |
| `ordered` | Orderable chip list with up/down arrows and a dropdown of unused criteria to add |
| `custom` | Named component rendered as a section card |

New primitives in `frontend/src/components/primitives/`: `Button`
(default, primary, ghost; loading state), `Select`, `MultiSelect` (on
`Select`), `OrderedList`. No new dependency.

**Service test.** Fields sharing a `test` name get one Test button next to
the last of them. It posts the current unsaved values for that service and
shows the result inline: green line with the returned message, red line
with the error, spinner while waiting.

**Pickers.** A field with `picker` gets a Load button. On success the text
input becomes a dropdown of the returned options with the current value
preselected; on failure it stays a text input with an error line, so a
hand-typed value still works.

**Dependent fields** do not render until their condition holds. Simple mode
hides `advanced` fields; a section whose fields are all hidden shows one
line saying so with a link that switches to Advanced. The mode is stored in
`localStorage`.

**Search** (top of the sidebar) filters sections to those with a match and,
inside the open section, dims non-matching fields rather than removing
them. Matching is on label, key and help, case-insensitive.

**Save.** Sticky bottom bar with the unsaved count and a Save button; the
existing restart-required warning stays. Save posts the flattened values.

## 3. Backend endpoints

**Tests.** `POST /ui/api/settings/test/<service>`, JSON body of that
service's field values (unsaved), returns `{ok, message, detail?}`. A
registry in a new `service_tests.py` maps names to functions; unknown names
are 404. The wizard testers (torbox, jellyfin, seerr, trakt, zilean,
discord, telegram, opensubtitles) move into the registry and
`POST /setup/test/<kind>` calls the same functions.

New testers, one request each, 8 s timeout, failures reported as "timed
out" or the status code, never logging the credential:

| Service | Check | Success message |
|---|---|---|
| `realdebrid` | `GET /user` | username and premium expiry |
| `debridio` | manifest fetch with the built config token | addon name and version |
| `tmdb` | `GET /configuration` | "TMDB key accepted" |
| `oidc` | `<issuer>/.well-known/openid-configuration` | issuer, and whether authorization and token endpoints were found |
| `zilean_pg` | connect and `SELECT 1` | server version |
| `radarr`, `sonarr` | `system_status()` plus the listing | version and movie/series count |

**Pickers.** `POST /ui/api/settings/picker/<name>` with the relevant field
values, returns `{options: [{value, label}]}`. Registered:
`radarr_root_folders`, `sonarr_root_folders` (existing code moves),
`radarr_quality_profiles`, `sonarr_quality_profiles` (new, one GET each).
The `/ui/api/arr-import/*` routes stay as thin aliases for one release.

**Quality profile settings.** New keys `RADARR_QUALITY_PROFILE` and
`SONARR_QUALITY_PROFILE` (blank means the arr's first profile, as today),
honoured by `arr_sync._defaults()`. Fixes the mirror silently depending on
profile order.

**Auth and CSRF.** Admin-only under the existing `/ui/api` guard, POST with
the SPA CSRF token, like the current arr test routes.

## 4. What moves or goes

- `frontend/src/pages/admin/Settings.tsx` is rewritten; `ArrTestButton` and
  `RootFolderPicker` are replaced by generic `ServiceTest` and `Picker`.
  `ModeCard`, `DiscoverGenreTabsPanel`, `LegacyPasswordCard`,
  `GenreRuleRows` become `custom` field components.
- `Settings.test.tsx` is rewritten with it.
- The user-facing `pages/Settings.tsx` is untouched.
- No database migration. Two new settings keys with blank defaults. No
  stored value changes meaning. Rollback is a redeploy of 0.16.1.

## 5. Testing

Backend (pytest, existing conventions: no `app.py` import, `_isolated_db`
per file, faked HTTP seams, mutation checks on new tests):

- schema guards as listed in section 1;
- serializer output for a known key, resolved options, `overridden` for DB vs env;
- each tester with one success and one failure case; unknown name 404; timeout message;
- pickers with faked arr responses; failure returns an error, not an empty list;
- `arr_sync._defaults()` honours the profile settings and falls back when blank;
- source-text assertions that the wizard route and the arr-import aliases go through the registries.

Frontend (vitest): `SettingField` per kind; secret mask and reveal;
dependent hide/show; Simple mode hides advanced and shows the notice;
search narrows and dims; `OrderedList` moves a chip; Save posts flattened
values and shows the unsaved count; service test shows message and error.
`tsc --noEmit` clean; built `static/app/` committed.

## 6. Delivery

One plan, six tasks in dependency order:

1. Schema in `settings.py` with guard tests.
2. `service_tests.py` and picker registry with routes; wizard and arr-import routes rerouted; quality profile keys.
3. Primitives `Button`, `Select`, `MultiSelect`, `OrderedList`.
4. `SettingField`, `ServiceTest`, `Picker`, section renderer.
5. Sidebar shell with Simple/Advanced, search and the save bar, wired into the admin tab.
6. Copy pass over all fields; `docs/INTEGRATIONS.md`, manual and CHANGELOG.

Subagent-driven with an opus whole-branch review. Released as 0.17.0 on
request. The wizard conversion is a separate plan.

## Risks

The copy is the long pole: 136 short descriptions written from the code and
the manual, some of which may need correction once seen live. The rewrite
replaces working code wholesale, so the frontend tests are rewritten with
it. Storage does not change, so rollback is a plain redeploy.
