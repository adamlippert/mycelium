# UI Overhaul, Plan 4: Pre-Auth Cutover Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the last three server-rendered surfaces (Login, Setup wizard, Manual) into the React app behind the `UI_V2` env flag, with permanent `/classic` escape hatches, closing out the UI overhaul.

**Architecture:** The flag is an environment variable read at startup, never a runtime setting: a runtime toggle is unreachable if login is what broke. Flask keeps every Jinja route alive at `/login/classic`, `/setup/classic`, `/admin/classic` regardless of the flag; with `UI_V2=true` the bare paths serve the SPA instead. The React login submits a REAL form POST to the unchanged `/login` endpoint (full page navigation, so the server's redirect and session cookie work with zero new backend). The wizard port is completeness-gated against `templates/setup.html` the way Plan 3's admin was gated against its inventory. The Jinja templates are NOT deleted in this plan; that is a follow-up release after VPS confirmation.

**Tech Stack:** React 18, TypeScript, React Query, the Plan 1 primitives; Flask route plumbing in `app.py`, one flag in `config.py`.

**Spec:** `docs/superpowers/specs/2026-08-30-ui-overhaul-design.md` (sections: Safety net, Setup wizard, Manual, Login, plus the follow-ups list)

**Plan 4 of 4.** Requires Plans 1-3 (complete on `feat/ui-overhaul`).

**Carried from Plan 3:** the `/ui/set-password` orphan (diff against `/ui/api/me/password`, then port: it is the LEGACY global password setter, `auth.set_password`, no current-password check, admin-only; distinct semantics, so it ports as a small admin Settings card); the `GenreRuleRows` duplicate extraction onto the `Toggle` primitive.

## Global Constraints

- **Never use em-dashes**, anywhere. Use a comma, a colon, parentheses, or " - ".
- **Public repo.** No secrets, tokens, IPs.
- **Branch `feat/ui-overhaul`.** No `Co-Authored-By`; every commit body ends with exactly:
  `Claude-Session: https://claude.ai/code/session_01S7W5TTdnwd8hdgj3L3dnnx`
- **`static/app/` rebuilds at the final task only.**
- **The auth path is the risk.** No change to `POST /login`, `POST /setup/save`, `POST /setup/skip`, `POST /setup/test/<kind>`, the OIDC routes, or `auth.py`'s gate EXCEPT the additions this plan names (new public classic paths). Any other diff hunk in those areas is a defect.
- **`UI_V2` defaults false.** With the flag off, every existing behaviour is byte-identical: the Jinja login, wizard and dashboard serve exactly as today.
- **Tests:** Python via `./.venv-sdd/bin/python -m pytest tests/ -q` (baseline 473; nothing imports app; routes asserted against source). Frontend `cd frontend && npm test` (baseline 116). JS `node --test tests/js/filter_rules.test.js` (34, files untouched).
- `npx tsc --noEmit`: 4 pre-existing errors (usePluginSlots.ts x3, Watchlist.tsx x1); Login.tsx's rewrite must not add errors (its pre-existing one, if the file carries one, should clear).
- **Refresh policy** as in prior plans.

## Verified backend facts (implementers rely on these; re-verify before deviating)

- `POST /login` (app.py:176): form fields `username`, `password`, `next`; success sets `session["user"]` and redirects to `next`; failure redirects to `/login?error=1&next=...`. Rate limited 5/min.
- `login.html` renders an error banner when `?error=1`, a `next` hidden field, and an OIDC link when `oidc.is_enabled()` (provider name via `oidc.provider_name()`); password form hidden when password auth is off.
- `GET /setup` (app.py:672): first run (`db.user_count() == 0`) always allowed; after that admin-only; redirects to `/admin` when `SETUP_COMPLETE` unless `?rerun=1`.
- `/setup/test/<kind>` kinds: torbox, jellyfin, zilean, radarr, sonarr, seerr, trakt, discord, telegram, opensubtitles. FormData POST, `{ok, detail|error}` JSON.
- `/setup/save`: FormData POST of `setting_`-style keys (read setup.html's JS `saveAll` to mirror exactly); `/setup/skip` marks complete.
- `templates/setup.html`: ten `data-step` panes, sections Welcome / TorBox / Jellyfin / Catbox lazy mode / Quality and language / Zilean / Radarr and Sonarr / Seerr / Trakt / Notifications / OpenSubtitles / All set.
- `/ui/set-password` (app.py:198): admin-only, form field `password` (min 6), calls `auth.set_password` (the legacy global password), flash + redirect response.
- `config.py` bool pattern: `X = _env("X", "false").lower() in ("1", "true", "yes")`.
- `auth._PUBLIC_PATHS` (auth.py:37) gates unauthenticated access; `/login` is present; classic variants must be added.
- `docs/install-guide.html` is the only doc file; the Manual ToC derives from its own headings (ruling: the mockup's 12 hardcoded entries were illustrative; deriving from the real document honors "content from existing files, not a second copy").

## File Structure

| File | Responsibility |
|---|---|
| `config.py` | modify: `UI_V2` flag |
| `app.py` | modify: flag-switched `/login`, `/setup`, `/admin` GETs; new `/login/classic`, `/setup/classic`, `/admin/classic`; Manual route unchanged (SPA-internal) |
| `auth.py` | modify: `_PUBLIC_PATHS` gains `/login/classic` |
| `tests/test_ui_v2_cutover.py` | create |
| `frontend/src/pages/Login.tsx` | rewrite: mockup styling, real form POST, OIDC, error banner |
| `frontend/src/pages/Setup.tsx` | create: ten-step wizard |
| `frontend/src/pages/Manual.tsx` | create: docs page, ToC from headings, scroll-spy |
| `frontend/src/App.tsx` | modify: `/setup` route added; `/manual` iframe replaced by `Manual` |
| `frontend/src/pages/admin/Settings.tsx` | modify: legacy set-password card |
| `frontend/src/pages/admin/{Requests,Settings}.tsx` + `frontend/src/components/primitives/GenreRuleRows.tsx` | extraction |

---

### Task 1: The UI_V2 flag and route plumbing

**Files:**
- Modify: `config.py`, `app.py`, `auth.py`
- Test: `tests/test_ui_v2_cutover.py`

**Interfaces:**
- Produces: `cfg.UI_V2: bool`; routes `/login/classic` (GET, public), `/setup/classic` (GET, same gates as `/setup`), `/admin/classic` (GET, same gates as today's `/admin`); flag-switched bare routes.

- [ ] **Step 1: Write the failing test**

`tests/test_ui_v2_cutover.py`:

```python
"""UI_V2 cuts the pre-auth surfaces over to the SPA, with permanent escape
hatches. The flag is an env var read at startup: a runtime toggle stored in
the database is unreachable if login is what broke. With the flag off,
today's behaviour must be byte-identical.
"""
import importlib
import os
import re
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _src(name):
    with open(os.path.join(_ROOT, name), encoding="utf-8") as f:
        return f.read()


def test_the_flag_defaults_off_and_parses_truthy_values(monkeypatch):
    import config
    monkeypatch.delenv("UI_V2", raising=False)
    importlib.reload(config)
    assert config.UI_V2 is False
    monkeypatch.setenv("UI_V2", "true")
    importlib.reload(config)
    assert config.UI_V2 is True
    monkeypatch.delenv("UI_V2", raising=False)
    importlib.reload(config)


def test_classic_routes_exist_and_serve_the_jinja_views():
    src = _src("app.py")
    assert '@app.get("/login/classic")' in src
    assert '@app.get("/setup/classic")' in src
    assert '@app.get("/admin/classic")' in src
    # each classic body renders the template the bare route used to
    for tpl in ("login.html", "setup.html", "ui.html"):
        assert src.count(f'render_template("{tpl}"') >= 1


def test_the_bare_routes_switch_on_the_flag():
    src = _src("app.py")
    for fn in ("login_view", "setup_wizard", "ui_dashboard"):
        m = re.search(rf"def {fn}\(.*?\n(?=@app\.|\ndef )", src, re.S)
        assert m, fn
        assert "UI_V2" in m.group(0), f"{fn} does not consult the flag"
        assert "_spa_index()" in m.group(0), f"{fn} cannot serve the SPA"


def test_login_classic_is_public():
    assert '"/login/classic"' in _src("auth.py")


def test_the_auth_gate_redirect_targets_are_flag_agnostic():
    """The gate redirects to /login; with UI_V2 on that serves the SPA login,
    off it serves Jinja. The gate itself must not hardcode a classic path."""
    src = _src("auth.py")
    assert "/login/classic?" not in src.replace('"/login/classic"', "")
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv-sdd/bin/python -m pytest tests/test_ui_v2_cutover.py -q`
Expected: FAIL (no flag, no routes).

- [ ] **Step 3: Implement**

`config.py`, beside the other feature flags:

```python
# Serve the React SPA at /login, /setup and /admin instead of the Jinja
# pages. Env var, not a runtime setting: a runtime toggle is unreachable if
# login is what broke. The Jinja pages stay reachable at /login/classic,
# /setup/classic and /admin/classic regardless.
UI_V2 = _env("UI_V2", "false").lower() in ("1", "true", "yes")
```

`app.py`: restructure the three GET views so the existing Jinja-rendering body moves into a shared helper the classic route also calls, and the bare route consults the flag:

```python
def _login_page():
    return render_template("login.html",
                            error=request.args.get("error"),
                            next=request.args.get("next", ""),
                            oidc_enabled=oidc.is_enabled(),
                            oidc_provider=oidc.provider_name(),
                            password_enabled=bool(cfg.AUTH_ENABLED or
                                                   __import__("settings").get("AUTH_PASSWORD_HASH", "")))


@app.get("/login")
def login_view():
    if cfg.UI_V2:
        return _spa_index()
    return _login_page()


@app.get("/login/classic")
def login_classic():
    return _login_page()
```

Same shape for `/setup` (the gates - `user_count`, `is_admin`, `SETUP_COMPLETE`/`rerun` - run BEFORE the flag branch, identically for bare and classic, so the classic route is not an auth bypass) and `/admin` (the admin gate and `SETUP_COMPLETE` redirect stay; only the final render switches). `_spa_index` is defined near the file bottom; reference it via a small module-level indirection or move the three views below it (state which in the report).

`auth.py`: add `"/login/classic"` to `_PUBLIC_PATHS`.

- [ ] **Step 4: Run the tests**

Run: `./.venv-sdd/bin/python -m pytest tests/test_ui_v2_cutover.py -q` then the full suite.
Expected: 5 new pass; 478 total.

- [ ] **Step 5: Commit**

```bash
git add config.py app.py auth.py tests/test_ui_v2_cutover.py
git commit -m "feat(cutover): UI_V2 flag with permanent classic escape hatches"
```

---

### Task 2: The React login

**Files:**
- Rewrite: `frontend/src/pages/Login.tsx`
- Test: `frontend/src/pages/Login.test.tsx`

**Interfaces:**
- Consumes: `GET /ui/api/session` (already typed) for the oidc/password flags IF exposed there; otherwise read `templates/login.html` and mirror its conditional rendering using a tiny new endpoint-free approach: the flags arrive via the login page's own needs (check `api.session`'s payload first with `grep -n "oidc" app.py frontend/src/api.ts`; if the session payload lacks them, add `oidc_enabled`/`oidc_provider`/`password_enabled` to the session endpoint's response in `app.py` and the `SessionInfo` type, asserting the addition in `tests/test_ui_v2_cutover.py`).
- Produces: the mockup login: centered card, `myc3l1um` wordmark, tagline "the hidden network beneath your media library", username + password fields, Sign in, `or` divider, "Continue with <provider>" linking `/login/oidc`, error banner on `?error=1`, version footer.

The submission is a REAL `<form method="post" action="/login">` with hidden `next` (from `?next=` query param, default `/`) so the server's redirect-on-success and rate limiting work unchanged; no fetch, no React Query mutation. Check `templates/login.html` for a CSRF hidden field: if the Jinja form carries one, mirror it using the SPA's csrf meta tag content; if `POST /login` is csrf-exempt, do not add one (state which in the report).

This rewrite also kills the last old-palette hexes in `frontend/src`: the logo SVG in Login.tsx dies with the rewrite (wordmark text instead, as the Sidebar does).

- [ ] **Step 1: failing test** (`Login.test.tsx`): renders username and password fields and a submit button; the form's method is post and action is /login; the hidden `next` field carries the `?next=` param (use MemoryRouter initialEntries `['/login?next=%2Fwatchlist&error=1']`); the error banner shows on `error=1`; the tagline renders. Mock `api.session` (or the flags source you land on) for the OIDC branch: provider present renders the Continue link href `/login/oidc`.
- [ ] **Step 2**: run to fail, implement per the mockup styling (tokens only; no stock colours), run `cd frontend && npm test` and `npx tsc --noEmit`, then `grep -rn "22d3ee\|0d9488\|5eead4\|6366f1" frontend/src` must return NOTHING (the plan-1 exclusion finally closes).
- [ ] **Step 3**: commit `feat(cutover): React login page`.

---

### Task 3: The setup wizard port

**Files:**
- Create: `frontend/src/pages/Setup.tsx` (plus `frontend/src/pages/setup/` step components if the file would exceed ~400 lines; state the split in the report)
- Modify: `frontend/src/App.tsx` (add a `/setup` route OUTSIDE the Layout shell: the wizard is pre-auth chrome-less)
- Test: `frontend/src/pages/Setup.test.tsx`

**Interfaces:**
- Consumes: `POST /setup/save` (FormData), `POST /setup/skip`, `POST /setup/test/<kind>` for kinds torbox, jellyfin, zilean, radarr, sonarr, seerr, trakt, discord, telegram, opensubtitles; all unchanged.
- Produces: the full ten-step wizard, styled per the mockup's step-indicator treatment (numbered steps rail, Back / Continue, Autosaved note, Test buttons with ok/fail readouts).

**The completeness gate (binding, mirrors Plan 3's inventory pattern):** before writing code, extract from `templates/setup.html` the complete list of steps, every input's `name`, every Test button and its kind, and the exact FormData keys `saveAll` posts; write that list into your report FIRST, port against it, and hand the reviewer the list to diff against the template. A field in setup.html with no React counterpart is a blocking defect. The mockup's four steps were illustrative; the spec (corrected) mandates all ten.

Mechanics: one React state object holding all field values, initialised from the template's defaults (mirror them exactly); each Test button posts the RELEVANT fields as FormData to its kind endpoint and renders `{ok, detail|error}`; Continue advances locally; the final step's finish posts everything to `/setup/save` then `/setup/skip`-equivalent completion exactly as the Jinja JS sequence does (read `saveAll` and the finish handler; mirror the call order); a Skip control mirrors `/setup/skip`. No React Query needed; plain fetch with FormData (no JSON headers).

- [ ] **Step 1**: extract the field inventory into the report.
- [ ] **Step 2: failing test** (`Setup.test.tsx`): renders the Welcome step; Continue advances to a step whose heading matches setup.html's second section; a Test button posts FormData to /setup/test/torbox (fetch spy) and renders the mocked ok detail; the step rail shows ten steps.
- [ ] **Step 3**: implement, run `cd frontend && npm test`, tsc gate.
- [ ] **Step 4**: commit `feat(cutover): React setup wizard, all ten steps`.

---

### Task 4: The Manual page

**Files:**
- Create: `frontend/src/pages/Manual.tsx`
- Modify: `frontend/src/App.tsx` (the `/manual` route's iframe element becomes `<Manual />`)
- Test: `frontend/src/pages/Manual.test.tsx`

**Interfaces:**
- Consumes: `GET /docs/install-guide.html` (served by the existing `docs_file` route).
- Produces: a docs page: left ToC derived from the document's own `h1/h2` headings, scroll-spy highlighting, the content restyled by token classes, a "README on GitHub" link to `https://github.com/adamlippert/mycelium#readme`.

Mechanics: fetch the HTML, parse with `DOMParser`, extract the `<body>` content (strip any `<script>` and `<style>` the standalone page carries; apply the app's typography by rendering into a classed container), build the ToC from the headings with generated ids, `IntersectionObserver` for scroll-spy. The document is same-origin and self-authored, but strip scripts anyway and inject via a sanitizing path (element cloning, not raw innerHTML of script-bearing content); note the approach in the report.

- [ ] **Step 1: failing test**: mock fetch returning a small HTML doc with two h2s; assert both appear in the ToC and the content renders; assert no `<script>` from the source survives in the container.
- [ ] **Step 2**: implement, suites + tsc gates.
- [ ] **Step 3**: commit `feat(cutover): native Manual page with derived ToC`.

---

### Task 5: Carried cleanups

**Files:**
- Create: `frontend/src/components/primitives/GenreRuleRows.tsx` (extraction onto the `Toggle` primitive)
- Modify: `frontend/src/pages/admin/Requests.tsx`, `frontend/src/pages/admin/Settings.tsx` (consume the shared component; delete the local copies; Settings also gains the legacy password card)
- Modify: `frontend/src/components/primitives/index.ts`
- Test: `frontend/src/components/primitives/GenreRuleRows.test.tsx`

Two items:
1. **GenreRuleRows extraction**: the two local copies (admin Requests.tsx ~line 279, admin Settings.tsx ~line 190) differ only in whitespace; extract one shared component, replacing the hand-rolled toggle button with the `Toggle` primitive, preserving the exact rule-row semantics and mutation payloads. Both consumers' existing tests must keep passing unchanged.
2. **Legacy password card**: a small card in the admin Settings tab ("Legacy password" with a hint that it sets the single shared fallback password, distinct from per-user passwords), one password input (min 6 enforced client-side to match the server), posting form field `password` to `/ui/set-password` via the `formPost` mechanism. Tick the orphan inventory line 175 with a note recording the diffed semantics (`auth.set_password`, no current-password check, admin-only, vs `/ui/api/me/password` per-user with current check).

- [ ] **Step 1: failing tests**: GenreRuleRows renders rules from props and fires its change callback (port the assertions from whichever consumer test covered it, if any; otherwise minimal render+interact); Settings shows the Legacy password card and posts field `password` (fetch spy).
- [ ] **Step 2**: implement, full frontend suite + tsc.
- [ ] **Step 3**: commit `refactor(admin): shared GenreRuleRows, legacy password card`.

---

### Task 6: Gate

- [ ] **Step 1: Full sweep**

```bash
./.venv-sdd/bin/python -m pytest tests/ -q            # expect 478
node --test tests/js/filter_rules.test.js              # 34; git diff --quiet static/admin/ tests/js/
cd frontend && npm test && npx tsc --noEmit            # all green; at most the 4 pre-existing errors, minus any this plan cleared
grep -rn "22d3ee\|0d9488\|5eead4\|6366f1" frontend/src # NOTHING remains
grep -rnE "text-red-|bg-red-|text-green-|zinc-|indigo-" frontend/src/pages --include='*.tsx' | grep -v Admin.tsx  # nothing (Admin.tsx is deleted; nothing excluded any more)
```

- [ ] **Step 2: Flag-off equivalence spot-check**

With no `UI_V2` in the environment, assert via the Task 1 tests that the bare routes fall through to the Jinja renders (already covered; re-run the file).

- [ ] **Step 3: Build, commit**

```bash
cd frontend && npm run build
cd .. && git add -A && git commit -m "feat(cutover): plan 4 gate, rebuild static/app"
```

- [ ] **Step 4: Report** the VPS verification checklist verbatim for the user (this cannot be tested locally):

1. Deploy with `UI_V2` unset: everything behaves exactly as before (Jinja login/setup/admin).
2. Set `UI_V2=true` in Coolify's env, redeploy: `/login` serves the React login; sign in works; `/admin` serves the native admin on refresh; `/setup?rerun=1` shows the React wizard.
3. `/login/classic`, `/setup/classic`, `/admin/classic` serve the Jinja versions throughout.
4. Rollback: unset `UI_V2`, redeploy.
5. Only after all four pass: the Jinja template deletion becomes a candidate for a LATER release.

## Done when

- All suites green (478 / 34 / frontend all passing); old-palette grep returns nothing anywhere in `frontend/src`.
- `UI_V2` off: byte-identical behaviour. On: SPA at the three bare paths, classics reachable.
- `static/app/` rebuilt and committed.
- The orphan `/ui/set-password` line is ticked with its diffed semantics recorded.
