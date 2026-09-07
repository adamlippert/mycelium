# Setup Wizard on the Settings Schema Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the wizard's twelve hand-written step files with steps declared next to the settings schema, rendered by the same field kit as the Settings page, pre-filled from current values, with Test and Load buttons that work before any admin exists.

**Architecture:** `settings.py` gains `WIZARD_STEPS` (title, intro, keys, lite flag per step), `RULE_FIELDS` (declarations for the four filter-rule keys the wizard edits) and a `required` flag on fields; `wizard_schema_for_ui()` serves them through `GET /setup/schema`. Because the auth gate lets only `/setup/*` through on a fresh install, the wizard's Test and Load buttons call `/setup/test/<kind>` (now also accepting JSON) and a new `/setup/picker/<name>`, both gated like `/setup/save`; the `/ui/api` routes are not widened. The frontend extracts `SectionView`'s field loop into a shared `FieldList` used by both the Settings page and a new `WizardStep`; `Setup.tsx` becomes a thin shell over the schema payload.

**Tech Stack:** Python 3.12 / Flask, pytest; React 18 + TypeScript + Vite + Tailwind, vitest + Testing Library. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-07-wizard-on-schema-design.md`

**Deviation from the spec, decided while planning:** the spec widened the admin gate on `/ui/api/settings/picker/<name>` and `/ui/api/settings/test/<service>`. `auth.py`'s bricked-install carve-out (lines 376 to 378) admits only `/setup`, `/setup/*` and `/ui/api/users/create`, so a fresh install with auth on could never reach the `/ui/api` routes. The wizard therefore uses `/setup/test/<kind>` and a new `/setup/picker/<name>`; the `/ui/api` routes stay admin-only.

## Global Constraints

- Never use em-dashes or `--` in code, comments, copy or docs.
- The repo is public: no passwords, tokens or IP addresses.
- Branch `main`. Commit trailer `Claude-Session: https://claude.ai/code/session_01EZbQf8PvzNCADFo6bW74ko`. No `Co-Authored-By`.
- Tests never import `app.py`; routes are checked on source text via `_src()`. Every DB-touching test file carries its own `_isolated_db` autouse fixture (copy from `tests/test_settings_schema.py` lines 26 to 45). No `tests/conftest.py`. No test reaches the network.
- Mutation-check each new load-bearing test. Run pytest as `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/ -q -p no:cacheprovider` (854 passed at HEAD 6e98716). Frontend: `cd frontend && npx tsc --noEmit && npx vitest run` (196 passed). The built `static/app/` is committed after any frontend change.
- `tests/test_tier1_residue.py` pins on source text that `setup_save` and `setup_skip` call `_needs_first_admin()` before `SETUP_COMPLETE` is set, and `tests/test_service_tests.py` pins that `setup_test` calls `service_tests.run(kind, ...)` with no raw `requests` import; both must keep passing.
- `SECTIONS`, `SETTING_GROUPS`, `all_for_ui()`, `schema_for_ui()` keep their shapes; `RULE_FIELDS` is not part of `SECTIONS`.
- Copy rules: labels at most 40 characters, help one sentence at most 220 characters ending in a full stop (guarded by `test_help_lines_are_short_sentences`).
- The wizard's field copy comes from the schema; step titles and intros from `WIZARD_STEPS` exactly as written in Task 1.

## File structure

| File | Responsibility |
|---|---|
| `settings.py` | `required` in `_f`; `RULE_FIELDS`; `rule:*` resolvers; `WIZARD_STEPS`; `_field_for_ui()`; `wizard_schema_for_ui()`; `fields_by_key()` includes rule fields |
| `app.py` | `_setup_gate()`; `GET /setup/schema`; `POST /setup/picker/<name>`; `setup_test` accepts JSON; `setup_save` allows `fields_by_key()` keys and loses the translator |
| `migrate_filters.py` | `WIZARD_KEYS` and `translate_wizard_keys` removed |
| `tests/test_setup_wizard.py` (new), `tests/test_settings_schema.py` | guards and routes |
| `frontend/src/api.ts` | `required` on `SettingsField`; `WizardStepDef`, `SetupSchema`; `setupSchema`, `setupTest`, `setupPicker` |
| `frontend/src/pages/admin/settings/FieldList.tsx` (new) | the field loop with dependent hiding, custom cards, Test placement; `endpoint` prop |
| `frontend/src/pages/admin/settings/{SectionView,SettingField,ServiceTest,Picker}.tsx` | use `FieldList`; `endpoint` threaded to `ServiceTest` and `Picker` |
| `frontend/src/pages/setup/WizardStep.tsx` (new), `StepRail.tsx` (rewritten), `frontend/src/pages/Setup.tsx` (rewritten) | the wizard |
| removed | `frontend/src/pages/setup/{types.ts,fields.tsx,TestButton.tsx,StepWelcome,StepTorbox,StepJellyfin,StepSeerr,StepPreferences,StepCatbox,StepNotifications,StepTrakt,StepOpenSubtitles,StepZilean,StepRadarrSonarr}.tsx`, `tests/test_setup_wizard_keys.py` |
| docs | `docs/install-guide.html`, `README.md`, `CHANGELOG.md` |

---

### Task 1: Backend: steps, rule fields, `required`, routes, translator removal

**Files:**
- Modify: `settings.py` (`_f` signature; after `_OPTION_RESOLVERS`; after `SECTIONS`; `fields_by_key()`; `schema_for_ui()`)
- Modify: `app.py` (setup routes block, lines 759 to 872)
- Modify: `migrate_filters.py` (delete from `WIZARD_KEYS = (` at line 164 through the end of `translate_wizard_keys`)
- Delete: `tests/test_setup_wizard_keys.py`
- Test: `tests/test_setup_wizard.py` (new); `tests/test_settings_schema.py` (FIELD_KEYS gains `required`)

**Interfaces:**
- Produces: `settings.WIZARD_STEPS: list[dict]` with `{"id","title","intro","keys","lite"}`; `settings.RULE_FIELDS: list[dict]`; field dicts gain `"required": bool`; `settings.fields_by_key()` returns section fields plus rule fields; `settings.wizard_schema_for_ui() -> {"steps": [...], "fields": [field+value+overridden+hot_reload+options]}`; routes `GET /setup/schema` returning `{steps, fields, needs_first_admin}`, `POST /setup/picker/<name>` (JSON `{values}`, returns `{ok, options}` or `{ok:false, error}`), `POST /setup/test/<kind>` accepting JSON `{values}` and then returning `{ok, message}` (form posts keep `{ok, detail}`/`{ok:false, error}`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_setup_wizard.py`:

```python
"""The setup wizard is declared next to the settings schema: WIZARD_STEPS
name the keys each step shows, RULE_FIELDS declare the four filter-rule
keys the quality step edits, and /setup/schema serves both pre-filled.
"""
import os
import re
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

sys.modules.pop("settings", None)

import pytest

import db
import settings

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _src(name):
    with open(os.path.join(_ROOT, name), encoding="utf-8") as f:
        return f.read()


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


def test_every_step_names_known_keys_once_with_title_and_intro():
    known = settings.fields_by_key()
    seen = []
    for s in settings.WIZARD_STEPS:
        assert set(s) == {"id", "title", "intro", "keys", "lite"}, s.get("id")
        assert s["title"].strip() and s["intro"].strip().endswith("."), s["id"]
        assert isinstance(s["lite"], bool), s["id"]
        for k in s["keys"]:
            assert k in known, f"{s['id']}: {k}"
            assert known[k]["kind"] != "custom", k
        seen.extend(s["keys"])
        for text in (s["title"], s["intro"]):
            assert chr(0x2014) not in text and " -" + "- " not in text, s["id"]
    assert len(seen) == len(set(seen)), "a key appears in two steps"
    assert [s["id"] for s in settings.WIZARD_STEPS][:2] == ["welcome", "torbox"]
    assert {s["id"] for s in settings.WIZARD_STEPS if not s["lite"]} == {"trakt", "subtitles", "zilean", "arrs"}


def test_rule_fields_are_declared_with_vocabularies_without_unknown():
    by_key = {f["key"]: f for f in settings.RULE_FIELDS}
    assert set(by_key) == {"RESOLUTION_PREFERRED", "RESOLUTION_EXCLUDED", "ENCODE_PREFERRED", "LANGUAGE_PREFERRED"}
    assert by_key["RESOLUTION_PREFERRED"]["kind"] == "ordered"
    assert all(by_key[k]["kind"] == "multiselect" for k in ("RESOLUTION_EXCLUDED", "ENCODE_PREFERRED", "LANGUAGE_PREFERRED"))
    res = [o["value"] for o in settings._resolve_options(by_key["RESOLUTION_PREFERRED"])]
    assert "2160p" in res and "1080p" in res and "unknown" not in res
    enc = [o["value"] for o in settings._resolve_options(by_key["ENCODE_PREFERRED"])]
    assert "hevc" in enc and "unknown" not in enc
    lang = [o["value"] for o in settings._resolve_options(by_key["LANGUAGE_PREFERRED"])]
    assert "en" in lang and "unknown" not in lang
    # Rule fields live outside the Settings sections but are known to the schema.
    assert "RESOLUTION_PREFERRED" in settings.fields_by_key()
    assert all(f["key"] not in {f2["key"] for s in settings.SECTIONS for f2 in s["fields"]} for f in settings.RULE_FIELDS)


def test_required_is_only_the_torbox_key():
    req = [k for k, f in settings.fields_by_key().items() if f["required"]]
    assert req == ["TORBOX_API_KEY"]


def test_wizard_schema_is_prefilled_from_current_values():
    settings.set("JELLYFIN_URL", "http://jf.test")
    settings.set("TORBOX_API_KEY", "abc")
    settings.set("RESOLUTION_PREFERRED", "1080p,2160p")
    out = settings.wizard_schema_for_ui()
    assert [s["id"] for s in out["steps"]] == [s["id"] for s in settings.WIZARD_STEPS]
    by_key = {f["key"]: f for f in out["fields"]}
    wanted = [k for s in settings.WIZARD_STEPS for k in s["keys"]]
    assert list(by_key) == wanted, "one field per step key, in step order"
    assert by_key["JELLYFIN_URL"]["value"] == "http://jf.test" and by_key["JELLYFIN_URL"]["overridden"] is True
    assert by_key["TORBOX_API_KEY"]["value"] is True, "secrets are set/not-set only"
    assert by_key["RESOLUTION_PREFERRED"]["value"] == ["1080p", "2160p"]
    assert by_key["RESOLUTION_PREFERRED"]["options"][0]["value"] == "2160p"
    assert by_key["ZILEAN_URL"]["depends_on"] == "ZILEAN_MODE=external"


def test_the_retired_translator_is_gone_and_save_accepts_rule_keys():
    import migrate_filters
    assert not hasattr(migrate_filters, "translate_wizard_keys")
    assert not hasattr(migrate_filters, "WIZARD_KEYS")
    assert hasattr(migrate_filters, "RETIRED"), "the .env warning keeps its map"
    src = _src("app.py")
    assert "translate_wizard_keys" not in src and "WIZARD_KEYS" not in src
    body = re.search(r"def setup_save\(\).*?\n(.*?)\n@app\.", src, re.S).group(1)
    assert "fields_by_key()" in body
    # The rule keys are accepted by the allow-list and validated by settings.set.
    assert "RESOLUTION_PREFERRED" in settings.fields_by_key()
    assert "QUALITY_PREFERENCE" not in settings.fields_by_key()
    with pytest.raises(ValueError):
        settings.set("RESOLUTION_PREFERRED", "1080p,8k")


def test_the_setup_routes_share_one_gate():
    src = _src("app.py")
    gate = re.search(r"def _setup_gate\(\).*?\n(.*?)\n\n\n", src, re.S)
    assert gate and 'SETUP_COMPLETE' in gate.group(1) and "auth.is_admin()" in gate.group(1)
    for route in ('@app.get("/setup/schema")', '@app.post("/setup/picker/<name>")', '@app.post("/setup/test/<kind>")'):
        assert route in src, route
        body = src.split(route, 1)[1].split("\n\n\n", 1)[0]
        assert "_setup_gate()" in body, route
    schema = src.split('@app.get("/setup/schema")', 1)[1].split("\n\n\n", 1)[0]
    assert "wizard_schema_for_ui()" in schema and "_needs_first_admin()" in schema
    picker = src.split('@app.post("/setup/picker/<name>")', 1)[1].split("\n\n\n", 1)[0]
    assert "service_tests.PICKERS" in picker and "service_tests.pick(name" in picker
    test = src.split('@app.post("/setup/test/<kind>")', 1)[1].split("\n\n\n", 1)[0]
    assert "get_json(silent=True)" in test and "service_tests.run(kind" in test
    assert 'jsonify(ok=True, detail=' in test, "the form shape the old wizard used stays"
```

In `tests/test_settings_schema.py`, change `FIELD_KEYS` to include `"required"`.

- [ ] **Step 2: Run to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/test_setup_wizard.py tests/test_settings_schema.py -q -p no:cacheprovider`
Expected: FAIL, `AttributeError: module 'settings' has no attribute 'WIZARD_STEPS'`, and `test_every_field_has_exactly_the_declared_keys` fails on the missing `required` key.

- [ ] **Step 3: `settings.py`**

`_f`: add `required=False` to the signature after `readonly=False` and `"required": required` to the returned dict. In `SECTIONS`, the `TORBOX_API_KEY` field gets `required=True`.

After `_OPTION_RESOLVERS` (append entries; `_rt.UNKNOWN` is the sentinel `release_tags.values_for` appends):

```python
_OPTION_RESOLVERS.update({
    "rule:resolution": lambda: [{"value": v, "label": v} for v in _rt.values_for("resolution") if v != _rt.UNKNOWN],
    "rule:encode": lambda: [{"value": v, "label": v} for v in _rt.values_for("encode") if v != _rt.UNKNOWN],
    "rule:language": lambda: [{"value": v, "label": v} for v in _rt.values_for("language") if v != _rt.UNKNOWN],
})
```

After `_UNLISTED_KEYS`, before `fields_by_key()`:

```python
# The four filter-rule keys the setup wizard edits. They live in the Filter
# rules tab, not in a Settings section, so they are declared here and only
# reachable through fields_by_key() and WIZARD_STEPS.
RULE_FIELDS = [
    _f("RESOLUTION_PREFERRED", "Preferred resolutions",
       "Most wanted first. A release in a higher-ranked resolution wins over a lower one.",
       "ordered", options="rule:resolution"),
    _f("RESOLUTION_EXCLUDED", "Resolutions to skip",
       "Add 2160p here to avoid 4K releases, for example on a player without HDR.",
       "multiselect", options="rule:resolution"),
    _f("ENCODE_PREFERRED", "Preferred encodes",
       "hevc is smaller for the same quality; avc plays on more devices.",
       "multiselect", options="rule:encode"),
    _f("LANGUAGE_PREFERRED", "Preferred audio languages",
       "Releases with these audio languages rank first.",
       "multiselect", options="rule:language"),
]

# The setup wizard: each step names the schema keys it shows, in order.
# lite=False steps are skipped when LITE_MODE is on.
WIZARD_STEPS = [
    {"id": "welcome", "title": "Welcome", "lite": True,
     "intro": "Pick how this Mycelium runs; everything here can be changed later in Settings.",
     "keys": ["LITE_MODE"]},
    {"id": "torbox", "title": "TorBox", "lite": True,
     "intro": "TorBox is where torrents are cached and streamed from, so its key is the one thing setup cannot skip.",
     "keys": ["TORBOX_API_KEY"]},
    {"id": "jellyfin", "title": "Jellyfin", "lite": True,
     "intro": "Where the library is played; leave it blank if Jellyfin is not running yet.",
     "keys": ["JELLYFIN_URL", "JELLYFIN_API_KEY", "JELLYFIN_MEDIA_PATH"]},
    {"id": "seerr", "title": "Seerr and metadata", "lite": True,
     "intro": "Requests arrive from Seerr; TMDB supplies posters, runtimes and Discover.",
     "keys": ["SEERR_URL", "SEERR_API_KEY", "TMDB_API_KEY"]},
    {"id": "quality", "title": "Quality preferences", "lite": True,
     "intro": "How releases are ranked; the Filter rules tab has the full model later.",
     "keys": ["RESOLUTION_PREFERRED", "RESOLUTION_EXCLUDED", "ENCODE_PREFERRED", "LANGUAGE_PREFERRED"]},
    {"id": "catbox", "title": "Catbox", "lite": True,
     "intro": "Fetch titles on demand instead of holding every torrent on TorBox; needs the public address players reach Mycelium on.",
     "keys": ["CATBOX_MODE", "CATBOX_HOST"]},
    {"id": "notifications", "title": "Notifications", "lite": True,
     "intro": "Where to hear about finished and failed requests; optional.",
     "keys": ["DISCORD_WEBHOOK_URL", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"]},
    {"id": "trakt", "title": "Trakt", "lite": False,
     "intro": "Lets users connect their Trakt watchlist; optional.",
     "keys": ["TRAKT_CLIENT_ID", "TRAKT_CLIENT_SECRET"]},
    {"id": "subtitles", "title": "Subtitles", "lite": False,
     "intro": "Subtitle download from OpenSubtitles; optional.",
     "keys": ["OPENSUBTITLES_API_KEY", "OPENSUBTITLES_LANGUAGES"]},
    {"id": "zilean", "title": "Zilean", "lite": False,
     "intro": "A DMM hash index searched next to Torrentio; optional.",
     "keys": ["ZILEAN_ENABLED", "ZILEAN_MODE", "ZILEAN_URL",
              "ZILEAN_PG_HOST", "ZILEAN_PG_PORT", "ZILEAN_PG_DB", "ZILEAN_PG_USER", "ZILEAN_PG_PASSWORD"]},
    {"id": "arrs", "title": "Radarr / Sonarr", "lite": False,
     "intro": "Mirror the library into the arrs so Seerr, Maintainerr and calendars see it; optional.",
     "keys": ["ARR_SYNC_ENABLED",
              "RADARR_URL", "RADARR_API_KEY", "RADARR_ROOT_FOLDER", "RADARR_QUALITY_PROFILE",
              "SONARR_URL", "SONARR_API_KEY", "SONARR_ROOT_FOLDER", "SONARR_QUALITY_PROFILE"]},
]


def fields_by_key() -> dict[str, dict]:
    out = {f["key"]: f for s in SECTIONS for f in s["fields"]}
    out.update({f["key"]: f for f in RULE_FIELDS})
    return out
```

Delete the old one-line `fields_by_key()`.

Replace `schema_for_ui()` with a shared per-field helper:

```python
def _field_for_ui(f: dict, overrides: dict) -> dict:
    """One field with its current value, whether a DB override exists,
    whether it hot-reloads, and options resolved. A secret's value is
    reported as True/False (set or not), never the secret itself."""
    item = dict(f)
    item["options"] = _resolve_options(f)
    if f["kind"] == "custom":
        item.update({"value": None, "overridden": False, "hot_reload": True})
        return item
    current = get(f["key"])
    item["value"] = bool(current) if f["kind"] == "secret" else current
    item["overridden"] = overrides.get(f["key"]) is not None
    item["hot_reload"] = f["key"] in HOT_RELOAD
    return item


def schema_for_ui() -> list[dict]:
    """SECTIONS with each field filled in by _field_for_ui."""
    overrides = db.get_all_settings()
    return [{"id": s["id"], "title": s["title"], "description": s["description"], "icon": s["icon"],
             "fields": [_field_for_ui(f, overrides) for f in s["fields"]]}
            for s in SECTIONS]


def wizard_schema_for_ui() -> dict:
    """WIZARD_STEPS plus one filled-in field per step key, in step order."""
    overrides = db.get_all_settings()
    by_key = fields_by_key()
    keys = [k for s in WIZARD_STEPS for k in s["keys"]]
    return {"steps": WIZARD_STEPS, "fields": [_field_for_ui(by_key[k], overrides) for k in keys]}
```

- [ ] **Step 4: `app.py` setup routes**

Directly above `def _needs_first_admin()` insert:

```python
def _setup_gate():
    """None when the caller may use the setup surface: setup not yet
    complete (first run), or an admin re-running it. Otherwise a 401."""
    import settings as _settings
    if _settings.get("SETUP_COMPLETE", False) and not auth.is_admin():
        return jsonify(error="unauthorized"), 401
    return None
```

Directly after `setup_skip` add:

```python
@app.get("/setup/schema")
@limiter.limit("30 per minute")
def setup_schema():
    """Steps and pre-filled fields for the wizard."""
    denied = _setup_gate()
    if denied:
        return denied
    import settings as _settings
    payload = _settings.wizard_schema_for_ui()
    payload["needs_first_admin"] = _needs_first_admin()
    return jsonify(**payload)


@app.post("/setup/picker/<name>")
@limiter.limit("30 per minute")
def setup_picker(name: str):
    """Options for a wizard field filled from a service (arr root folders,
    quality profiles). Body: {"values": {KEY: value}}. Same gate as save."""
    denied = _setup_gate()
    if denied:
        return denied
    import service_tests
    if name not in service_tests.PICKERS:
        return jsonify(ok=False, error="unknown picker"), 404
    p = request.get_json(silent=True) or {}
    return jsonify(**service_tests.pick(name, p.get("values") or {}))
```

`setup_save`: replace its first lines through the end of the `for key, value in request.form.items():` loop header region with:

```python
    denied = _setup_gate()
    if denied:
        return denied
    _allowed_keys = set(_settings.fields_by_key()) | {"SETUP_COMPLETE"}
    saved = 0
    for key, value in request.form.items():
        if key not in _allowed_keys:
            log.warning("setup_save: rejected unknown key %r", key)
            continue
```

Delete the `import migrate_filters` line, the whole comment block and `wizard_form` translation block, and the `if key in migrate_filters.WIZARD_KEYS: continue` lines. The rest of the loop (empty clears, bool coercion, `ValueError` warning) and the `_needs_first_admin()` tail stay unchanged.

`setup_skip`: replace its two-line auth check with `denied = _setup_gate()` / `if denied: return denied`.

`setup_test`: replace the auth check the same way, and replace the body after the `kind not in service_tests.TESTS` check with:

```python
    p = request.get_json(silent=True)
    if isinstance(p, dict):
        # The schema-driven wizard posts JSON like the Settings page and reads {ok, message}.
        return jsonify(**service_tests.run(kind, p.get("values") or {}))
    r = service_tests.run(kind, dict(request.form))
    if r["ok"]:
        return jsonify(ok=True, detail=r["message"])
    return jsonify(ok=False, error=r["message"])
```

- [ ] **Step 5: `migrate_filters.py`**

Delete `WIZARD_KEYS` and `translate_wizard_keys` (from line 164 to the end of that function). If `_truthy` at line 167 has no other caller (`grep -n "_truthy" migrate_filters.py`), delete it too. Keep `RETIRED`, `warn_stale_env` and the startup migration. Delete `tests/test_setup_wizard_keys.py`.

- [ ] **Step 6: Run the tests and the suite**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/test_setup_wizard.py tests/test_settings_schema.py tests/test_tier1_residue.py tests/test_service_tests.py tests/test_spa_shell.py tests/test_auth_bootstrap.py tests/test_filter_rules_ui.py -q -p no:cacheprovider`, then the full suite. Expected: green. If `tests/test_tier1_residue.py::test_the_wizard_is_told_whether_an_admin_is_needed` or the `_needs_first_admin` regex breaks because `_setup_gate` sits above it, the regex `def _needs_first_admin\(\).*?\n(.*?)\n\n@app\.` needs the next decorated route after `_needs_first_admin` to still be the first `@app.` occurrence; keep `_setup_gate` above `_needs_first_admin`, not below.

- [ ] **Step 7: Mutation checks**

Make `fields_by_key()` skip `RULE_FIELDS`: `test_rule_fields_are_declared...` and `test_wizard_schema_is_prefilled...` must fail. Restore. In `_field_for_ui`, report the secret's raw value: `test_wizard_schema_is_prefilled...` must fail. Restore. Delete `__pycache__`.

- [ ] **Step 8: Commit**

```bash
git add settings.py app.py migrate_filters.py tests/test_setup_wizard.py tests/test_settings_schema.py
git rm tests/test_setup_wizard_keys.py
git commit -m "feat(setup): wizard steps and rule fields declared next to the schema, served at /setup/schema

Claude-Session: https://claude.ai/code/session_01EZbQf8PvzNCADFo6bW74ko"
```

---

### Task 2: Frontend: `FieldList` extraction and the setup API

**Files:**
- Modify: `frontend/src/api.ts` (`SettingsField.required`; new types and functions)
- Create: `frontend/src/pages/admin/settings/FieldList.tsx`
- Modify: `frontend/src/pages/admin/settings/SectionView.tsx`, `SettingField.tsx`, `ServiceTest.tsx`, `Picker.tsx`
- Test: `frontend/src/pages/admin/settings/FieldList.test.tsx` (new); existing `SectionView.test.tsx` must stay green unchanged

**Interfaces:**
- Consumes: Task 1's routes.
- Produces: `export type Endpoint = 'settings' | 'setup'` (in `FieldList.tsx`); `FieldList({ fields, sections, values, onChange, advanced, query?, custom?, endpoint? })` rendering the visible fields with custom cards, Test buttons and pickers; `ServiceTest` and `Picker` accept `endpoint?: Endpoint` (default `'settings'`); `SettingField` accepts and forwards `endpoint`; `api.setupSchema(): Promise<SetupSchema>`, `api.setupTest(service, values)`, `api.setupPicker(name, values)`; types `WizardStepDef = { id; title; intro; keys: string[]; lite: boolean }`, `SetupSchema = { steps: WizardStepDef[]; fields: SettingsField[]; needs_first_admin: boolean }`.

- [ ] **Step 1: `api.ts`**

Add `required: boolean;` to `SettingsField` after `readonly`. After `SettingsSection` add:

```ts
export interface WizardStepDef {
  id: string;
  title: string;
  intro: string;
  keys: string[];
  lite: boolean;
}

export interface SetupSchema {
  steps: WizardStepDef[];
  fields: SettingsField[];
  needs_first_admin: boolean;
}
```

Next to `settingsSchema:` add:

```ts
  setupSchema: () => http<SetupSchema>('/setup/schema'),
  setupTest: (service: string, values: Record<string, string>) =>
    http<{ ok: boolean; message: string }>(`/setup/test/${service}`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    }),
  setupPicker: (name: string, values: Record<string, string>) =>
    http<{ ok: boolean; options?: { value: string; label: string }[]; error?: string }>(
      `/setup/picker/${name}`,
      { method: 'POST', body: JSON.stringify({ values }) },
    ),
```

- [ ] **Step 2: Write the failing `FieldList` test**

`frontend/src/pages/admin/settings/FieldList.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import type { SettingsField, SettingsSection } from '../../../api';
import { FieldList } from './FieldList';

const apiMocks = vi.hoisted(() => ({ settingsTest: vi.fn(), setupTest: vi.fn(), settingsPicker: vi.fn(), setupPicker: vi.fn() }));
vi.mock('../../../api', async () => {
  const actual = await vi.importActual<typeof import('../../../api')>('../../../api');
  return { ...actual, api: { ...actual.api, ...apiMocks } };
});

const f = (over: Partial<SettingsField>): SettingsField => ({
  key: 'K', label: 'Key', help: 'help', kind: 'str', options: null, placeholder: null, unit: null,
  min: null, max: null, advanced: false, depends_on: null, test: null, picker: null, component: null,
  readonly: false, required: false, value: '', overridden: false, hot_reload: true, ...over,
});
const FIELDS = [
  f({ key: 'RADARR_URL', label: 'Radarr URL', kind: 'url', test: 'radarr', value: 'http://r.test' }),
  f({ key: 'RADARR_ROOT_FOLDER', label: 'Radarr root folder', kind: 'path', picker: 'radarr_root_folders', value: '' }),
];
const SECTION: SettingsSection = { id: 's', title: 'S', description: 'd', icon: 'x', fields: FIELDS };

function renderIt(endpoint: 'settings' | 'setup') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const values = { RADARR_URL: 'http://r.test', RADARR_ROOT_FOLDER: '' };
  return render(
    <QueryClientProvider client={qc}>
      <FieldList fields={FIELDS} sections={[SECTION]} values={values} onChange={() => {}} advanced endpoint={endpoint} />
    </QueryClientProvider>,
  );
}

describe('FieldList endpoint', () => {
  beforeEach(() => vi.clearAllMocks());

  it('routes Test and Load through the settings API by default', async () => {
    apiMocks.settingsTest.mockResolvedValue({ ok: true, message: 'Radarr 5' });
    apiMocks.settingsPicker.mockResolvedValue({ ok: true, options: [{ value: '/movies', label: '/movies' }] });
    renderIt('settings');
    await userEvent.click(screen.getByRole('button', { name: 'Test Radarr' }));
    await waitFor(() => expect(apiMocks.settingsTest).toHaveBeenCalledWith('radarr', { RADARR_URL: 'http://r.test' }));
    await userEvent.click(screen.getByRole('button', { name: 'Load Radarr root folder' }));
    await waitFor(() => expect(apiMocks.settingsPicker).toHaveBeenCalled());
    expect(apiMocks.setupTest).not.toHaveBeenCalled();
  });

  it('routes them through the setup API when told to', async () => {
    apiMocks.setupTest.mockResolvedValue({ ok: true, message: 'Radarr 5' });
    apiMocks.setupPicker.mockResolvedValue({ ok: true, options: [] });
    renderIt('setup');
    await userEvent.click(screen.getByRole('button', { name: 'Test Radarr' }));
    await waitFor(() => expect(apiMocks.setupTest).toHaveBeenCalledWith('radarr', { RADARR_URL: 'http://r.test' }));
    await userEvent.click(screen.getByRole('button', { name: 'Load Radarr root folder' }));
    await waitFor(() => expect(apiMocks.setupPicker).toHaveBeenCalledWith('radarr_root_folders', { RADARR_URL: 'http://r.test' }));
    expect(apiMocks.settingsTest).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd frontend && npx vitest run src/pages/admin/settings/FieldList.test.tsx`
Expected: FAIL, cannot resolve `./FieldList`.

- [ ] **Step 4: Write `FieldList.tsx` and rewire**

`FieldList.tsx`:

```tsx
import type { ComponentType } from 'react';
import type { SettingsField, SettingsSection } from '../../../api';
import { ServiceTest } from './ServiceTest';
import { SettingField } from './SettingField';
import { isVisible, matchesQuery } from './visibility';
import type { FieldValue, Values } from './visibility';

export type Endpoint = 'settings' | 'setup';

export const SERVICE_LABEL: Record<string, string> = {
  torbox: 'TorBox', realdebrid: 'RealDebrid', tmdb: 'TMDB', zilean: 'Zilean', zilean_pg: 'Postgres',
  debridio: 'Debridio', jellyfin: 'Jellyfin', seerr: 'Seerr', radarr: 'Radarr', sonarr: 'Sonarr',
  trakt: 'Trakt', opensubtitles: 'OpenSubtitles', discord: 'Discord', telegram: 'Telegram', oidc: 'OIDC',
};

export type CustomCard = ComponentType<{ values: Values; onChange: (key: string, next: FieldValue) => void }>;

/** The fields of one section or wizard step: dependent fields hidden until
 * their toggle is on, advanced fields hidden in Simple mode, one Test button
 * per service after the last of its fields, custom cards by name. */
export function FieldList({
  fields, sections, values, onChange, advanced, query = '', custom = {}, endpoint = 'settings',
}: {
  fields: SettingsField[];
  sections: SettingsSection[];
  values: Values;
  onChange: (key: string, next: FieldValue) => void;
  advanced: boolean;
  query?: string;
  custom?: Record<string, CustomCard>;
  endpoint?: Endpoint;
}) {
  const visible = fields.filter((f) => f.kind === 'custom' || isVisible(f, values, advanced));
  const lastOfService: Record<string, string> = {};
  visible.forEach((f) => { if (f.test) lastOfService[f.test] = f.key; });
  return (
    <>
      {visible.map((f) => {
        if (f.kind === 'custom') {
          const C = custom[f.component || ''];
          return C ? <div key={f.key} className="py-3"><C values={values} onChange={onChange} /></div> : null;
        }
        return (
          <div key={f.key}>
            <SettingField field={f} value={values[f.key]} onChange={(v) => onChange(f.key, v)} values={values} sections={sections}
              dimmed={!matchesQuery(f, query)} endpoint={endpoint} />
            {f.test && lastOfService[f.test] === f.key && (
              <ServiceTest service={f.test} label={SERVICE_LABEL[f.test] || f.test} sections={sections} values={values} endpoint={endpoint} />
            )}
          </div>
        );
      })}
    </>
  );
}
```

`SectionView.tsx`: delete its `SERVICE_LABEL` and the `visible`/`lastOfService`/map block; keep the header, the `allAdvancedHidden` notice (it still needs `visible` for that computation, so keep `const visible = section.fields.filter(...)` for the notice only), and render `<Card><FieldList fields={section.fields} sections={sections} values={values} onChange={onChange} advanced={advanced} query={query} custom={custom} /></Card>`. Its `custom` prop type becomes `Record<string, CustomCard>` imported from `FieldList`.

`ServiceTest.tsx`: add `endpoint = 'settings'` prop (type `Endpoint` imported from `./FieldList`); `mutationFn: () => (endpoint === 'setup' ? api.setupTest : api.settingsTest)(service, serviceValues(sections, service, values))`.

`Picker.tsx`: same `endpoint` prop; `mutationFn: () => (endpoint === 'setup' ? api.setupPicker : api.settingsPicker)(field.picker!, serviceValues(sections, service, values))`.

`SettingField.tsx`: `Control` and `SettingField` accept `endpoint?: Endpoint` and pass it to `Picker`.

(`FieldList` imports `ServiceTest`, and `ServiceTest` imports the `Endpoint` type from `FieldList`: a type-only import, so no runtime cycle. If `tsc` or vitest complains, move `Endpoint` and `SERVICE_LABEL` into `visibility.ts` and import from there in all three files.)

- [ ] **Step 5: Run everything**

Run: `cd frontend && npx tsc --noEmit && npx vitest run`
Expected: green; `SectionView.test.tsx` passes unchanged.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api.ts frontend/src/pages/admin/settings/
git commit -m "refactor(ui): FieldList shared by Settings and the wizard, setup API endpoints

Claude-Session: https://claude.ai/code/session_01EZbQf8PvzNCADFo6bW74ko"
```

---

### Task 3: The wizard

**Files:**
- Create: `frontend/src/pages/setup/WizardStep.tsx`
- Rewrite: `frontend/src/pages/setup/StepRail.tsx`, `frontend/src/pages/Setup.tsx`, `frontend/src/pages/Setup.test.tsx`
- Delete: `frontend/src/pages/setup/{types.ts,fields.tsx,TestButton.tsx,StepWelcome.tsx,StepTorbox.tsx,StepJellyfin.tsx,StepSeerr.tsx,StepPreferences.tsx,StepCatbox.tsx,StepNotifications.tsx,StepTrakt.tsx,StepOpenSubtitles.tsx,StepZilean.tsx,StepRadarrSonarr.tsx}`
- Keep: `StepAccount.tsx`, `StepDone.tsx`
- Build: `static/app/` committed

**Interfaces:**
- Consumes: `api.setupSchema`, `FieldList` with `endpoint="setup"`, `initialValues`, `asString`, `serialize` from `visibility.ts`, `StepAccount` (`Account`, `EMPTY_ACCOUNT`), `StepDone`, `api.createUser`, `csrfToken`.
- Produces: default export `Setup` (mounted by `App.tsx` at `/setup`, unchanged); `WizardStep({ step, fields, values, onChange })`; `StepRail({ steps: {id,title}[], current: number })`.

- [ ] **Step 1: Rewrite `Setup.test.tsx` (failing first)**

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { SettingsField, SetupSchema } from '../api';
import Setup from './Setup';

const apiMocks = vi.hoisted(() => ({ setupSchema: vi.fn(), setupTest: vi.fn(), setupPicker: vi.fn(), createUser: vi.fn() }));
vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return { ...actual, api: { ...actual.api, ...apiMocks } };
});

const f = (over: Partial<SettingsField>): SettingsField => ({
  key: 'K', label: 'Key', help: 'help', kind: 'str', options: null, placeholder: null, unit: null,
  min: null, max: null, advanced: false, depends_on: null, test: null, picker: null, component: null,
  readonly: false, required: false, value: '', overridden: false, hot_reload: true, ...over,
});

function schema(over: Partial<SetupSchema> = {}): SetupSchema {
  return {
    steps: [
      { id: 'welcome', title: 'Welcome', intro: 'Pick how this runs.', keys: ['LITE_MODE'], lite: true },
      { id: 'torbox', title: 'TorBox', intro: 'The one required key.', keys: ['TORBOX_API_KEY'], lite: true },
      { id: 'zilean', title: 'Zilean', intro: 'Optional index.', keys: ['ZILEAN_ENABLED', 'ZILEAN_URL'], lite: false },
    ],
    fields: [
      f({ key: 'LITE_MODE', label: 'Lite mode', kind: 'bool', value: false, hot_reload: false }),
      f({ key: 'TORBOX_API_KEY', label: 'TorBox API key', kind: 'secret', required: true, value: false, test: 'torbox' }),
      f({ key: 'ZILEAN_ENABLED', label: 'Use Zilean', kind: 'bool', value: false }),
      f({ key: 'ZILEAN_URL', label: 'Zilean URL', kind: 'url', depends_on: 'ZILEAN_ENABLED', test: 'zilean', value: '' }),
    ],
    needs_first_admin: false,
    ...over,
  };
}

function setCsrfMeta(value: string) {
  document.head.querySelectorAll('meta[name="csrf-token"]').forEach((m) => m.remove());
  const meta = document.createElement('meta');
  meta.setAttribute('name', 'csrf-token');
  meta.setAttribute('content', value);
  document.head.appendChild(meta);
}

const next = () => userEvent.click(screen.getByRole('button', { name: /continue|finish/i }));

beforeEach(() => {
  vi.clearAllMocks();
  setCsrfMeta('test-csrf-token');
  apiMocks.setupSchema.mockResolvedValue(schema());
  vi.spyOn(window, 'alert').mockImplementation(() => {});
});
afterEach(() => {
  document.head.querySelectorAll('meta[name="csrf-token"]').forEach((m) => m.remove());
  vi.restoreAllMocks();
});

describe('Setup', () => {
  it('renders the steps from the schema, first step first, with the rail', async () => {
    render(<Setup />);
    expect(await screen.findByRole('heading', { name: 'Welcome' })).toBeInTheDocument();
    expect(screen.getByText('Pick how this runs.')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Lite mode' })).toBeInTheDocument();
    expect(screen.getAllByRole('listitem')).toHaveLength(3);
  });

  it('Lite mode hides the non-lite steps and the rail shrinks', async () => {
    render(<Setup />);
    await userEvent.click(await screen.findByRole('checkbox', { name: 'Lite mode' }));
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
    await next();
    await userEvent.type(screen.getByLabelText('TorBox API key'), 'tb');
    await next();
    expect(screen.getByRole('heading', { name: /all set/i })).toBeInTheDocument();
  });

  it('Continue is disabled while a required field is blank, unless it is already set', async () => {
    render(<Setup />);
    await next();
    expect(await screen.findByRole('heading', { name: 'TorBox' })).toBeInTheDocument();
    const btn = screen.getByRole('button', { name: /continue/i });
    expect(btn).toBeDisabled();
    await userEvent.type(screen.getByLabelText('TorBox API key'), 'tb');
    expect(btn).toBeEnabled();
  });

  it('a required secret that is already set does not block', async () => {
    apiMocks.setupSchema.mockResolvedValue(schema({
      fields: schema().fields.map((x) => (x.key === 'TORBOX_API_KEY' ? { ...x, value: true } : x)),
    }));
    render(<Setup />);
    await next();
    expect(await screen.findByRole('heading', { name: 'TorBox' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /continue/i })).toBeEnabled();
  });

  it('a dependent field appears when its toggle flips and Test posts the typed values through the setup API', async () => {
    apiMocks.setupTest.mockResolvedValue({ ok: true, message: 'Zilean answered HTTP 200' });
    render(<Setup />);
    await next();
    await userEvent.type(await screen.findByLabelText('TorBox API key'), 'tb');
    await next();
    expect(await screen.findByRole('heading', { name: 'Zilean' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Zilean URL')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('checkbox', { name: 'Use Zilean' }));
    await userEvent.type(screen.getByLabelText('Zilean URL'), 'http://z');
    await userEvent.click(screen.getByRole('button', { name: 'Test Zilean' }));
    await waitFor(() => expect(apiMocks.setupTest).toHaveBeenCalledWith('zilean', { ZILEAN_URL: 'http://z' }));
    expect(await screen.findByText('Zilean answered HTTP 200')).toBeInTheDocument();
  });

  it('finishing posts only the changed keys, unprefixed, as form fields', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }));
    render(<Setup />);
    await next();
    await userEvent.type(await screen.findByLabelText('TorBox API key'), 'tb');
    await next();
    await next();
    expect(await screen.findByRole('heading', { name: /all set/i })).toBeInTheDocument();
    await next();
    await waitFor(() => expect(fetchSpy).toHaveBeenCalledWith('/setup/save', expect.anything()));
    const init = fetchSpy.mock.calls.find((c) => c[0] === '/setup/save')![1] as RequestInit;
    const body = init.body as FormData;
    expect(body.get('TORBOX_API_KEY')).toBe('tb');
    expect(body.has('LITE_MODE')).toBe(false);
    expect(body.has('ZILEAN_ENABLED')).toBe(false);
    expect(init.headers).toMatchObject({ 'X-CSRFToken': 'test-csrf-token' });
  });

  it('collects an admin account before Done when the schema says so, and refuses mismatched passwords', async () => {
    apiMocks.setupSchema.mockResolvedValue(schema({ needs_first_admin: true }));
    const fetchSpy = vi.spyOn(global, 'fetch');
    render(<Setup />);
    await next();
    await userEvent.type(await screen.findByLabelText('TorBox API key'), 'tb');
    await next();
    await next();
    expect(await screen.findByRole('heading', { name: /create your admin account/i })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/^username$/i), 'adam');
    await userEvent.type(screen.getByLabelText(/^password$/i), 'hunter2');
    await userEvent.type(screen.getByLabelText(/confirm password/i), 'hunter3');
    await next();
    expect(await screen.findByRole('heading', { name: /all set/i })).toBeInTheDocument();
    await next();
    expect(window.alert).toHaveBeenCalledWith(expect.stringMatching(/do not match/i));
    expect(fetchSpy).not.toHaveBeenCalledWith('/setup/save', expect.anything());
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/pages/Setup.test.tsx`
Expected: FAIL (the old page ignores `setupSchema`).

- [ ] **Step 3: `WizardStep.tsx` and `StepRail.tsx`**

`WizardStep.tsx`:

```tsx
import type { SettingsField, SettingsSection, WizardStepDef } from '../../api';
import { FieldList } from '../admin/settings/FieldList';
import type { FieldValue, Values } from '../admin/settings/visibility';

/** One wizard step: its title and intro, then exactly the schema fields it
 * declares, through the same renderer as the Settings page. Test and Load
 * go through the /setup routes, which work before an admin exists. */
export default function WizardStep({
  step, fields, values, onChange,
}: {
  step: WizardStepDef;
  fields: SettingsField[];
  values: Values;
  onChange: (key: string, next: FieldValue) => void;
}) {
  const byKey = new Map(fields.map((f) => [f.key, f]));
  const stepFields = step.keys.map((k) => byKey.get(k)).filter((f): f is SettingsField => Boolean(f));
  const section: SettingsSection = { id: 'wizard', title: '', description: '', icon: '', fields };
  return (
    <div>
      <h2 className="mb-1.5 text-lg font-bold text-body">{step.title}</h2>
      <p className="mb-4 text-[13px] leading-relaxed text-muted">{step.intro}</p>
      <FieldList fields={stepFields} sections={[section]} values={values} onChange={onChange} advanced endpoint="setup" />
    </div>
  );
}

/** Keys on this step that are required and neither typed nor already set. */
export function missingRequired(step: WizardStepDef, fields: SettingsField[], values: Values): SettingsField[] {
  const byKey = new Map(fields.map((f) => [f.key, f]));
  return step.keys
    .map((k) => byKey.get(k))
    .filter((f): f is SettingsField => Boolean(f && f.required))
    .filter((f) => {
      const v = values[f.key];
      const typed = typeof v === 'string' ? v.trim() !== '' : Array.isArray(v) ? v.length > 0 : Boolean(v);
      const alreadySet = f.kind === 'secret' ? f.value === true : false;
      return !typed && !alreadySet;
    });
}
```

`StepRail.tsx` (rewrite):

```tsx
/** The content steps as a rail; `current` is the index of the active step,
 * or steps.length once past them (account and done bookends). */
export default function StepRail({ steps, current }: { steps: { id: string; title: string }[]; current: number }) {
  return (
    <div className="flex items-center" role="list" aria-label="setup steps">
      {steps.map((s, i) => {
        const done = current > i;
        const active = current === i;
        return (
          <div key={s.id} className="flex min-w-0 flex-1 items-center" role="listitem">
            <div className="flex w-14 flex-none flex-col items-center gap-1.5">
              <span
                className={`flex h-7 w-7 flex-none items-center justify-center rounded-full text-[11px] font-semibold ${
                  done
                    ? 'border border-ok/45 bg-ok/20 text-ok'
                    : active
                      ? 'border border-accent-light bg-accent text-white shadow-[0_0_0_4px_rgba(97,82,223,0.18)]'
                      : 'border border-border bg-white/[0.04] text-muted'
                }`}
              >
                {done ? '✓' : i + 1}
              </span>
              <span className={`max-w-[4.5rem] truncate text-[10px] tracking-wide ${active ? 'text-body' : 'text-muted'}`} title={s.title}>
                {s.title}
              </span>
            </div>
            {i < steps.length - 1 && <div className={`mb-[18px] h-px flex-1 ${done ? 'bg-ok/40' : 'bg-border'}`} />}
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 4: Rewrite `Setup.tsx`**

```tsx
import { useEffect, useMemo, useState } from 'react';
import { api, csrfToken } from '../api';
import type { SetupSchema, SettingsSection } from '../api';
import { initialValues, serialize } from './admin/settings/visibility';
import type { FieldValue, Values } from './admin/settings/visibility';
import StepRail from './setup/StepRail';
import WizardStep, { missingRequired } from './setup/WizardStep';
import StepDone from './setup/StepDone';
import StepAccount, { EMPTY_ACCOUNT } from './setup/StepAccount';
import type { Account } from './setup/StepAccount';

/** Pre-auth, chrome-less setup wizard driven by GET /setup/schema: the
 * steps and their fields come from the settings schema, pre-filled with the
 * current values, so a re-run shows what is configured today. */
export default function Setup() {
  const [schema, setSchema] = useState<SetupSchema | null>(null);
  const [loadError, setLoadError] = useState('');
  const [values, setValues] = useState<Values>({});
  const [initial, setInitial] = useState<Values>({});
  const [step, setStep] = useState(0);
  const [saving, setSaving] = useState(false);
  const [account, setAccount] = useState<Account>(EMPTY_ACCOUNT);

  useEffect(() => {
    api.setupSchema().then((s) => {
      const section: SettingsSection = { id: 'wizard', title: '', description: '', icon: '', fields: s.fields };
      const v = initialValues([section]);
      setSchema(s);
      setValues(v);
      setInitial(v);
    }).catch((e: Error) => setLoadError(e.message));
  }, []);

  const section: SettingsSection = useMemo(
    () => ({ id: 'wizard', title: '', description: '', icon: '', fields: schema?.fields || [] }),
    [schema],
  );
  const isLite = Boolean(values.LITE_MODE);
  const steps = useMemo(() => (schema?.steps || []).filter((s) => !isLite || s.lite), [schema, isLite]);
  const needsAccount = Boolean(schema?.needs_first_admin);
  const accountStep = needsAccount ? steps.length : -1;
  const doneStep = needsAccount ? steps.length + 1 : steps.length;
  const isDone = step === doneStep;
  const current = steps[step];
  const missing = current && schema ? missingRequired(current, schema.fields, values) : [];

  const onChange = (key: string, next: FieldValue) => setValues((p) => ({ ...p, [key]: next }));

  function accountProblem(): string | null {
    if (!needsAccount) return null;
    if (!account.username.trim()) return 'Choose a username.';
    if (account.password.length < 4) return 'Password must be at least 4 characters.';
    if (account.password !== account.confirm) return 'The passwords do not match.';
    return null;
  }

  async function finish() {
    const problem = accountProblem();
    if (problem) {
      window.alert(problem);
      return;
    }
    setSaving(true);
    try {
      const fd = new FormData();
      Object.entries(serialize([section], values, initial)).forEach(([k, v]) => fd.append(k.replace(/^setting_/, ''), v));
      const r = await fetch('/setup/save', { method: 'POST', body: fd, headers: { 'X-CSRFToken': csrfToken() } });
      if (!r.ok) throw new Error('save failed');
      if (needsAccount) {
        // Settings are saved but setup is deliberately not marked complete
        // until this succeeds: creating the first admin is what completes it.
        await api.createUser({ username: account.username.trim(), password: account.password, role: 'admin' });
      }
      window.location.href = '/ui';
    } catch (e: any) {
      setSaving(false);
      window.alert('Save failed: ' + e.message);
    }
  }

  function goNext() {
    if (isDone) {
      finish();
      return;
    }
    setStep((s) => Math.min(s + 1, doneStep));
  }

  function goBack() {
    setStep((s) => Math.max(s - 1, 0));
  }

  async function skipWizard() {
    if (!window.confirm('Skip the wizard? You can configure everything via Settings tab later.')) return;
    await fetch('/setup/skip', { method: 'POST', headers: { 'X-CSRFToken': csrfToken() } });
    window.location.href = '/ui';
  }

  // Lite can shrink the step list from under the current index.
  useEffect(() => {
    if (step > doneStep) setStep(doneStep);
  }, [step, doneStep]);

  if (loadError) return <p className="p-6 text-sm text-danger">Could not load the setup wizard: {loadError}</p>;
  if (!schema) return <p className="p-6 text-sm text-muted">Loading...</p>;

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-[640px] overflow-hidden rounded-xl border border-border bg-card shadow-2xl">
        <div className="border-b border-border px-7 pb-4 pt-6">
          <h1 className="font-mono text-xl font-bold text-body">
            myc<span className="text-accent-light">3</span>l<span className="text-accent-light">1</span>um setup
          </h1>
          <p className="mt-1 text-xs text-muted">
            One-time wizard to wire up the basics. You can change everything later in the Settings tab.
          </p>
          <div className="mt-3.5">
            <StepRail steps={steps} current={step} />
          </div>
        </div>

        <div className="min-h-[280px] px-7 py-6">
          {current && <WizardStep step={current} fields={schema.fields} values={values} onChange={onChange} />}
          {needsAccount && step === accountStep && <StepAccount account={account} setAccount={setAccount} />}
          {isDone && <StepDone />}
        </div>

        <div className="flex items-center justify-between border-t border-border bg-card-raised px-7 py-4">
          <button type="button" onClick={skipWizard} className="text-sm text-muted hover:text-body">Skip wizard</button>
          <div className="flex items-center gap-2.5">
            {step > 0 && (
              <button type="button" onClick={goBack} className="text-sm text-muted hover:text-body">Back</button>
            )}
            {missing.length > 0 && <span className="text-[11px] text-warn">{missing[0].label} is required.</span>}
            <button
              type="button"
              onClick={goNext}
              disabled={saving || missing.length > 0}
              className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white hover:bg-accent/90 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {saving ? 'Saving...' : isDone ? 'Finish' : 'Continue'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
```

`StepDone.tsx`: change "Settings &rarr; Connections" to "the Settings tab" (the Connections section no longer exists).

- [ ] **Step 5: Delete the old files**

```bash
cd frontend/src/pages/setup && git rm types.ts fields.tsx TestButton.tsx StepWelcome.tsx StepTorbox.tsx StepJellyfin.tsx StepSeerr.tsx StepPreferences.tsx StepCatbox.tsx StepNotifications.tsx StepTrakt.tsx StepOpenSubtitles.tsx StepZilean.tsx StepRadarrSonarr.tsx
```

Then `grep -rn "setup/types\|buildFormData\|SetupData\|loginFlags().needsFirstAdmin" frontend/src` must show no remaining importers (the `loginFlags` helper in `api.ts` stays; the login page uses it).

- [ ] **Step 6: Run everything and build**

Run: `cd frontend && npx tsc --noEmit && npx vitest run && npm run build`
Expected: green; `static/app/` rebuilt. Backend suite once for sanity.

- [ ] **Step 7: Commit**

```bash
git add -A frontend/src static/app
git commit -m "feat(setup): the wizard renders schema steps with the shared field kit, pre-filled

Claude-Session: https://claude.ai/code/session_01EZbQf8PvzNCADFo6bW74ko"
```

---

### Task 4: Docs

**Files:**
- Modify: `docs/install-guide.html` (the wizard description near line 387 and the TorBox step near line 532; `grep -n "wizard" docs/install-guide.html`), `README.md` (`grep -n "wizard" README.md`: the setup paragraph and the "/setup locked after first run" line), `CHANGELOG.md`

- [ ] **Step 1: Manual and README**

`docs/install-guide.html`: where the manual says the wizard "has a Test button for each integration so you can verify everything works before saving" (both language spans), extend the sentence: "...before saving, and a re-run from Admin, Settings pre-fills what is configured today. Quality preferences edit the same rules as the Filter rules tab." No other wizard steps are enumerated in the manual; if a step list exists, align it with the eleven titles in Task 1.

`README.md`: in the setup wizard paragraph, replace the sentence describing the steps (if any) with: "The wizard shows the same fields as Settings, pre-filled on a re-run, with Test buttons for every service and Load buttons for Radarr and Sonarr folders and profiles. Lite mode skips the Trakt, subtitle, Zilean and arr steps."

- [ ] **Step 2: CHANGELOG**

Prepend:

```markdown
## [Unreleased]

### Changed

- The setup wizard is driven by the settings schema: its steps are declared
  next to the schema, every field renders through the same kit as Settings
  (labels, help, dropdowns, pickers, Test buttons), and a re-run pre-fills
  the current values. The quality step edits the real filter rules
  (`RESOLUTION_PREFERRED`, `RESOLUTION_EXCLUDED`, `ENCODE_PREFERRED`,
  `LANGUAGE_PREFERRED`); the server-side translation of the retired
  `QUALITY_PREFERENCE`, `ALLOW_4K`, `PREFER_HEVC` and
  `AUDIO_LANGUAGE_PREFERENCE` names is gone.
- New `GET /setup/schema` and `POST /setup/picker/<name>`; `POST
  /setup/test/<kind>` also accepts a JSON body. All three share the setup
  gate (open until setup completes, admin afterwards).
```

- [ ] **Step 3: Both suites and commit**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/ -q -p no:cacheprovider
cd frontend && npx tsc --noEmit && npx vitest run && cd ..
git add docs/install-guide.html README.md CHANGELOG.md
git commit -m "docs(setup): schema-driven wizard

Claude-Session: https://claude.ai/code/session_01EZbQf8PvzNCADFo6bW74ko"
```

---

## Self-review notes

- Spec coverage: steps and rule fields, `required`, schema route, save allow-list and translator removal (Task 1); `FieldList` extraction and setup API (Task 2); shell, `WizardStep`, rail, required gate, save of changed keys, bookends, removals (Task 3); docs (Task 4). The spec's widening of the `/ui/api` picker and test gates is replaced by `/setup/picker/<name>` and JSON on `/setup/test/<kind>` for the reason stated in the header.
- Type consistency: `WizardStepDef` fields match `WIZARD_STEPS` keys; `SetupSchema.fields` are `SettingsField` with `required`; `FieldList`'s `endpoint` reaches `ServiceTest` and `Picker`; `serialize()` output keys are stripped of `setting_` before posting, matching `setup_save`'s bare-key form; `missingRequired` treats a secret with `value === true` as set, matching `_field_for_ui`'s True/False report.
- The old wizard auto-enabled Zilean when a URL was typed; the schema's dependent field (URL shown only once the toggle is on) makes that explicit instead.
