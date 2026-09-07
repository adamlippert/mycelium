# Setup wizard on the settings schema

Date: 2026-09-07. Status: approved in conversation, awaiting file review.
Follows `2026-09-07-settings-redesign-design.md` (shipped as 0.17.0).

## Goal

Convert the setup wizard from twelve hand-written step files with their own
inputs, state and test button to a thin shell that renders steps declared
next to the settings schema, using the same `SettingField` renderer, Test
buttons and pickers as the Settings page. Gains: one place for labels and
controls, pre-filled values on a re-run, dropdowns and pickers in the
wizard, Test buttons for every service in it. Removes: the wizard's own
field kit, its `SetupData` state, and the server-side translation of four
retired setting names.

Non-goals: changing what setup does after save (admin creation, redirect),
adding an Advanced mode to the wizard, touching the Settings page.

## Decisions taken

| Question | Decision |
|---|---|
| How steps are defined | `WIZARD_STEPS` in `settings.py`, each naming a title, an intro and schema keys in order |
| The Preferences step | Edits the real rule keys (`RESOLUTION_PREFERRED`, `RESOLUTION_EXCLUDED`, `ENCODE_PREFERRED`, `LANGUAGE_PREFERRED`); the retired-key translator is deleted |
| Lite mode | Steps carry `lite: True/False`; Lite hides the non-lite steps, live |
| Advanced fields | Not applicable; a step shows exactly its declared keys, `depends_on` still applies |
| Pre-fill | Yes, from current values (secrets as set/not-set), on first run and re-run |

## 1. Backend

### Wizard steps

`settings.WIZARD_STEPS`: an ordered list of
`{"id", "title", "intro", "keys": [...], "lite": bool}`.

| id | title | keys | lite |
|---|---|---|---|
| `welcome` | Welcome | `LITE_MODE` | True |
| `torbox` | TorBox | `TORBOX_API_KEY` | True |
| `jellyfin` | Jellyfin | `JELLYFIN_URL`, `JELLYFIN_API_KEY`, `JELLYFIN_MEDIA_PATH` | True |
| `seerr` | Seerr and metadata | `SEERR_URL`, `SEERR_API_KEY`, `TMDB_API_KEY` | True |
| `quality` | Quality preferences | `RESOLUTION_PREFERRED`, `RESOLUTION_EXCLUDED`, `ENCODE_PREFERRED`, `LANGUAGE_PREFERRED` | True |
| `catbox` | Catbox | `CATBOX_MODE`, `CATBOX_HOST` | True |
| `notifications` | Notifications | `DISCORD_WEBHOOK_URL`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | True |
| `trakt` | Trakt | `TRAKT_CLIENT_ID`, `TRAKT_CLIENT_SECRET` | False |
| `subtitles` | Subtitles | `OPENSUBTITLES_API_KEY`, `OPENSUBTITLES_LANGUAGES` | False |
| `zilean` | Zilean | `ZILEAN_ENABLED`, `ZILEAN_MODE`, `ZILEAN_URL`, `ZILEAN_PG_HOST`, `ZILEAN_PG_PORT`, `ZILEAN_PG_DB`, `ZILEAN_PG_USER`, `ZILEAN_PG_PASSWORD` | False |
| `arrs` | Radarr / Sonarr | `ARR_SYNC_ENABLED`, `RADARR_URL`, `RADARR_API_KEY`, `RADARR_ROOT_FOLDER`, `RADARR_QUALITY_PROFILE`, `SONARR_URL`, `SONARR_API_KEY`, `SONARR_ROOT_FOLDER`, `SONARR_QUALITY_PROFILE` | False |

Each `intro` is one sentence saying what the step configures and whether it
can be skipped. Guard tests: every key names a field known to
`fields_by_key()`, no key appears in two steps, every step has a non-empty
title and intro, no dashes.

### Rule fields

`settings.RULE_FIELDS`: field declarations (same shape as section fields)
for the four rule keys the wizard edits. Not part of `SECTIONS`, so the
Settings page is unchanged; `fields_by_key()` returns sections' fields plus
these. `RESOLUTION_PREFERRED` is `ordered`; the other three `multiselect`.
Options come from new resolvers `rule:resolution`, `rule:encode`,
`rule:language` that return `release_tags.values_for(category)` without
`unknown`, as `{value, label}` with `label == value`. Copy:

- `RESOLUTION_PREFERRED`, "Preferred resolutions": "Most wanted first. A release in a higher-ranked resolution wins over a lower one."
- `RESOLUTION_EXCLUDED`, "Resolutions to skip": "Add 2160p here to avoid 4K releases, for example on a player without HDR."
- `ENCODE_PREFERRED`, "Preferred encodes": "hevc is smaller for the same quality; avc plays on more devices."
- `LANGUAGE_PREFERRED`, "Preferred audio languages": "Releases with these audio languages rank first."

### Required fields

Field declarations gain `required: bool` (default False), True only for
`TORBOX_API_KEY`. The wizard disables Continue while a required field on the
current step is blank and not already set; Settings ignores the flag.

### Schema route

`GET /setup/schema`, gated exactly like `/setup/save`: open while
`SETUP_COMPLETE` is false, admin afterwards. Returns
`{"steps": WIZARD_STEPS, "fields": [...], "needs_first_admin": bool}` where
`fields` is the `schema_for_ui()` field shape (value, overridden,
hot_reload, resolved options) for every key any step references, including
the rule fields. Secrets report set/not-set only.

### Pickers pre-auth

`POST /ui/api/settings/picker/<name>` accepts the same predicate as
`/setup/test/<kind>`: admin, or setup not yet complete. The test route
`/ui/api/settings/test/<service>` gets the same widening. Both are POST
under CSRF as before. `/setup/test/<kind>` stays as an alias for one release.

### Save

`POST /setup/save` unchanged in shape (`KEY=value` form fields, `""` clears
the override, bools coerced, `settings.set()` validates). `_allowed_keys`
becomes `set(fields_by_key()) | {"SETUP_COMPLETE"}`, so the rule keys are
accepted and validated against their vocabulary. The retired-key path
(`migrate_filters.WIZARD_KEYS`, `translate_wizard_keys`, the
`wizard_form` block in `setup_save`, `tests/test_setup_wizard_keys.py`) is
deleted. `migrate_filters.RETIRED` stays for `warn_stale_env`.

## 2. Frontend

### Shell

`frontend/src/pages/Setup.tsx` fetches `/setup/schema` on mount. State:
`values` and `initial` from `initialValues()` over the returned fields,
`step` index, `account` for the bookend. `steps` are the payload's steps
filtered by `lite` when `values.LITE_MODE` is true. The rail (`StepRail`)
lists the visible steps' titles. Navigation as today: Continue, Back, and
the account and done bookends after the last content step.

### Step renderer

`frontend/src/pages/setup/WizardStep.tsx` renders one step: title, intro,
then its keys through `SettingField` with dependent-field hiding, one Test
button per service after the last of its fields, and pickers, all via the
existing `pages/admin/settings/` components. `SectionView`'s field loop is
extracted into a shared `FieldList` component (in `pages/admin/settings/`)
that both `SectionView` and `WizardStep` use, so the Test-button placement
and dependency logic exist once. `advanced` is always true for the wizard
(the step declares exactly what it shows).

### Required gate

`WizardStep` reports whether any required field is blank and unset; the
shell disables Continue accordingly, with the field's help shown under the
button.

### Save

Finishing posts only changed keys (`asString(values[k]) !==
asString(initial[k])`) as unprefixed form fields to `/setup/save`, untouched
secrets omitted, booleans `true`/`false`, lists comma-joined. Then the
account creation when `needs_first_admin`, then the dashboard redirect, as
today. Test buttons post through `/ui/api/settings/test/<service>` with
`serviceValues()`.

### Removed

`pages/setup/types.ts`, `fields.tsx`, `TestButton.tsx`, and the ten
`Step*.tsx` content files. `StepAccount.tsx`, `StepDone.tsx`, `StepRail.tsx`
stay (the rail reads titles from props).

## 3. Testing

Backend (pytest, existing conventions): `WIZARD_STEPS` guards; `RULE_FIELDS`
resolvers omit `unknown`; `required` only on `TORBOX_API_KEY`; the schema
route and the widened picker/test gates on source text; `/setup/save`
accepts `RESOLUTION_PREFERRED=1080p,2160p` and rejects an unknown key (the
route body on source text plus a `settings.set` round-trip); the translator
and its test are gone (a source-text assertion that `app.py` no longer
mentions `translate_wizard_keys`).

Frontend (vitest): the wizard renders steps from a fixture in order; Lite
hides non-lite steps and the rail shrinks; Continue is disabled on a blank
required field and enabled once typed or already set; a dependent field
appears when its toggle flips; a Test button posts the typed values for that
service; finishing posts only changed keys, unprefixed; the account bookend
still blocks completion on a mismatch; `FieldList` extraction leaves
`SectionView.test.tsx` green.

## 4. Delivery

One plan, four tasks: (1) backend steps, rule fields, `required`, schema
route, gate widening, translator removal, tests; (2) `FieldList` extraction
from `SectionView`; (3) wizard shell and `WizardStep`, removals, tests,
build; (4) docs (manual's wizard section, README, CHANGELOG). Subagent-driven
with an opus whole-branch review. Release as 0.18.0 on request.

## Risks

The wizard is the first thing a new user sees, and the rewrite replaces
every content step; the frontend test file is rewritten with it. Rollback is
a redeploy of 0.17.0. The rule keys are validated by `settings.set()`, so a
bad value fails loudly at save, as it does from the Filter rules tab.
