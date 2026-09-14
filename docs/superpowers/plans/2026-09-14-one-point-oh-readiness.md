# 1.0 Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Release 1.0.0 with a written compatibility promise, `app.py` and `catbox.py` split along their responsibilities, docs that match the code, an upgrade and rollback procedure, and a catbox comparison report.

**Architecture:** Routes move verbatim from `app.py` into Flask blueprints under `routes/`, one module per group of `app.py` sections; `catbox.py` keeps the play path and hands jobs and pack handling to `catbox_jobs.py` and `catbox_packs.py` with thin re-exports. A generated route table proves no route changed. Guard tests then tie `docs/COMPATIBILITY.md` to the schema tiers and the registered routes, and every documented name to the code.

**Tech Stack:** Python 3.12, Flask blueprints, SQLite; React frontend untouched except the manual's HTML; pytest, vitest.

**Spec:** `docs/superpowers/specs/2026-09-14-one-point-oh-readiness-design.md`

## Global Constraints

- Never write two hyphens in a row anywhere (code, comments, docs, commit messages); markdown table separators and horizontal rules excepted.
- The repo is public: no keys, tokens or addresses.
- Work on branch `main`. No `Co-Authored-By`. Commit trailer on every commit: `Claude-Session: https://claude.ai/code/session_01E4NjBiGw4m7EjGexJTbQu5`.
- Tests never import `app.py` or the route modules (they start the scheduler); routes are asserted on source text. Every DB test file has its own `_isolated_db` fixture; no conftest; no network; pristine output.
- Python: `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/ -q -p no:cacheprovider` (1247 tests at the start). Frontend: `cd frontend && npx tsc --noEmit && npx vitest run`, `npm run build`, commit `static/app/` on any frontend change.
- Refactor tasks change no behaviour: no route path, method, auth check, response, log message or setting changes; no test weakened. The route table fixture (Task 2) and the re-export list (Task 3) are invariants.
- Mutation checks after every new test; restore by copying files back from the scratchpad, never `git checkout`.
- The frozen route list (spec, Decisions table) and the tier rule (supported = listed and not advanced; advanced = listed and flagged; internal = `_UNLISTED_KEYS`; deployment = read from the environment only) are copied verbatim into `docs/COMPATIBILITY.md`.

---

## File Structure

| File | Responsibility |
|---|---|
| `routes/__init__.py` | `register_all(app)`: imports and registers every blueprint in a fixed order |
| `routes/_common.py` | Helpers two or more route modules share (`_setup_gate`, `_lib_action`, JSON error helpers) |
| `routes/auth.py` | the Auth section: `/login`, `/logout`, `/ui/set-password`, `/ui/api/me/password`, plus the `after_request` and `context_processor` hooks |
| `routes/integration.py` | the Webhook section (`/webhook`, `/webhook/arr`, `/health`, `/healthz`, `/metrics`) and `/docs/<path:filename>` |
| `routes/setup.py` | the Setup wizard section |
| `routes/stream.py` | the Catbox lazy materialization section and the WebDAV section |
| `routes/admin_library.py` | the Upgrader / consolidation / trending triggers section, Dashboard, Auto-add now, Radarr / Sonarr import |
| `routes/admin_misc.py` | the New JSON APIs section and the User management (admin) section |
| `routes/spa.py` | Discover, Watchlist, User requests, the Modern SPA section |
| `app.py` | Flask app object, `db.init()`, config, `before_request` gate, scheduler, `_delayed` startup hooks, `routes.register_all(app)` |
| `scripts/route_table.py` | Parses route decorators from source into a sorted list of `(method, path)`; writes or checks `tests/fixtures/route_table.json` |
| `tests/_routes.py` | `src_for_route(path)`: the text of the module that defines a route |
| `tests/_torbox_import.py` | the real-client import helper the `sys.modules` dances become |
| `catbox.py` | play path, caches, locks, register, materialize; re-exports for jobs |
| `catbox_jobs.py` | `release_idle`, `reconcile_torbox_ids`, `last_reconcile`, `_account_lists`, `_last_reconcile`, `_reconcile_lock` |
| `catbox_packs.py` | `resolve_pack_files`, `_reconcile_pack`, `detach_episode`, `_search_detached`, `_start_detached_search`, `series_title`, `_EP_SUFFIX_RE` |
| `docs/COMPATIBILITY.md` | the promise (spec section 1) |
| `deprecations.py` | `DEPRECATED: dict[str, str]` old name to replacement; `warn_deprecated_env()` |
| `tests/test_compatibility.py`, `tests/test_docs_references.py`, `tests/test_schema_version.py` | guards |
| `docs/RECOVERY.md`, `README.md`, `docs/install-guide.html`, `docs/INTEGRATIONS.md`, `docs/SCALING.md`, `.env.example` | swept |
| `docs/superpowers/reports/2026-09-14-catbox-comparison.md` | the comparison report |

---

### Task 1: Whole-codebase review

**Files:**
- Create: `.superpowers/sdd/2026-09-14-one-point-oh-readiness/review-findings.md` (workspace, not committed)

**Interfaces:**
- Produces: a findings file with sections Blockers, Refactor now (safe), Refactor now (structural notes for Tasks 2 and 3), After 1.0, each item `file:line`, what, why, suggested change. Tasks 4 reads "Refactor now (safe)"; Tasks 2 and 3 read the structural notes.

- [ ] **Step 1: Dispatch the review** (most capable model, read-only) over the whole repository excluding `.venv*`, `node_modules`, `static/app`, `docs/superpowers`. Prompt: the goals of the pass, the file structure above, and these questions: dead code and unused imports; duplicated helpers across modules; functions over 120 lines; misleading names; comment and docstring drift (search for "Task " and "0.2" leftovers); modules whose responsibilities blur; test hygiene (the `sys.modules` dances, fixtures duplicated across files, tests asserting nothing); anything that would make the blueprint split or the catbox split risky (module-level state read by other modules, circular imports); security (secrets in logs, missing admin gates on `/ui/api/*` routes, unbounded inputs).
- [ ] **Step 2: Triage.** The controller marks each finding "this pass" or "after 1.0" in the file and lists the after-1.0 ones in the ledger. No commit.

---

### Task 2: `app.py` into blueprints

**Files:**
- Create: `routes/__init__.py`, `routes/_common.py`, `routes/auth.py`, `routes/integration.py`, `routes/setup.py`, `routes/stream.py`, `routes/admin_library.py`, `routes/admin_misc.py`, `routes/spa.py`, `scripts/route_table.py`, `tests/fixtures/route_table.json`, `tests/_routes.py`, `tests/test_route_table.py`
- Modify: `app.py`, every test that calls `_src("app.py")` for a route (60 call sites in 35 files)

**Interfaces:**
- Produces: `routes.register_all(app)`; each module exposes `bp = Blueprint("<name>", __name__)`; `tests._routes.src_for_route(path: str) -> str` (the full source text of the module whose decorator contains `path`; raises `KeyError` naming the path when none does); `scripts/route_table.py` with `parse(paths: list[str]) -> list[list[str]]` (sorted `[method, path]` pairs) and a CLI `--write` / `--check`.

- [ ] **Step 1: Freeze the route table before touching anything**

`scripts/route_table.py`:

```python
"""The registered routes as (method, path) pairs, parsed from source so the
tests can compare without importing app.py. `--write` refreshes the
fixture, `--check` fails when the code and the fixture differ."""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "route_table.json"
DECOR = re.compile(r'^@(?:app|bp)\.(get|post|put|delete|route)\(\s*"([^"]+)"(?:\s*,\s*methods=\[([^\]]*)\])?', re.M)


def parse(paths):
    pairs = set()
    for p in paths:
        src = Path(p).read_text(encoding="utf-8")
        for verb, path, methods in DECOR.findall(src):
            if verb == "route":
                for m in re.findall(r'"([A-Z]+)"', methods or '"GET"'):
                    pairs.add((m, path))
            else:
                pairs.add((verb.upper(), path))
    return sorted([list(x) for x in pairs])


def sources():
    out = [ROOT / "app.py"]
    out += sorted((ROOT / "routes").glob("*.py")) if (ROOT / "routes").is_dir() else []
    return [str(p) for p in out]


if __name__ == "__main__":
    table = parse(sources())
    if "--write" in sys.argv:
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(json.dumps(table, indent=1) + "\n")
        print(f"wrote {len(table)} routes")
    else:
        stored = json.loads(FIXTURE.read_text())
        if stored != table:
            missing = [r for r in stored if r not in table]
            extra = [r for r in table if r not in stored]
            print("route table changed:", "missing", missing, "extra", extra)
            sys.exit(1)
        print(f"{len(table)} routes match")
```

Run `.venv-sdd/bin/python scripts/route_table.py --write` on the unchanged `app.py`; the fixture holds 197 entries (route decorators with `methods=[...]` count once per method). Commit the script and the fixture first: `git commit -m "test: freeze the route table before the blueprint split"`.

`tests/test_route_table.py`:

```python
"""The blueprint split moves routes; it never changes them. The fixture was
generated from app.py before the split and is refreshed only by a commit
that deliberately adds or removes a route."""
import json
import os
import sys

_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import route_table  # noqa: E402


def test_registered_routes_equal_the_frozen_table():
    stored = json.load(open(os.path.join(_ROOT, "tests", "fixtures", "route_table.json")))
    assert route_table.parse(route_table.sources()) == stored
```

- [ ] **Step 2: The test helper**

`tests/_routes.py`:

```python
"""Where a route lives now. Tests assert routes on source text; after the
blueprint split that text is in routes/<module>.py, and a later move costs
nothing here."""
import glob
import os

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _candidates():
    return [os.path.join(_ROOT, "app.py")] + sorted(glob.glob(os.path.join(_ROOT, "routes", "*.py")))


def src_for_route(path: str) -> str:
    needle = f'"{path}"'
    for p in _candidates():
        text = open(p, encoding="utf-8").read()
        if needle in text and ("@bp." in text or "@app." in text):
            return text
    raise KeyError(f"no module defines a route for {path}")
```

- [ ] **Step 3: Move the sections**

For each target module: create it with the imports it needs, `bp = Blueprint("<name>", __name__)`, and the section's code moved verbatim from `app.py` with `@app.` replaced by `@bp.` on the decorators only. Section boundaries are the `# ──` comment lines in `app.py` (Auth 583, Webhook 612, Dashboard 759, Setup wizard 776, New JSON APIs 1081, Catbox 1379, Upgrader/triggers 2007, WebDAV 2509, Discover 2516, Watchlist 2863, User requests 2922, User management 2980, Auto-add now 3614, Radarr / Sonarr import 3624, Modern SPA 3726; the five routes before line 583 belong to Auth). Module-level helpers used by one section move with it; helpers used by two or more (`_setup_gate` at 792, `_lib_action` at 2176, any JSON error helper) go to `routes/_common.py`. Imports at the top of `app.py` that only the moved code used move along; `app.py` keeps what its remaining code needs. The `after_request` and `context_processor` hooks become `@bp.after_app_request` and `@bp.app_context_processor` in `routes/auth.py`. `url_for("ui_dashboard")` and any other `url_for` targets gain the blueprint prefix (`url_for("spa.ui_dashboard")`): grep `url_for(` and `redirect(url_for` across the repo (templates included) and fix every one.

`routes/__init__.py`:

```python
"""Every blueprint, registered in one fixed order. app.py calls
register_all(app) after its own hooks are in place."""
from flask import Flask


def register_all(app: Flask) -> None:
    from routes import auth, integration, setup, stream, admin_library, admin_misc, spa
    for mod in (auth, integration, setup, stream, admin_library, admin_misc, spa):
        app.register_blueprint(mod.bp)
```

`spa` is last because it owns the catch-all `/<path:subpath>`.

In `app.py`, after the `before_request` gate and the scheduler setup: `import routes; routes.register_all(app)`. `app.py` keeps `app = Flask(...)`, `db.init()`, config loading, the gate, `_delayed` and the startup block. Route modules that need `app`-level objects (the scheduler, `_delayed`) import them from `app` lazily inside the function (`from app import scheduler`), never at module level, to avoid an import cycle.

- [ ] **Step 4: Update the tests**

Every `_src("app.py")` that asserts a route body becomes `src_for_route("<path>")` from `tests._routes` (add `sys.path` insertion of the tests directory or use a relative import as the file already does for `_src`). Tests that read `app.py` for the scheduler, startup hooks or `_delayed` keep `_src("app.py")`. Run the full suite; every failure is either a helper the test expected in `app.py` (fix the test to the new module) or a real regression (fix the code). Then `.venv-sdd/bin/python scripts/route_table.py --check` must print the match line.

- [ ] **Step 5: Verify, mutation-check, commit**

Full suite green. Mutation checks: comment out one blueprint registration (the route-table test fails); rename one path in a route module (fails). Smoke: `.venv-sdd/bin/python -c "import app"` is NOT run (starts the scheduler); instead `.venv-sdd/bin/python -c "import ast,glob; [ast.parse(open(p).read()) for p in ['app.py']+glob.glob('routes/*.py')]"`. Commit: `refactor(routes): split app.py into blueprints, routes unchanged`.

---

### Task 3: `catbox.py` into three modules

**Files:**
- Create: `catbox_jobs.py`, `catbox_packs.py`
- Modify: `catbox.py`, `app.py` (scheduler job targets), `overview.py` (`last_reconcile`), `release_swap.py` (`_pack_lock` import unchanged, `episode_matches` unchanged), tests: `tests/test_pack_files.py`, `tests/test_torbox_reconcile.py`, `tests/test_release_idle_accounts.py`, `tests/test_catbox_homing.py`, any test referencing the moved names

**Interfaces:**
- Produces: `catbox_packs.resolve_pack_files(token, item, live)`, `catbox_packs.detach_episode(vi)`, `catbox_packs.series_title(name)`, `catbox_packs._start_detached_search(episodes)` (the test seam), `catbox_packs._search_detached`; `catbox_jobs.release_idle()`, `catbox_jobs.reconcile_torbox_ids()`, `catbox_jobs.last_reconcile()`, `catbox_jobs._last_reconcile`, `catbox_jobs._reconcile_lock`, `catbox_jobs._account_lists`. `catbox.py` keeps `_token_lock`, `_pack_lock`, `_pack_locks`, the caches, `_sweep_caches`, `_content_key`, `invalidate_url_cache`, and re-exports `release_idle`, `reconcile_torbox_ids`, `last_reconcile` as thin wrappers with a lazy import.

- [ ] **Step 1: Write the failing test**

`tests/test_catbox_layout.py`:

```python
"""catbox.py holds the play path; jobs and pack handling live in their own
modules. The re-exports exist for one release so the scheduler and the
overview keep their names; the docstring lists them."""
import os

import catbox
import catbox_jobs
import catbox_packs

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def test_modules_own_their_functions():
    assert {"release_idle", "reconcile_torbox_ids", "last_reconcile", "_account_lists"} <= set(dir(catbox_jobs))
    assert {"resolve_pack_files", "detach_episode", "series_title", "_search_detached", "_start_detached_search"} <= set(dir(catbox_packs))
    for name in ("_resolve_pack_files", "_reconcile_pack", "_detach_episode", "_account_lists"):
        assert name not in catbox.__dict__, f"{name} moved out of catbox.py"


def test_re_exports_delegate_and_are_listed():
    assert catbox.release_idle.__module__ == "catbox" and "catbox_jobs" in open(os.path.join(_ROOT, "catbox.py")).read().split("def release_idle")[1][:200]
    doc = catbox.__doc__ or ""
    for name in ("release_idle", "reconcile_torbox_ids", "last_reconcile"):
        assert name in doc, "re-export listed in the module docstring"


def test_no_import_cycle_at_module_level():
    src = open(os.path.join(_ROOT, "catbox.py")).read()
    top = src.split("\ndef ")[0]
    assert "import catbox_jobs" not in top and "import catbox_packs" not in top
```

- [ ] **Step 2: Run it** (fails: modules missing).

- [ ] **Step 3: Move**

`catbox_packs.py` receives, verbatim, `_resolve_pack_files` (renamed `resolve_pack_files`), `_pack_lock` stays in `catbox.py`, `_reconcile_pack`, `_detach_episode` (renamed `detach_episode`), `_EP_SUFFIX_RE`, `_series_title` (renamed `series_title`), `_start_detached_search`, `_search_detached`. It does `import catbox` at module level and uses `catbox._pack_lock`, `catbox.invalidate_url_cache`, `catbox._content_key`, `catbox.db`. `catbox._materialize_locked` calls `resolve_pack_files` through a lazy `from catbox_packs import resolve_pack_files` inside the function.

`catbox_jobs.py` receives `_last_reconcile`, `_reconcile_lock`, `last_reconcile`, `_account_lists`, `reconcile_torbox_ids`, `release_idle`; `import catbox` at module level for `_sweep_caches`, `_token_lock`, `invalidate_url_cache`, `_home`, `db`, `torbox`, `torbox_pool`.

In `catbox.py`, at the bottom:

```python
def release_idle() -> int:
    """Re-export, removed in 1.1: use catbox_jobs.release_idle."""
    import catbox_jobs
    return catbox_jobs.release_idle()


def reconcile_torbox_ids() -> dict:
    """Re-export, removed in 1.1: use catbox_jobs.reconcile_torbox_ids."""
    import catbox_jobs
    return catbox_jobs.reconcile_torbox_ids()


def last_reconcile() -> dict | None:
    """Re-export, removed in 1.1: use catbox_jobs.last_reconcile."""
    import catbox_jobs
    return catbox_jobs.last_reconcile()
```

and the module docstring gains a "Re-exports (until 1.1): release_idle, reconcile_torbox_ids, last_reconcile" line. `app.py`'s scheduler targets and `overview._consistency` switch to `catbox_jobs.` directly.

- [ ] **Step 4: Update the tests**

`tests/test_pack_files.py`: `catbox._resolve_pack_files` becomes `catbox_packs.resolve_pack_files`, `catbox._detach_episode` becomes `catbox_packs.detach_episode`, `catbox._series_title` becomes `catbox_packs.series_title`, the fixture's `monkeypatch.setattr(catbox, "_start_detached_search", ...)` becomes `catbox_packs`; the source-text assertions on `_resolve_pack_files`/`_pack_lock` read `catbox_packs.py`. `tests/test_torbox_reconcile.py` and `tests/test_release_idle_accounts.py`: `catbox._last_reconcile`/`_reconcile_lock` become `catbox_jobs.`, calls become `catbox_jobs.reconcile_torbox_ids()` and `catbox_jobs.release_idle()`, fakes on `catbox.torbox` stay (jobs read `catbox.torbox`? No: jobs import `torbox` themselves, so fakes target `catbox_jobs.torbox`). `tests/test_torbox_client_accounts.py::test_materialize_locked_catches_auth_failed_from_the_homed_lookups` still reads `catbox.py`. Anything else the suite reports.

- [ ] **Step 5: Verify, mutation-check, commit**

Full suite green. Mutation: make `catbox.release_idle` return 0 without delegating (the layout test's docstring or delegation assertion fails); remove the lazy import in `_materialize_locked` (pack tests fail). Commit: `refactor(catbox): jobs and pack handling in their own modules, re-exports until 1.1`.

---

### Task 4: Safe cleanups from the review

**Files:**
- Modify: whatever Task 1's "Refactor now (safe)" list names; `config.py` (drop `EXCLUDE_DV_P5`, line 107); `tests/_torbox_import.py` (new) replacing the `sys.modules` dance in `tests/test_torbox_ratelimit.py`, `tests/test_torbox_client_accounts.py`, `tests/test_catbox_homing.py`, `tests/test_release_idle_accounts.py`, `tests/test_pack_registration.py` and any other file with the dance

**Interfaces:**
- Produces: `tests._torbox_import.real_torbox()` returning the real module regardless of a MagicMock in `sys.modules`.

- [ ] **Step 1: The import helper and its test**

```python
"""Some test modules replace sys.modules["torbox"] with a MagicMock at
collection time. Tests that need the real client take it from here."""
import importlib
import sys


def real_torbox():
    prior = sys.modules.get("torbox")
    sys.modules.pop("torbox", None)
    try:
        mod = importlib.import_module("torbox")
    finally:
        if prior is not None:
            sys.modules["torbox"] = prior
        else:
            sys.modules.pop("torbox", None)
    return mod
```

`tests/test_torbox_import_helper.py`: with a `MagicMock` planted in `sys.modules["torbox"]`, `real_torbox()` returns a module whose `__file__` ends with `torbox.py`, and afterwards `sys.modules["torbox"]` is the mock again.

- [ ] **Step 2: Apply the list.** One commit per finding or per tightly related group, each naming the covering tests in the message body. Behaviour unchanged. `EXCLUDE_DV_P5`: remove the `config.py` line; `migrate_filters.RETIRED` keeps its entry (the warning for a stale `.env` stays), `migrate_filters.migrate` reads it through `_settings.get` which falls back to nothing, confirm with `tests/test_migrate_filters*.py`.
- [ ] **Step 3: Verify.** Full suite green after every commit; grep for "Task " and "replaces this" in comments returns nothing.

---

### Task 5: Compatibility document, deprecation map and guard tests

**Files:**
- Create: `docs/COMPATIBILITY.md`, `deprecations.py`, `tests/test_compatibility.py`
- Modify: `app.py` (call `deprecations.warn_deprecated_env()` at startup next to `migrate_filters.warn_stale_env()`), `settings.py` (`SCHEMA_VERSION` in `_UNLISTED_KEYS`, needed by Task 6 too)

**Interfaces:**
- Produces: `deprecations.DEPRECATED: dict[str, str]` (empty at 1.0 except the three catbox re-exports are not env vars, so the dict starts empty), `deprecations.warn_deprecated_env() -> list[str]`; the document's machine-readable blocks: a fenced block per tier headed `<!-- tier: supported -->` etc. with one `NAME` per line, and a fenced block `<!-- routes -->` with one `METHOD /path` per line, which the guard parses.

- [ ] **Step 1: The guard tests**

`tests/test_compatibility.py`:

```python
"""docs/COMPATIBILITY.md is the promise; these tests keep it equal to the
code. A variable in config.py that is in no tier, a route missing from the
frozen list, or a deprecated name without a replacement fails here."""
import os
import re
import sys

import settings

_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import route_table  # noqa: E402

DOC = open(os.path.join(_ROOT, "docs", "COMPATIBILITY.md"), encoding="utf-8").read()
FROZEN_PREFIXES = ("/webhook", "/stream/", "/spore-stream/", "/internal/", "/health", "/healthz", "/metrics", "/setup", "/docs/")


def _block(marker):
    m = re.search(rf"<!-- {marker} -->\s*```\n(.*?)```", DOC, re.S)
    assert m, f"missing block {marker}"
    return [l.strip() for l in m.group(1).splitlines() if l.strip()]


def _config_vars():
    src = open(os.path.join(_ROOT, "config.py")).read()
    return set(re.findall(r"^([A-Z][A-Z0-9_]+)\s*=\s*_env", src, re.M))


def test_variable_tiers_match_the_schema_and_config():
    listed = {f["key"]: f for s in settings.SECTIONS for f in s["fields"] if f["kind"] != "custom"}
    supported = {k for k, f in listed.items() if not f.get("advanced")}
    advanced = {k for k, f in listed.items() if f.get("advanced")}
    internal = set(settings._UNLISTED_KEYS)
    deployment = _config_vars() - set(listed) - internal
    assert set(_block("tier: supported")) == supported
    assert set(_block("tier: advanced")) == advanced
    assert set(_block("tier: internal")) == internal
    assert set(_block("tier: deployment")) == deployment
    assert not (supported & advanced) and not (set(listed) & internal)


def test_frozen_routes_match_the_registered_ones():
    registered = {f"{m} {p}" for m, p in route_table.parse(route_table.sources()) if p.startswith(FROZEN_PREFIXES)}
    assert set(_block("routes")) == registered


def test_every_deprecation_names_a_replacement_and_a_changelog_line():
    import deprecations
    changelog = open(os.path.join(_ROOT, "CHANGELOG.md")).read()
    for old, new in deprecations.DEPRECATED.items():
        assert new and new != old
        assert old in changelog, f"{old} deprecated without a changelog line"
```

- [ ] **Step 2: `deprecations.py`**

```python
"""Promised names on their way out. A name listed here still works for one
minor release and warns once at startup, naming its replacement; the next
minor release removes it. Empty at 1.0."""
import logging
import os

log = logging.getLogger(__name__)

DEPRECATED: dict[str, str] = {}


def warn_deprecated_env() -> list[str]:
    messages = []
    for old, new in DEPRECATED.items():
        if old in os.environ:
            messages.append(f"{old} is deprecated and will be removed in the next minor release; use {new}.")
    for m in messages:
        log.warning("%s", m)
    return messages
```

- [ ] **Step 3: Write `docs/COMPATIBILITY.md`** per spec section 1, generating the tier blocks with a one-off script over `settings.SECTIONS` and `config.py` (each table row: name, default from `config.py` where present, the schema's `help` text or a written one-liner for deployment variables), and the route block from `route_table.parse`. Prose for each frozen route: method, purpose, what it accepts, what it returns, one example.

- [ ] **Step 4: Run, mutation-check** (remove one variable from a tier block; drop one route line), **commit** `docs: the 1.0 compatibility promise with guard tests`.

---

### Task 6: Upgrade and rollback

**Files:**
- Modify: `db.py` (new `ensure_schema_version(app_version) -> str | None`), `app.py` (call before `db.init()`, startup log line), `settings.py` (`SCHEMA_VERSION` unlisted), `docs/RECOVERY.md`
- Test: `tests/test_schema_version.py`

**Interfaces:**
- Produces: `db.ensure_schema_version(app_version) -> str | None`: reads the `SCHEMA_VERSION` setting through a raw connection (works on any schema that has the `settings` table), returns the previous version (None on a fresh database); when the stored version exists and differs from `app_version`, calls `backup.run()` before returning. `db.record_schema_version(app_version)` writes it after `init()`. Startup log: `Mycelium <version>, database schema from <previous or "fresh">`.

- [ ] **Step 1: Failing tests**

`tests/test_schema_version.py` (own `_isolated_db` fixture that only patches `db.DB_PATH` and drops the cached connection; it must NOT call `db.init()` itself, the tests do):

```python
import os

import backup
import db

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def test_first_start_records_the_version_and_takes_no_backup(monkeypatch):
    calls = []
    monkeypatch.setattr(backup, "run", lambda: calls.append(1))
    assert db.ensure_schema_version("1.0.0") is None
    db.init()
    db.record_schema_version("1.0.0")
    assert db.get_setting("SCHEMA_VERSION") == "1.0.0" and calls == []


def test_a_version_change_backs_up_before_migrating(monkeypatch):
    calls = []
    monkeypatch.setattr(backup, "run", lambda: calls.append(1))
    db.init()
    db.record_schema_version("0.29.0")
    assert db.ensure_schema_version("1.0.0") == "0.29.0"
    assert calls == [1]
    assert db.ensure_schema_version("1.0.0") == "0.29.0" and calls == [1, 1], "still differs until recorded"
    db.record_schema_version("1.0.0")
    assert db.ensure_schema_version("1.0.0") == "1.0.0" and calls == [1, 1]


def test_a_failing_backup_does_not_block_startup(monkeypatch, caplog):
    def boom():
        raise OSError("disk full")
    monkeypatch.setattr(backup, "run", boom)
    db.init()
    db.record_schema_version("0.29.0")
    assert db.ensure_schema_version("1.0.0") == "0.29.0"
    assert "backup" in caplog.text.lower()


def test_startup_calls_ensure_before_init_and_logs_the_line():
    src = open(os.path.join(_ROOT, "app.py")).read()
    assert src.index("db.ensure_schema_version(APP_VERSION)") < src.index("db.init()")
    assert src.index("db.init()") < src.index("db.record_schema_version(APP_VERSION)")
    assert "Mycelium %s, database schema from %s" in src
```

- [ ] **Step 2: Implement**, with `backup.run()` failures logged and ignored (a failed backup must not block startup; the log says so).
- [ ] **Step 3: `docs/RECOVERY.md`**: sections "Upgrading", "Before you upgrade" (the automatic backup, how to take one by hand), "Rolling back one version" with a table of what each release since 0.17 added to the database (from `db._migrate`: read the migration blocks and list column and table per version using the changelog dates), "What cannot be rolled back" (none today). No double hyphens.
- [ ] **Step 4: Verify, mutation-check, commit** `feat(startup): backup on version change, schema version recorded, upgrade and rollback documented`.

---

### Task 7: Documentation sweep and docs guard

**Files:**
- Modify: `README.md`, `docs/install-guide.html`, `docs/INTEGRATIONS.md`, `docs/SCALING.md`, `.env.example`
- Create: `tests/test_docs_references.py`

**Interfaces:**
- Produces: the guard that every `UPPER_SNAKE` token that matches a variable name pattern and is wrapped in backticks in those files exists in `config.py` or the schema, and every backticked path starting with `/webhook`, `/stream`, `/spore-stream`, `/health`, `/metrics`, `/setup`, `/ui/api/` exists in the route table (with `<...>` segments compared by shape).

- [ ] **Step 1: The guard test**

`tests/test_docs_references.py`:

```python
"""Every variable and route the docs name must exist. A removal fails here
until the docs follow."""
import os
import re
import sys

import settings

_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import route_table  # noqa: E402

FILES = ["README.md", "docs/install-guide.html", "docs/INTEGRATIONS.md", "docs/SCALING.md", "docs/RECOVERY.md", "docs/COMPATIBILITY.md", ".env.example"]
# Backticked upper-case tokens that are not Mycelium variables.
NOT_VARIABLES = {
    "PUID", "PGID",            # container user ids, documented as Docker knobs
    "TZ",                      # container timezone
    "GET", "POST", "DELETE",   # HTTP methods in route prose
    "JSON", "URL", "API",      # plain words
}
ROUTE_PREFIXES = ("/webhook", "/stream", "/spore-stream", "/health", "/metrics", "/setup", "/ui/api/", "/internal/")


def _known_vars():
    src = open(os.path.join(_ROOT, "config.py")).read()
    known = set(re.findall(r"^([A-Z][A-Z0-9_]+)\s*=\s*_env", src, re.M))
    known |= {f["key"] for s in settings.SECTIONS for f in s["fields"] if f["kind"] != "custom"}
    known |= set(settings._UNLISTED_KEYS)
    return known


def _shape(path):
    return re.sub(r"<[^>]+>", "<x>", path.rstrip("/"))


def test_documented_variables_exist():
    known = _known_vars()
    unknown = {}
    for f in FILES:
        text = open(os.path.join(_ROOT, f), encoding="utf-8").read()
        tokens = set(re.findall(r"`([A-Z][A-Z0-9_]{2,})`", text))
        if f == ".env.example":
            tokens = set(re.findall(r"^([A-Z][A-Z0-9_]+)=", text, re.M))
        bad = tokens - known - NOT_VARIABLES
        if bad:
            unknown[f] = sorted(bad)
    assert unknown == {}


def test_documented_routes_exist():
    registered = {_shape(p) for _, p in route_table.parse(route_table.sources())}
    unknown = {}
    for f in FILES:
        text = open(os.path.join(_ROOT, f), encoding="utf-8").read()
        paths = {m for m in re.findall(r"`((?:/[\w<>:.-]+)+)`", text) if m.startswith(ROUTE_PREFIXES)}
        bad = {p for p in paths if _shape(p) not in registered}
        if bad:
            unknown[f] = sorted(bad)
    assert unknown == {}
```

The allow-list grows only with a comment per entry saying why the token is not a variable.
- [ ] **Step 2: Sweep each file** against 0.17 through 0.29 per spec section 3, using the changelog as the checklist: for each release entry, find the sentence in the docs that should change and change it. Removed: the classic UI, the twelve filter booleans, the continue-watching setting, any `X-Emby-Token` mention. Added or updated: the ten admin tabs, the Library and Requests tabs, release swap and season swap, the account pool, Jellyfin 12, pack registration, the id check, the Overview, the webhook secret rotation, Comet and MediaFusion, the egress estimate. README's configuration section becomes a pointer to `docs/COMPATIBILITY.md` plus the ten most common variables.
- [ ] **Step 3: `.env.example`** ordered by tier with a heading per tier; every variable exists.
- [ ] **Step 4: Verify** (Python guard, `npx vitest run` for the manual's test), **commit** `docs: sweep against 0.17 through 0.29, docs reference guard`.

---

### Task 8: Catbox comparison report

**Files:**
- Create: `docs/superpowers/reports/2026-09-14-catbox-comparison.md`

**Interfaces:**
- Produces: the report per spec section 5. Research only; may run alongside Tasks 5 to 7.

- [ ] **Step 1: Research.** Read `https://docs.elfhosted.com/app/catbox/`, `https://docs.elfhosted.com/guides/media/jellyfin-torbox-aars/`, `https://docs.elfhosted.com/guides/media/torbox/`, the Plex and Emby counterparts linked from them, and `https://store.elfhosted.com/product/catbox/`. List every stated behaviour with its source URL.
- [ ] **Step 2: Map** each to Mycelium by reading `catbox.py`, `catbox_packs.py`, `catbox_jobs.py`, `strm_generator.py`, `arr_stubs.py`, `arr_sync.py`, `docs/INTEGRATIONS.md`, the README's catbox section: same / different by design / missing, with the Mycelium file that implements or lacks it.
- [ ] **Step 3: Rate** each missing behaviour useful or not for a four-to-six-user Jellyfin install on TorBox, with a rough effort (hours, days) and the module it would touch. Note every place Mycelium's docs describe the catbox differently from the code.
- [ ] **Step 4: Commit** `docs: catbox comparison with ElfHosted's CatBox`.

---

## Whole-branch review and release

One opus review of `git diff -U10 <base>..HEAD -- . ':(exclude)static/app'` plus the ledger's deferred list; one fix wave; one scoped re-review. Then, on request: `APP_VERSION = "1.0.0"`, changelog `## [1.0.0]` (Added: the compatibility promise, the upgrade procedure, the comparison report; Changed: the module layout with "no route or variable changed"; Removed: `EXCLUDE_DV_P5`), `releases.json`, tag `v1.0.0`, watch Release and CI by id, local notes.
