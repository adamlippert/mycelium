# Settings Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the admin Settings tab with a schema-driven page: section sidebar, one field renderer with real controls, label and help on every setting, a Test button per credentialed service, pickers for values that come from a service, Simple/Advanced, dependent fields and search.

**Architecture:** `settings.py` gains a declarative `SECTIONS` list (label, help, kind, options, advanced, depends_on, test, picker per key) that is the single source of truth; the old `SETTING_GROUPS` and `all_for_ui()` are derived from it and stay byte-compatible for the Filter rules tab. A new `service_tests.py` holds one tester per service and one picker per remote list; the wizard's `/setup/test/<kind>` and the `/ui/api/arr-import/*` routes call into it. The frontend gets four primitives (`Button`, `Select`, `MultiSelect`, `OrderedList`), a `SettingField` renderer, and a new `Settings.tsx` shell with sidebar, search, Simple/Advanced and the save bar.

**Tech Stack:** Python 3.12 / Flask backend, pytest; React 18 + TypeScript + Vite + Tailwind frontend, vitest + Testing Library. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-07-settings-redesign-design.md`

## Global Constraints

- Never use em-dashes or `--` in code, comments, copy or docs. Use a colon, comma or full stop.
- The repo is public: no passwords, tokens or IP addresses in any file.
- Work on branch `main`. Commit messages carry the trailer `Claude-Session: https://claude.ai/code/session_01EZbQf8PvzNCADFo6bW74ko`. No `Co-Authored-By`.
- Tests never import `app.py`; routes are checked on source text via a `_src()` helper. Every test file that touches the database carries its own `_isolated_db` autouse fixture (see `tests/test_arr_sync.py` lines 23 to 40). No `tests/conftest.py`. No test reaches the network: `requests.get/post` or the module's HTTP seam is faked.
- After a new test: mutation check (break the implementation, the test must fail, restore). Run pytest with `PYTHONDONTWRITEBYTECODE=1 -p no:cacheprovider`.
- Backend suite: `.venv-sdd/bin/python -m pytest tests/ -q -p no:cacheprovider` (currently 821 passed). Frontend: `cd frontend && npx tsc --noEmit && npx vitest run`. The built `static/app/` is committed after any frontend change (`npm run build`).
- The existing `GET /ui/api/settings` payload (`{groups:[{id,title,items}], hot_reload}`) and `settings.all_for_ui()` keep their exact shape: `FilterRules.tsx`, `tests/test_filter_rules.py` and `tests/test_filter_rules_ui.py` depend on them.
- Copy rules for labels and help: plain English, one sentence of help saying what the setting does and what a sensible value is, no code words unless the value itself is one. Secrets are never echoed in messages or logs.
- Setting names in the spec are authoritative. New keys introduced here: `RADARR_QUALITY_PROFILE`, `SONARR_QUALITY_PROFILE` (str, hot reload), `ARR_SYNC_INTERVAL_MINUTES` and `DISK_SYNC_INTERVAL_MINUTES` (int, restart), `OIDC_CLIENT_SECRET` (secret, restart; already in `config.py`).

## File structure

| File | Responsibility |
|---|---|
| `settings.py` | `SECTIONS` schema, `_UNLISTED_KEYS`, `schema_for_ui()`, `fields_by_key()`; `SETTING_GROUPS` derived |
| `service_tests.py` (new) | `TESTS` and `PICKERS` registries, `run()`, `pick()`, value fallback to saved settings |
| `radarr.py`, `sonarr.py` | `quality_profiles()` |
| `arr_sync.py` | `_defaults()` honours the quality profile setting by name |
| `config.py` | the new keys |
| `app.py` | `GET /ui/api/settings/schema`, `POST /ui/api/settings/test/<service>`, `POST /ui/api/settings/picker/<name>`; wizard and arr-import routes rerouted; scheduler reads the two interval keys through `settings` |
| `tests/test_settings_schema.py` (new) | schema guards and serializer |
| `tests/test_service_tests.py` (new) | testers, pickers, routes on source text |
| `frontend/src/components/primitives/{Button,Select,MultiSelect,OrderedList}.tsx` (new) | controls |
| `frontend/src/pages/admin/settings/visibility.ts` (new) | pure helpers: initial values, visibility, search, serialisation |
| `frontend/src/pages/admin/settings/{SettingField,ServiceTest,Picker,SectionView,customCards}.tsx` (new) | field renderer, service test, picker, section renderer, the custom cards |
| `frontend/src/pages/admin/Settings.tsx` | rewritten shell |
| `frontend/src/api.ts` | `SettingsField`, `SettingsSection`, `settingsSchema`, `settingsTest`, `settingsPicker` |
| `docs/INTEGRATIONS.md`, `docs/install-guide.html`, `CHANGELOG.md`, `README.md` | docs |

---

### Task 1: The schema in `settings.py`

**Files:**
- Modify: `settings.py` (replace the `SETTING_GROUPS` literal at lines 234 to 368; add `SECTIONS`, `_UNLISTED_KEYS`, `fields_by_key()`, `schema_for_ui()`; add the new keys to `_INT_KEYS` and `HOT_RELOAD`)
- Modify: `config.py` (after line 329, the `DISK_SYNC_INTERVAL_MINUTES` line): add `RADARR_QUALITY_PROFILE` and `SONARR_QUALITY_PROFILE`
- Test: `tests/test_settings_schema.py` (new)

**Interfaces:**
- Produces: `settings.SECTIONS: list[dict]` where each section is `{"id","title","description","icon","fields":[field...]}` and each field has exactly the keys `key,label,help,kind,options,placeholder,unit,min,max,advanced,depends_on,test,picker,component,readonly`. `settings.fields_by_key() -> dict[str, dict]`. `settings.schema_for_ui() -> list[dict]` (sections with fields plus `value`, `overridden`, `hot_reload`, resolved `options` as `[{"value","label"}]`). `settings.SETTING_GROUPS` keeps its old shape, derived. `settings._UNLISTED_KEYS: set[str]`.
- Consumed by Task 2 (`test` and `picker` names must match the registries), Task 4 and 5 (payload shape).

- [ ] **Step 1: Write the failing guard tests**

Create `tests/test_settings_schema.py`:

```python
"""The settings schema: one declaration per key that drives the admin
Settings page. Guards keep a new key from shipping without a label, and
keep the old groups payload byte-compatible for the Filter rules tab.
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
FIELD_KEYS = {"key", "label", "help", "kind", "options", "placeholder", "unit", "min", "max",
              "advanced", "depends_on", "test", "picker", "component", "readonly"}
KINDS = {"bool", "int", "float", "str", "list", "url", "path", "secret", "select",
         "multiselect", "ordered", "custom"}


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


def _fields():
    return [f for s in settings.SECTIONS for f in s["fields"]]


def test_every_field_has_exactly_the_declared_keys():
    for f in _fields():
        assert set(f) == FIELD_KEYS, f["key"]
        assert f["kind"] in KINDS, f["key"]


def test_every_field_has_a_label_and_help_without_dashes():
    for f in _fields():
        if f["kind"] == "custom":
            continue
        assert f["label"].strip() and f["help"].strip(), f["key"]
        for text in (f["label"], f["help"]):
            assert chr(0x2014) not in text and " -" + "- " not in text, f["key"]
    for s in settings.SECTIONS:
        assert s["title"].strip() and s["description"].strip() and s["icon"], s["id"]


def test_every_typed_key_is_listed_once_or_deliberately_unlisted():
    typed = (settings._BOOL_KEYS | settings._LIST_KEYS | settings._INT_KEYS
             | settings._FLOAT_KEYS | {*settings._ENUM_KEYS})
    listed = [f["key"] for f in _fields() if f["kind"] != "custom"]
    assert len(listed) == len(set(listed)), "a key appears in two sections"
    rule_keys = {*settings._RULE_LIST_KEYS} | settings._RULE_STRICT_KEYS
    missing = typed - set(listed) - settings._UNLISTED_KEYS - rule_keys
    assert not missing, f"typed keys without a field: {sorted(missing)}"
    assert not (set(listed) & settings._UNLISTED_KEYS)


def test_kind_agrees_with_the_type_buckets():
    for f in _fields():
        k, kind = f["key"], f["kind"]
        if kind == "custom":
            continue
        if k in settings._BOOL_KEYS:
            assert kind == "bool", k
        elif k in settings._INT_KEYS:
            assert kind == "int", k
        elif k in settings._FLOAT_KEYS:
            assert kind == "float", k
        elif k in settings._LIST_KEYS:
            assert kind in ("list", "multiselect", "ordered"), k
        elif k in settings._ENUM_KEYS:
            assert kind == "select", k
        else:
            assert kind in ("str", "url", "path", "secret", "select"), k


def test_depends_on_names_a_real_toggle_or_select_value():
    by_key = settings.fields_by_key()
    for f in _fields():
        dep = f["depends_on"]
        if not dep:
            continue
        key, _, value = dep.partition("=")
        assert key in by_key, f["key"]
        if value:
            assert by_key[key]["kind"] == "select", f["key"]
            assert value in [o["value"] for o in settings._resolve_options(by_key[key])], f["key"]
        else:
            assert by_key[key]["kind"] == "bool", f["key"]


def test_custom_fields_name_a_component_and_nothing_else_does():
    for f in _fields():
        assert bool(f["component"]) == (f["kind"] == "custom"), f["key"]


def test_the_secret_keys_are_declared_secret():
    for f in _fields():
        if re.search(r"KEY|TOKEN|SECRET|PASSWORD", f["key"]) and f["kind"] != "custom":
            assert f["kind"] == "secret", f["key"]


def test_the_old_groups_are_derived_and_keep_the_filter_rules_group():
    ids = [g["id"] for g in settings.SETTING_GROUPS]
    assert "filter_rules" in ids
    keys = {k for g in settings.SETTING_GROUPS for k in g["keys"]}
    assert keys >= {f["key"] for f in _fields() if f["kind"] != "custom"}
    payload = settings.all_for_ui()
    assert payload and {"id", "title", "items"} <= set(payload[0])


def test_schema_for_ui_carries_value_override_and_resolved_options():
    settings.set("MIN_SEEDERS", 7)
    settings.set("RADARR_URL", "http://radarr.test")
    out = settings.schema_for_ui()
    by_key = {f["key"]: f for s in out for f in s["fields"]}
    assert by_key["MIN_SEEDERS"]["value"] == 7 and by_key["MIN_SEEDERS"]["overridden"] is True
    assert by_key["MAX_SIZE_GB"]["overridden"] is False
    assert by_key["RADARR_URL"]["hot_reload"] is True
    langs = by_key["OPENSUBTITLES_LANGUAGES"]["options"]
    assert {"value": "en", "label": "en"} in langs
    sort = by_key["SORT_ORDER"]["options"]
    assert [o["value"] for o in sort] == list(settings._streams.SORT_CRITERIA)
    assert by_key["ZILEAN_MODE"]["options"] == [{"value": "external", "label": "External service"},
                                                 {"value": "native", "label": "Native index"}]
    assert by_key["AUTO_ADD_REGION"]["options"][0] == {"value": "NL", "label": "Netherlands"}
    assert by_key["RADARR_ROOT_FOLDER"]["picker"] == "radarr_root_folders"
    assert by_key["TORBOX_API_KEY"]["test"] == "torbox"
    # A secret's value is never sent to the browser, only whether it is set.
    settings.set("TORBOX_API_KEY", "abc")
    out = settings.schema_for_ui()
    tb = next(f for s in out for f in s["fields"] if f["key"] == "TORBOX_API_KEY")
    assert tb["value"] is True


def test_the_new_keys_are_typed_and_have_defaults():
    import config
    assert "ARR_SYNC_INTERVAL_MINUTES" in settings._INT_KEYS
    assert "DISK_SYNC_INTERVAL_MINUTES" in settings._INT_KEYS
    assert "RADARR_QUALITY_PROFILE" in settings.HOT_RELOAD and "SONARR_QUALITY_PROFILE" in settings.HOT_RELOAD
    assert config.RADARR_QUALITY_PROFILE == "" and config.SONARR_QUALITY_PROFILE == ""


def test_the_schema_route_exists_and_is_admin_only():
    src = _src("app.py")
    m = re.search(r'@app\.get\("/ui/api/settings/schema"\)\s*\ndef (\w+)\(\):(.*?)\n\n', src, re.S)
    assert m and "is_admin()" in m.group(2) and "schema_for_ui()" in m.group(2)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/test_settings_schema.py -q -p no:cacheprovider`
Expected: FAIL, `AttributeError: module 'settings' has no attribute 'SECTIONS'`

- [ ] **Step 3: Add the new keys to `config.py`**

After the `DISK_SYNC_INTERVAL_MINUTES` line in `config.py`:

```python
# Quality profile the mirror uses when adding a title, by name. Blank means
# the arr's first profile, which is what older releases always used.
RADARR_QUALITY_PROFILE = _env("RADARR_QUALITY_PROFILE", "")
SONARR_QUALITY_PROFILE = _env("SONARR_QUALITY_PROFILE", "")
```

- [ ] **Step 4: Type the new keys in `settings.py`**

In `_INT_KEYS` add `"ARR_SYNC_INTERVAL_MINUTES", "DISK_SYNC_INTERVAL_MINUTES",`. In `HOT_RELOAD` next to `"RADARR_ROOT_FOLDER", "SONARR_ROOT_FOLDER",` add `"RADARR_QUALITY_PROFILE", "SONARR_QUALITY_PROFILE",`.

- [ ] **Step 5: Replace `SETTING_GROUPS` with `SECTIONS` and derive the old groups**

Delete the whole `SETTING_GROUPS = [ ... ]` literal (from the comment `# Logical groups for the Settings UI tab.` through its closing `]`) and put this in its place. Every `_f()` call below is the copy for that field; keep the wording.

```python
# Region list for AUTO_ADD_REGION. Mirrors frontend/src/components/shell/RegionPicker.tsx.
_REGIONS = [
    ("NL", "Netherlands"), ("BE", "Belgium"), ("ZA", "South Africa"), ("US", "United States"),
    ("GB", "United Kingdom"), ("DE", "Germany"), ("FR", "France"), ("ES", "Spain"),
    ("IT", "Italy"), ("AU", "Australia"), ("CA", "Canada"), ("BR", "Brazil"), ("IN", "India"),
    ("JP", "Japan"), ("KR", "South Korea"), ("SE", "Sweden"), ("NO", "Norway"),
    ("DK", "Denmark"), ("PT", "Portugal"), ("PL", "Poland"),
]

# Option resolvers: a field whose options come from a vocabulary defined
# elsewhere names the resolver instead of listing values.
_OPTION_RESOLVERS = {
    "languages": lambda: [{"value": c, "label": c} for c in _streams.LANGUAGE_CODES],
    "sort_criteria": lambda: [{"value": c, "label": c.replace("_", " ")} for c in _streams.SORT_CRITERIA],
    "regions": lambda: [{"value": c, "label": n} for c, n in _REGIONS],
    "zilean_mode": lambda: [{"value": "external", "label": "External service"},
                            {"value": "native", "label": "Native index"}],
}


def _f(key, label, help, kind=None, *, options=None, placeholder=None, unit=None,
       min=None, max=None, advanced=False, depends_on=None, test=None, picker=None,
       component=None, readonly=False):
    """One field declaration. kind defaults from the type buckets; pass it
    only to refine (url, path, secret, select, multiselect, ordered) or for
    a custom card."""
    if kind is None:
        kind = ("bool" if key in _BOOL_KEYS else "int" if key in _INT_KEYS
                else "float" if key in _FLOAT_KEYS else "list" if key in _LIST_KEYS
                else "select" if key in _ENUM_KEYS else "str")
    return {"key": key, "label": label, "help": help, "kind": kind, "options": options,
            "placeholder": placeholder, "unit": unit, "min": min, "max": max,
            "advanced": advanced, "depends_on": depends_on, "test": test, "picker": picker,
            "component": component, "readonly": readonly}


def _custom(component, label=""):
    return _f(f"__{component}", label, "", "custom", component=component)


SECTIONS = [
    {
        "id": "mode", "title": "Mode", "icon": "⚙",
        "description": "How this Mycelium runs: full or lite, and whether titles are fetched on demand.",
        "fields": [
            _f("LITE_MODE", "Lite mode",
               "Run only the webhook, the processor and this admin: no Discover, no schedulers, no plugins. For Seerr and Jellyfin-only setups. Restart after changing."),
            _f("CATBOX_MODE", "Catbox mode",
               "Add a torrent to TorBox only when someone presses play, and drop it again after idling. Needed for the on-demand library and the arr stub files. Restart after changing."),
            _f("CATBOX_HOST", "Public URL", "Address Jellyfin and other players can reach Mycelium on, used inside every .strm file.",
               "url", placeholder="https://mycelium.example.com", depends_on="CATBOX_MODE"),
            _f("CATBOX_LAZY_ADD", "Lazy add",
               "Skip the TorBox add at request time and do it on first play only. Saves TorBox adds, costs a longer first start.",
               depends_on="CATBOX_MODE"),
            _f("CATBOX_PRELOAD", "Preload on request",
               "Add the torrent to TorBox as soon as a request succeeds so the first play starts fast. Each request spends one of the 60 hourly adds.",
               depends_on="CATBOX_MODE"),
            _f("CATBOX_IDLE_MINUTES", "Idle minutes before release",
               "How long a title may sit unplayed before its torrent is removed from TorBox again. 1440 is one day.",
               unit="minutes", min=5, advanced=True, depends_on="CATBOX_MODE"),
            _f("CATBOX_GC_INTERVAL_MINUTES", "Idle check interval", "How often idle titles are looked for. Restart after changing.",
               unit="minutes", min=1, advanced=True, depends_on="CATBOX_MODE"),
            _f("DISK_SYNC_ENABLED", "Purge titles deleted on disk",
               "Once an hour, a title whose .strm files are gone (a Jellyfin delete) is removed from Mycelium too. Off keeps the files coming back.",
               depends_on="CATBOX_MODE"),
            _f("WEBDAV_ENABLED", "WebDAV share", "Serve the library over WebDAV as well. Restart after changing.", advanced=True),
        ],
    },
    {
        "id": "debrid", "title": "Debrid", "icon": "☁",
        "description": "TorBox is where torrents are cached and streamed from. RealDebrid can stand in when a release is only cached there.",
        "fields": [
            _f("TORBOX_API_KEY", "TorBox API key", "From TorBox, Settings, API. Required for everything.", "secret", test="torbox"),
            _f("TORBOX_BASE_URL", "TorBox API URL", "Leave the default unless TorBox publishes a new API address.",
               "url", placeholder="https://api.torbox.app/v1/api", advanced=True, test="torbox"),
            _f("TORBOX_POLL_INTERVAL_SEC", "Poll interval", "Seconds between checks while waiting for TorBox to finish caching a torrent.",
               unit="seconds", min=1, advanced=True),
            _f("TORBOX_POLL_TIMEOUT_SEC", "Poll timeout", "Give up waiting for TorBox after this many seconds and report the title as failed for now.",
               unit="seconds", min=30, advanced=True),
            _f("MULTI_DEBRID_ENABLED", "RealDebrid fallback", "Try RealDebrid when a release is not cached on TorBox."),
            _f("REALDEBRID_API_KEY", "RealDebrid API key", "From real-debrid.com, My account, API token.",
               "secret", depends_on="MULTI_DEBRID_ENABLED", test="realdebrid"),
        ],
    },
    {
        "id": "scrapers", "title": "Scrapers and metadata", "icon": "\U0001F50D",
        "description": "Where releases are searched for, and where titles, posters and runtimes come from.",
        "fields": [
            _f("TMDB_API_KEY", "TMDB API key", "A free key from themoviedb.org. Powers Discover, posters and the runtime in stub files.",
               "secret", test="tmdb"),
            _f("ZILEAN_ENABLED", "Use Zilean", "Search a Zilean DMM index next to Torrentio for cached releases."),
            _f("ZILEAN_MODE", "Zilean mode", "External talks to a running Zilean service. Native imports its Postgres into a built-in index.",
               options="zilean_mode", depends_on="ZILEAN_ENABLED"),
            _f("ZILEAN_URL", "Zilean URL", "Address of the Zilean service.", "url",
               placeholder="http://zilean:8181", depends_on="ZILEAN_MODE=external", test="zilean"),
            _f("ZILEAN_PG_HOST", "Postgres host", "Host name of Zilean's Postgres database.", placeholder="zilean-postgres",
               depends_on="ZILEAN_MODE=native", test="zilean_pg"),
            _f("ZILEAN_PG_PORT", "Postgres port", "Usually 5432.", min=1, max=65535, depends_on="ZILEAN_MODE=native", test="zilean_pg"),
            _f("ZILEAN_PG_DB", "Postgres database", "Database name, usually zilean.", depends_on="ZILEAN_MODE=native", test="zilean_pg"),
            _f("ZILEAN_PG_USER", "Postgres user", "Database user with read access.", depends_on="ZILEAN_MODE=native", test="zilean_pg"),
            _f("ZILEAN_PG_PASSWORD", "Postgres password", "Password for that user.", "secret",
               depends_on="ZILEAN_MODE=native", test="zilean_pg"),
            _f("DEBRIDIO_ENABLED", "Use Debridio", "Search the Debridio addon as well. Needs its own API key."),
            _f("DEBRIDIO_API_KEY", "Debridio API key", "From your Debridio account.", "secret",
               depends_on="DEBRIDIO_ENABLED", test="debridio"),
            _f("DEBRIDIO_BASE_URL", "Debridio URL", "Leave the default unless you host the addon yourself.", "url",
               placeholder="https://addon.debridio.com", advanced=True, depends_on="DEBRIDIO_ENABLED", test="debridio"),
            _f("DEBRIDIO_MAX_RESULTS", "Debridio result limit", "Most results to take from one Debridio search.",
               min=1, max=500, advanced=True, depends_on="DEBRIDIO_ENABLED"),
            _f("DEBRIDIO_CONFIG_TOKEN", "Debridio config token", "Only if you built a config token in the addon yourself; blank lets Mycelium build one.",
               "secret", advanced=True, depends_on="DEBRIDIO_ENABLED"),
        ],
    },
    {
        "id": "jellyfin", "title": "Jellyfin", "icon": "\U0001F3AC",
        "description": "The media server that plays the library. Mycelium tells it what changed.",
        "fields": [
            _f("JELLYFIN_URL", "Jellyfin URL", "Address Mycelium can reach Jellyfin on, from inside Docker if both run there.",
               "url", placeholder="http://jellyfin:8096", test="jellyfin"),
            _f("JELLYFIN_API_KEY", "Jellyfin API key", "Dashboard, API Keys. Lets Mycelium trigger library refreshes.",
               "secret", test="jellyfin"),
            _f("JELLYFIN_MEDIA_PATH", "Media path as Jellyfin sees it",
               "Only when Jellyfin mounts the media folder at a different path than Mycelium does. Blank means the same path.",
               "path", placeholder="/media"),
            _f("JELLYFIN_REFRESH_DELAY_SEC", "Refresh delay", "Seconds to wait after writing files before asking Jellyfin to look.",
               unit="seconds", min=0, advanced=True),
        ],
    },
    {
        "id": "seerr", "title": "Seerr", "icon": "\U0001F4EC",
        "description": "Requests arrive from Seerr through a webhook; outcomes are reported back.",
        "fields": [
            _f("SEERR_URL", "Seerr URL", "Address of Seerr, Overseerr or Jellyseerr.", "url",
               placeholder="http://seerr:5055", test="seerr"),
            _f("SEERR_API_KEY", "Seerr API key", "Settings, General, API key in Seerr.", "secret", test="seerr"),
            _f("SEERR_REPORT_STATUS", "Report outcomes to Seerr",
               "Mark a request available when its files exist, declined when it finally failed, and remove its media entry when purged."),
            _f("SEERR_DECLINE_WANTED_AFTER_DAYS", "Decline wanted after",
               "Days a released title may stay without a release before Seerr is told it was declined. 0 never declines.",
               unit="days", min=0),
            _custom("WebhookSecret", "Webhook secret"),
        ],
    },
    {
        "id": "arrs", "title": "Radarr / Sonarr", "icon": "\U0001F4E1",
        "description": "Mirror the library into Radarr and Sonarr so Seerr, Maintainerr and calendars see it. The arrs never download anything.",
        "fields": [
            _f("ARR_SYNC_ENABLED", "Mirror the library", "Create every title in the arr as a monitored entry with search off, and remove it on purge."),
            _f("RADARR_URL", "Radarr URL", "Address Mycelium can reach Radarr on.", "url",
               placeholder="http://radarr:7878", depends_on="ARR_SYNC_ENABLED", test="radarr"),
            _f("RADARR_API_KEY", "Radarr API key", "Settings, General, API Key in Radarr.", "secret",
               depends_on="ARR_SYNC_ENABLED", test="radarr"),
            _f("RADARR_ROOT_FOLDER", "Radarr root folder", "Where mirrored movies are filed in Radarr. Blank uses its first root folder.",
               "path", depends_on="ARR_SYNC_ENABLED", picker="radarr_root_folders"),
            _f("RADARR_QUALITY_PROFILE", "Radarr quality profile", "Profile new entries get. Blank uses the first profile.",
               depends_on="ARR_SYNC_ENABLED", picker="radarr_quality_profiles"),
            _f("SONARR_URL", "Sonarr URL", "Address Mycelium can reach Sonarr on.", "url",
               placeholder="http://sonarr:8989", depends_on="ARR_SYNC_ENABLED", test="sonarr"),
            _f("SONARR_API_KEY", "Sonarr API key", "Settings, General, API Key in Sonarr.", "secret",
               depends_on="ARR_SYNC_ENABLED", test="sonarr"),
            _f("SONARR_ROOT_FOLDER", "Sonarr root folder", "Where mirrored series are filed in Sonarr. Blank uses its first root folder.",
               "path", depends_on="ARR_SYNC_ENABLED", picker="sonarr_root_folders"),
            _f("SONARR_QUALITY_PROFILE", "Sonarr quality profile", "Profile new entries get. Blank uses the first profile.",
               depends_on="ARR_SYNC_ENABLED", picker="sonarr_quality_profiles"),
            _f("ARR_STUBS_ENABLED", "Write stub files for the arrs",
               "Put a tiny MKV per title in a folder the arrs mount as their root, so titles show as present instead of missing. Needs Catbox mode.",
               depends_on="ARR_SYNC_ENABLED"),
            _f("ARR_STUB_PATH", "Stub folder", "Folder inside this container where the stubs are written; mount it in Radarr and Sonarr as their root folders.",
               "path", placeholder="/arr-stubs", depends_on="ARR_STUBS_ENABLED"),
            _f("ARR_SYNC_PURGE_ENABLED", "Purge titles deleted in the arr",
               "Once an hour, a mirrored title the arr no longer holds is removed from Mycelium. Off re-adds it to the arr instead.",
               depends_on="ARR_SYNC_ENABLED"),
        ],
    },
    {
        "id": "quality", "title": "Quality", "icon": "⭐",
        "description": "Size and seeder floors and the sort order. Which resolutions, sources and languages win lives in the Filter rules tab.",
        "fields": [
            _f("MIN_SEEDERS", "Minimum seeders", "Releases with fewer seeders are ignored. 3 is a safe floor for cached content.", min=0),
            _f("MAX_SIZE_GB", "Maximum size", "Largest release to accept, in GB. 0 means no limit.", unit="GB", min=0),
            _f("MAX_SIZE_GB_BY_RESOLUTION", "Size cap per resolution",
               "Caps per resolution as resolution:GB pairs, for example 2160p:40,1080p:12. Blank uses the single maximum above.",
               placeholder="2160p:40,1080p:12"),
            _f("PREFER_SMALLER_FILES", "Prefer smaller files", "When two releases tie, take the smaller one."),
            _f("EXCLUDE_UNDERSIZED_RELEASES", "Skip undersized releases",
               "Drop releases far smaller than expected for their resolution; they are usually re-encodes or fakes."),
            _f("EXCLUDE_UNDERSIZED_STRICT", "Undersized rule is strict",
               "Keep dropping undersized releases even when nothing else is left. Off relaxes the rule rather than return nothing.",
               advanced=True),
            _f("WEB_PLAYER_MAX_SIZE_GB", "Web player size limit", "Largest release the built-in web player will pick, in GB.", unit="GB", min=0),
            _f("SORT_ORDER", "Sort order", "Which properties decide between surviving releases, most important first.",
               "ordered", options="sort_criteria"),
            _f("BLACKLIST_FAIL_THRESHOLD", "Blacklist after failures", "A release that fails this many times is never tried again.",
               min=1, advanced=True),
            _custom("FilterRulesLink", "Filter rules"),
        ],
    },
    {
        "id": "subtitles", "title": "Subtitles", "icon": "\U0001F4AC",
        "description": "Subtitle download from OpenSubtitles.",
        "fields": [
            _f("OPENSUBTITLES_API_KEY", "OpenSubtitles API key", "From opensubtitles.com, API consumers.", "secret", test="opensubtitles"),
            _f("OPENSUBTITLES_LANGUAGES", "Subtitle languages", "Languages to fetch subtitles for.", "multiselect", options="languages"),
            _f("OPENSUBTITLES_USER_AGENT", "User agent", "Sent with every OpenSubtitles request; they ask for an app name and version.",
               advanced=True),
        ],
    },
    {
        "id": "automation", "title": "Automation", "icon": "\U0001F916",
        "description": "Background jobs that improve and repair the library on their own.",
        "fields": [
            _f("AUTO_UPGRADE_ENABLED", "Auto-upgrade quality", "Replace a title when a better release matching your rules appears."),
            _f("AUTO_UPGRADE_INTERVAL_HOURS", "Upgrade check interval", "How often to look for upgrades.",
               unit="hours", min=1, advanced=True, depends_on="AUTO_UPGRADE_ENABLED"),
            _f("SEASON_PACK_CONSOLIDATION_ENABLED", "Consolidate season packs",
               "Replace single episodes with a season pack once one is cached, so a season is one torrent."),
            _f("SEASON_PACK_CHECK_INTERVAL_HOURS", "Season pack check interval", "How often to look for packs.",
               unit="hours", min=1, advanced=True, depends_on="SEASON_PACK_CONSOLIDATION_ENABLED"),
            _f("CATCHUP_ENABLED", "Catch up missed requests", "After a restart, re-run requests that were interrupted.", advanced=True),
            _f("CATCHUP_DELAY_SEC", "Catch-up delay", "Seconds after boot before catch-up starts.", unit="seconds", min=0,
               advanced=True, depends_on="CATCHUP_ENABLED"),
            _f("CATCHUP_TAKE", "Catch-up batch", "Most requests to re-run in one catch-up.", min=1, advanced=True, depends_on="CATCHUP_ENABLED"),
            _f("MAX_RETRY_ATTEMPTS", "Retry attempts", "Times a failed request is retried before it is declined for good.", min=0, advanced=True),
            _custom("GenreTabs", "Discover genre tabs"),
        ],
    },
    {
        "id": "auto_add", "title": "Auto-add", "icon": "➕",
        "description": "Request popular titles without anyone asking. Each one spends a TorBox add.",
        "fields": [
            _f("TRENDING_PRECACHE_COUNT", "Trending movies", "How many trending movies to add each run. 0 is off.", min=0),
            _f("TRENDING_TV_COUNT", "Trending series", "How many trending series to add each run. 0 is off.", min=0),
            _f("POPULAR_MOVIE_COUNT", "Popular movies", "How many popular movies to add each run. 0 is off.", min=0),
            _f("POPULAR_TV_COUNT", "Popular series", "How many popular series to add each run. 0 is off.", min=0),
            _f("NETFLIX_NL_TOP_COUNT", "Netflix top list", "How many from the Netflix top list for your region. 0 is off.", min=0),
            _f("PRIME_NL_TOP_COUNT", "Prime Video top list", "How many from the Prime Video top list. 0 is off.", min=0),
            _f("DISNEY_NL_TOP_COUNT", "Disney+ top list", "How many from the Disney+ top list. 0 is off.", min=0),
            _f("AUTO_ADD_MIN_RATING", "Minimum rating", "Skip titles rated below this on TMDB.", min=0, max=10),
            _f("AUTO_ADD_MIN_VOTES", "Minimum votes", "Skip titles with fewer TMDB votes, which filters out obscure entries.", min=0),
            _f("AUTO_ADD_REGION", "Region", "Country the streaming top lists are taken for.", "select", options="regions"),
            _f("TRENDING_CHECK_INTERVAL_HOURS", "Auto-add interval", "How often auto-add runs.", unit="hours", min=1, advanced=True),
            _custom("AutoAddNow", "Run now"),
        ],
    },
    {
        "id": "auto_approve", "title": "Auto-approve and imports", "icon": "✅",
        "description": "Limits for requests Mycelium approves on its own, and the Trakt and MDBList imports.",
        "fields": [
            _f("AUTO_APPROVE_DAILY_LIMIT", "Genre rule daily limit", "Most titles the genre rules may approve per day.", min=0),
            _f("AUTO_APPROVE_ACTOR_DAILY_LIMIT", "Favourite actor daily limit", "Most titles the favourite-actor rule may approve per day.", min=0),
            _f("TRAKT_CLIENT_ID", "Trakt client id", "From trakt.tv, Settings, Your API apps.", test="trakt"),
            _f("TRAKT_CLIENT_SECRET", "Trakt client secret", "The secret of that API app.", "secret"),
            _f("TRAKT_AUTO_REQUEST_CAP", "Trakt import cap", "Most titles a Trakt watchlist sync may request per run.", min=0),
            _f("MDBLIST_AUTO_REQUEST_CAP", "MDBList import cap", "Most titles an MDBList sync may request per run.", min=0),
        ],
    },
    {
        "id": "security", "title": "Security", "icon": "\U0001F512",
        "description": "Who can log in and how.",
        "fields": [
            _f("AUTH_ENABLED", "Require login", "Ask for a login on every page. Off is only safe behind another login."),
            _f("AUTH_USERNAME", "Admin username", "Username for the built-in admin login."),
            _f("TRUSTED_PROXY_AUTH", "Trust a proxy header", "Accept the user name from a header set by a reverse proxy such as Authelia."),
            _f("TRUSTED_PROXY_USER_HEADER", "Proxy user header", "Header carrying the user name.", placeholder="X-Forwarded-User",
               advanced=True, depends_on="TRUSTED_PROXY_AUTH"),
            _f("TRUSTED_PROXY_NETWORKS", "Trusted networks", "Only requests from these networks (CIDR, comma separated) may carry that header.",
               placeholder="127.0.0.1/32,10.0.0.0/8", advanced=True, depends_on="TRUSTED_PROXY_AUTH"),
            _f("OIDC_ENABLED", "Single sign-on (OIDC)", "Log in through an OpenID Connect provider such as Authentik or Keycloak. Restart after changing."),
            _f("OIDC_PROVIDER_NAME", "Provider name", "Shown on the login button.", placeholder="SSO", depends_on="OIDC_ENABLED"),
            _f("OIDC_ISSUER_URL", "Issuer URL", "The provider's issuer; its discovery document lives at /.well-known/openid-configuration below it.",
               "url", placeholder="https://auth.example.com/application/o/mycelium/", depends_on="OIDC_ENABLED", test="oidc"),
            _f("OIDC_CLIENT_ID", "Client id", "Client id registered for Mycelium at the provider.", depends_on="OIDC_ENABLED", test="oidc"),
            _f("OIDC_CLIENT_SECRET", "Client secret", "Client secret from the provider.", "secret", depends_on="OIDC_ENABLED"),
            _f("OIDC_SCOPES", "Scopes", "Scopes to request. The default covers a user name and email.",
               placeholder="openid email profile", advanced=True, depends_on="OIDC_ENABLED"),
            _f("OIDC_USER_CLAIM", "User name claim", "Which claim becomes the Mycelium user name.",
               placeholder="preferred_username", advanced=True, depends_on="OIDC_ENABLED"),
            _custom("LegacyPassword", "Legacy password"),
        ],
    },
    {
        "id": "notifications", "title": "Notifications", "icon": "\U0001F514",
        "description": "Where to hear about finished and failed requests.",
        "fields": [
            _f("NOTIFY_ON_SUCCESS", "Notify on success", "Send a message when a request lands."),
            _f("NOTIFY_ON_FAILURE", "Notify on failure", "Send a message when a request fails for good."),
            _f("DISCORD_WEBHOOK_URL", "Discord webhook URL", "A webhook from a Discord channel's integrations page. Treated as a secret.",
               "secret", test="discord"),
            _f("TELEGRAM_BOT_TOKEN", "Telegram bot token", "Token from BotFather.", "secret", test="telegram"),
            _f("TELEGRAM_CHAT_ID", "Telegram chat id", "The chat or channel the bot posts to.", test="telegram"),
        ],
    },
    {
        "id": "intervals", "title": "Intervals", "icon": "⏱",
        "description": "How often each background job runs. Restart after changing any of these.",
        "fields": [
            _f("STRM_GENERATOR_INTERVAL_HOURS", "Library repair", "Regenerates missing or expired .strm files.", unit="hours", min=1, advanced=True),
            _f("CLEANUP_INTERVAL_HOURS", "Cleanup", "Removes dead and duplicate files.", unit="hours", min=1, advanced=True),
            _f("MONITOR_INTERVAL_HOURS", "Series monitor", "Looks for new episodes of monitored series.", unit="hours", min=1, advanced=True),
            _f("MOVIE_SYNC_INTERVAL_MINUTES", "Wanted movies", "Retries movies that were released but had no release yet.", unit="minutes", min=1, advanced=True),
            _f("MERGE_VERSIONS_INTERVAL_HOURS", "Merge versions", "Folds duplicate versions of a title together.", unit="hours", min=1, advanced=True),
            _f("BACKUP_INTERVAL_HOURS", "Database backup", "Copies the database to the backups folder.", unit="hours", min=1, advanced=True),
            _f("RETRY_QUEUE_INTERVAL_MINUTES", "Retry queue", "Retries requests that hit a temporary error.", unit="minutes", min=1, advanced=True),
            _f("CONTINUE_WATCHING_INTERVAL_MINUTES", "Continue watching", "Refreshes the continue-watching row from Jellyfin.", unit="minutes", min=1, advanced=True),
            _f("AUTO_APPROVE_INTERVAL_HOURS", "Auto-approve", "Runs the genre and favourite-actor rules.", unit="hours", min=1, advanced=True),
            _f("ARR_SYNC_INTERVAL_MINUTES", "Arr reconcile", "Adds what the arrs lack and purges what was deleted there. 0 disables it.", unit="minutes", min=0, advanced=True),
            _f("DISK_SYNC_INTERVAL_MINUTES", "On-disk deletion check", "Purges titles whose files were deleted. 0 disables it.", unit="minutes", min=0, advanced=True),
            _f("HEALTH_CACHE_SECONDS", "Health cache", "How long the Overview health rows are cached.", unit="seconds", min=5, advanced=True),
        ],
    },
]

# Typed keys that have no field on purpose: retired filter booleans (the
# rules editor replaced them, see migrate_filters.RETIRED) and internal
# markers nobody should edit by hand.
_UNLISTED_KEYS = {
    "ALLOW_4K", "EXCLUDE_REMUX", "EXCLUDE_BLURAY", "EXCLUDE_CAM", "STRICT_NO_CAM",
    "PREFER_WEBDL", "PREFER_HEVC", "QUALITY_PREFERENCE",
    "AUDIO_LANGUAGE_PREFERENCE", "EXCLUDE_LANGUAGES",
    "FILTER_RULES_MIGRATED",
}


def fields_by_key() -> dict[str, dict]:
    return {f["key"]: f for s in SECTIONS for f in s["fields"]}


# The pre-schema groups payload. FilterRules.tsx and app.py's wizard save
# read this shape, so it is derived here rather than removed.
SETTING_GROUPS = [
    {"id": s["id"], "title": s["title"], "keys": [f["key"] for f in s["fields"] if f["kind"] != "custom"]}
    for s in SECTIONS
] + [{
    "id": "filter_rules",
    "title": "Filtering rules",
    "keys": [k for k in _RULE_LIST_KEYS] + sorted(_RULE_STRICT_KEYS),
}]
```

- [ ] **Step 6: Add `schema_for_ui()` at the end of `settings.py`**

```python
def _resolve_options(field: dict) -> list[dict] | None:
    opts = field["options"]
    if opts is None:
        return None
    if isinstance(opts, str):
        return _OPTION_RESOLVERS[opts]()
    return [o if isinstance(o, dict) else {"value": o, "label": o} for o in opts]


def schema_for_ui() -> list[dict]:
    """SECTIONS with each field's current value, whether a DB override
    exists, whether it hot-reloads, and options resolved. A secret's value is
    reported as True/False (set or not), never the secret itself."""
    overrides = db.get_all_settings()
    out = []
    for section in SECTIONS:
        fields = []
        for f in section["fields"]:
            item = dict(f)
            item["options"] = _resolve_options(f)
            if f["kind"] == "custom":
                item.update({"value": None, "overridden": False, "hot_reload": True})
            else:
                current = get(f["key"])
                item["value"] = bool(current) if f["kind"] == "secret" else current
                item["overridden"] = overrides.get(f["key"]) is not None
                item["hot_reload"] = f["key"] in HOT_RELOAD
            fields.append(item)
        out.append({"id": section["id"], "title": section["title"], "description": section["description"],
                    "icon": section["icon"], "fields": fields})
    return out
```

- [ ] **Step 7: Add the route in `app.py`**

Directly after the `ui_api_settings` route (around line 2059):

```python
@app.get("/ui/api/settings/schema")
def ui_api_settings_schema():
    """The schema-driven Settings page: sections, fields, copy, values."""
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import settings
    return jsonify(sections=settings.schema_for_ui(), hot_reload=list(settings.HOT_RELOAD))
```

- [ ] **Step 8: Run the new tests and the whole suite**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/test_settings_schema.py tests/test_filter_rules.py tests/test_filter_rules_ui.py tests/test_settings_enum.py tests/test_arr_sync.py -q -p no:cacheprovider`
Expected: all pass. Then the full suite: 821 plus the new tests, all green. If `tests/test_filter_rules_ui.py` asserts a key is not shown that the schema now lists (the retired keys), it stays satisfied because `_UNLISTED_KEYS` keeps them out.

- [ ] **Step 9: Mutation check**

Remove `"label": label` from `_f()`'s return dict: `test_every_field_has_exactly_the_declared_keys` must fail. Restore. Change `_UNLISTED_KEYS` to an empty set: `test_every_typed_key_is_listed_once_or_deliberately_unlisted` must fail. Restore. Delete `__pycache__`.

- [ ] **Step 10: Commit**

```bash
git add settings.py config.py app.py tests/test_settings_schema.py
git commit -m "feat(settings): declarative field schema with labels, help, kinds and dependencies

Claude-Session: https://claude.ai/code/session_01EZbQf8PvzNCADFo6bW74ko"
```

---

### Task 2: Service tests and pickers

**Files:**
- Create: `service_tests.py`
- Modify: `radarr.py`, `sonarr.py` (add `quality_profiles()` after `root_folders()`)
- Modify: `arr_sync.py` `_defaults()` (lines 69 to 89)
- Modify: `app.py`: replace the body of `setup_test()` (lines 851 to 975) with a registry call; replace `_arr_test`, `ui_api_arr_import_test_*`, `ui_api_arr_import_root_folders` (lines 3436 to 3474) with aliases; add the two new routes; scheduler reads the two interval keys through settings (lines 298 and 320)
- Test: `tests/test_service_tests.py` (new); extend `tests/test_arr_sync.py`

**Interfaces:**
- Consumes: `settings.fields_by_key()` (Task 1) to check every `test` and `picker` name is registered.
- Produces: `service_tests.TESTS: dict[str, Callable[[dict], dict]]` (services: torbox, realdebrid, tmdb, zilean, zilean_pg, debridio, jellyfin, seerr, radarr, sonarr, trakt, opensubtitles, discord, telegram, oidc); `service_tests.run(service, values) -> {"ok": bool, "message": str}` (never raises; unknown service raises `KeyError`); `service_tests.PICKERS` (radarr_root_folders, sonarr_root_folders, radarr_quality_profiles, sonarr_quality_profiles); `service_tests.pick(name, values) -> {"ok": True, "options": [{"value","label"}]} | {"ok": False, "error": str}`; `radarr.quality_profiles(url, key) -> [{"id": int, "name": str}]`; routes `POST /ui/api/settings/test/<service>` and `POST /ui/api/settings/picker/<name>` taking JSON `{"values": {KEY: value}}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_service_tests.py`:

```python
"""One tester per credentialed service and one picker per remote list,
shared by the Settings page and the setup wizard.
"""
import os
import re
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

sys.modules.pop("settings", None)

import pytest
import requests

import db
import service_tests
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


class FakeResp:
    def __init__(self, status, body=None, ctype="application/json"):
        self.status_code = status
        self._body = body if body is not None else {}
        self.headers = {"content-type": ctype}
        self.text = str(body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


@pytest.fixture
def http(monkeypatch):
    """Fakes service_tests' HTTP seam: routes a URL substring to a response
    and records every call. Nothing reaches the network."""
    calls = []
    routes = {}

    def fake(method, url, **kw):
        calls.append((method, url, kw))
        for needle, resp in routes.items():
            if needle in url:
                return resp() if callable(resp) else resp
        return FakeResp(404)

    monkeypatch.setattr(service_tests, "_http", fake)
    return routes, calls


def test_every_schema_test_and_picker_name_is_registered():
    for f in settings.fields_by_key().values():
        if f["test"]:
            assert f["test"] in service_tests.TESTS, f["key"]
        if f["picker"]:
            assert f["picker"] in service_tests.PICKERS, f["key"]


def test_torbox_reports_ok_and_never_echoes_the_key(http):
    routes, calls = http
    routes["/torrents/mylist"] = FakeResp(200, {"data": []})
    out = service_tests.run("torbox", {"TORBOX_API_KEY": "secret-key"})
    assert out["ok"] is True and "secret-key" not in out["message"]
    assert calls[0][2]["headers"]["Authorization"] == "Bearer secret-key"


def test_a_blank_value_falls_back_to_the_saved_setting(http):
    routes, calls = http
    settings.set("TORBOX_API_KEY", "saved-key")
    routes["/torrents/mylist"] = FakeResp(200, {"data": []})
    service_tests.run("torbox", {"TORBOX_API_KEY": ""})
    assert calls[0][2]["headers"]["Authorization"] == "Bearer saved-key"


def test_a_missing_credential_is_reported_without_a_request(http, monkeypatch):
    routes, calls = http
    import config
    monkeypatch.setattr(config, "TORBOX_API_KEY", "")
    settings.set("TORBOX_API_KEY", None)
    out = service_tests.run("torbox", {})
    assert out["ok"] is False and "key" in out["message"].lower() and calls == []


def test_a_timeout_reads_as_timed_out(http):
    routes, _ = http
    routes["/System/Info/Public"] = lambda: (_ for _ in ()).throw(requests.Timeout())
    out = service_tests.run("jellyfin", {"JELLYFIN_URL": "http://jf.test"})
    assert out == {"ok": False, "message": "timed out after 8 s"}


def test_realdebrid_reports_the_user(http):
    routes, calls = http
    routes["/user"] = FakeResp(200, {"username": "adam", "type": "premium", "expiration": "2027-01-01T00:00:00.000Z"})
    out = service_tests.run("realdebrid", {"REALDEBRID_API_KEY": "rd"})
    assert out["ok"] and "adam" in out["message"] and "2027-01-01" in out["message"]
    assert calls[0][2]["headers"]["Authorization"] == "Bearer rd"


def test_tmdb_accepts_and_rejects(http):
    routes, _ = http
    routes["/configuration"] = FakeResp(200, {"images": {}})
    assert service_tests.run("tmdb", {"TMDB_API_KEY": "k"})["ok"] is True
    routes["/configuration"] = FakeResp(401, {"status_message": "Invalid API key"})
    out = service_tests.run("tmdb", {"TMDB_API_KEY": "k"})
    assert out["ok"] is False and "401" in out["message"]


def test_oidc_reads_the_discovery_document(http):
    routes, calls = http
    routes["/.well-known/openid-configuration"] = FakeResp(200, {
        "issuer": "https://auth.test/app/o/mycelium/",
        "authorization_endpoint": "https://auth.test/authorize",
        "token_endpoint": "https://auth.test/token",
    })
    out = service_tests.run("oidc", {"OIDC_ISSUER_URL": "https://auth.test/app/o/mycelium/"})
    assert out["ok"] and "auth.test" in out["message"] and "token" in out["message"]
    assert calls[0][1] == "https://auth.test/app/o/mycelium/.well-known/openid-configuration"
    routes["/.well-known/openid-configuration"] = FakeResp(200, {"issuer": "x"})
    out = service_tests.run("oidc", {"OIDC_ISSUER_URL": "https://auth.test/app/o/mycelium/"})
    assert out["ok"] is False and "authorization" in out["message"]


def test_zilean_pg_connects_and_reports_the_version(monkeypatch):
    class Cur:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def execute(self, q): self.q = q
        def fetchone(self): return ("PostgreSQL 16.2 on x86_64",)

    class Conn:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def cursor(self): return Cur()

    seen = {}

    def connect(**kw):
        seen.update(kw)
        return Conn()

    monkeypatch.setattr(service_tests, "_pg_connect", connect)
    out = service_tests.run("zilean_pg", {"ZILEAN_PG_HOST": "pg", "ZILEAN_PG_PORT": "5433", "ZILEAN_PG_DB": "z",
                                          "ZILEAN_PG_USER": "u", "ZILEAN_PG_PASSWORD": "p"})
    assert out["ok"] and "16.2" in out["message"]
    assert seen["host"] == "pg" and seen["port"] == 5433 and seen["connect_timeout"] == 8
    monkeypatch.setattr(service_tests, "_pg_connect", lambda **kw: (_ for _ in ()).throw(RuntimeError("refused")))
    out = service_tests.run("zilean_pg", {"ZILEAN_PG_HOST": "pg"})
    assert out["ok"] is False and "refused" in out["message"]


def test_debridio_fetches_the_manifest_with_the_typed_key(http, monkeypatch):
    routes, calls = http
    routes["/manifest.json"] = FakeResp(200, {"name": "Debridio", "version": "1.2.3"})
    out = service_tests.run("debridio", {"DEBRIDIO_API_KEY": "dk"})
    assert out["ok"] and "Debridio" in out["message"] and "1.2.3" in out["message"]
    assert "dk" not in out["message"]


def test_radarr_reports_version_and_count(http):
    routes, _ = http
    routes["/api/v3/system/status"] = FakeResp(200, {"version": "5.2.0"})
    routes["/api/v3/movie"] = FakeResp(200, [{"id": 1}, {"id": 2}])
    out = service_tests.run("radarr", {"RADARR_URL": "http://r.test", "RADARR_API_KEY": "k"})
    assert out == {"ok": True, "message": "Radarr 5.2.0, 2 movies"}


def test_unknown_service_is_a_key_error():
    with pytest.raises(KeyError):
        service_tests.run("nope", {})


def test_the_wizard_kinds_all_exist():
    for kind in ("torbox", "jellyfin", "seerr", "discord", "telegram", "trakt", "opensubtitles", "zilean", "radarr", "sonarr"):
        assert kind in service_tests.TESTS


def test_root_folder_picker_lists_paths_with_free_space(http):
    routes, _ = http
    routes["/api/v3/rootfolder"] = FakeResp(200, [{"path": "/movies", "freeSpace": 5 * 1024 ** 3}, {"path": "/more", "freeSpace": None}])
    out = service_tests.pick("radarr_root_folders", {"RADARR_URL": "http://r.test", "RADARR_API_KEY": "k"})
    assert out == {"ok": True, "options": [{"value": "/movies", "label": "/movies (5 GB free)"}, {"value": "/more", "label": "/more"}]}


def test_quality_profile_picker_lists_names(http):
    routes, _ = http
    routes["/api/v3/qualityprofile"] = FakeResp(200, [{"id": 1, "name": "HD-1080p"}, {"id": 6, "name": "Ultra-HD"}])
    out = service_tests.pick("sonarr_quality_profiles", {"SONARR_URL": "http://s.test", "SONARR_API_KEY": "k"})
    assert out == {"ok": True, "options": [{"value": "HD-1080p", "label": "HD-1080p"}, {"value": "Ultra-HD", "label": "Ultra-HD"}]}


def test_a_picker_failure_is_an_error_not_an_empty_list(http):
    routes, _ = http
    routes["/api/v3/rootfolder"] = FakeResp(401)
    out = service_tests.pick("radarr_root_folders", {"RADARR_URL": "http://r.test", "RADARR_API_KEY": "bad"})
    assert out["ok"] is False and out["error"]
    assert service_tests.pick("radarr_root_folders", {})["ok"] is False


def test_the_routes_exist_and_the_wizard_and_arr_import_use_the_registry():
    src = _src("app.py")
    assert re.search(r'@app\.post\("/ui/api/settings/test/<service>"\)', src)
    assert re.search(r'@app\.post\("/ui/api/settings/picker/<name>"\)', src)
    wizard = src.split('@app.post("/setup/test/<kind>")', 1)[1].split("\n\n\n", 1)[0]
    assert "service_tests.run(kind" in wizard and '__import__("requests")' not in wizard
    arr = src.split('/ui/api/arr-import/test-radarr', 1)[1][:2000]
    assert "service_tests" in arr
    assert "def _arr_test" not in src
    assert '_settings_mod.get("ARR_SYNC_INTERVAL_MINUTES"' in src
    assert '_settings_mod.get("DISK_SYNC_INTERVAL_MINUTES"' in src
```

Append to `tests/test_arr_sync.py` (before the wiring section rule):

```python
def test_a_quality_profile_setting_is_matched_by_name(enabled, monkeypatch):
    import arr_sync
    enabled["RADARR_QUALITY_PROFILE"] = "Ultra-HD"
    fake = FakeArr({
        ("GET", "/qualityprofile"): (200, [{"id": 1, "name": "HD-1080p"}, {"id": 6, "name": "Ultra-HD"}]),
        ("GET", "/rootfolder"): (200, [{"path": "/movies"}]),
    })
    monkeypatch.setattr(arr_sync, "_request", fake)
    assert arr_sync._defaults("radarr", "http://radarr.test", "k") == (6, "/movies")


def test_an_unknown_profile_name_falls_back_to_the_first_with_a_warning(enabled, monkeypatch, caplog):
    import arr_sync
    enabled["RADARR_QUALITY_PROFILE"] = "Gone"
    fake = FakeArr({
        ("GET", "/qualityprofile"): (200, [{"id": 1, "name": "HD-1080p"}]),
        ("GET", "/rootfolder"): (200, [{"path": "/movies"}]),
    })
    monkeypatch.setattr(arr_sync, "_request", fake)
    with caplog.at_level("WARNING"):
        assert arr_sync._defaults("radarr", "http://radarr.test", "k") == (1, "/movies")
    assert any("Gone" in r.message for r in caplog.records)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/test_service_tests.py tests/test_arr_sync.py -q -p no:cacheprovider`
Expected: `ModuleNotFoundError: No module named 'service_tests'`, and the two arr_sync tests fail on the profile id.

- [ ] **Step 3: Add `quality_profiles()` to `radarr.py` and `sonarr.py`**

After `root_folders()` in each file (identical code in both):

```python
def quality_profiles(url: str, api_key: str, timeout: int = 8) -> list[dict]:
    """[{"id", "name"}] from /api/v3/qualityprofile. Raises on a bad key
    or an unreachable host so the caller can show the reason."""
    resp = requests.get(f"{url.rstrip('/')}/api/v3/qualityprofile",
                        headers=_headers(api_key), timeout=timeout)
    resp.raise_for_status()
    return [{"id": p.get("id"), "name": p.get("name")}
            for p in (resp.json() or []) if p.get("id") is not None and p.get("name")]
```

- [ ] **Step 4: Honour the profile setting in `arr_sync._defaults()`**

Replace the function body's cache key and profile choice:

```python
def _defaults(kind: str, base: str, key: str) -> tuple[int, str]:
    """Quality profile (setting by name, else the first) and root folder
    (setting, else the first)."""
    root_setting = (_settings.get(f"{kind.upper()}_ROOT_FOLDER", "") or "").strip()
    profile_setting = (_settings.get(f"{kind.upper()}_QUALITY_PROFILE", "") or "").strip()
    cache_key = (kind, base, root_setting, profile_setting)
    with _lock:
        if cache_key in _defaults_cache:
            return _defaults_cache[cache_key]
    status, profiles = _request("GET", f"{base}/api/v3/qualityprofile", key)
    if status != 200 or not profiles:
        raise ArrError(f"{kind}: no quality profiles ({status})")
    profile_id = int(profiles[0]["id"])
    if profile_setting:
        match = next((p for p in profiles if p.get("name") == profile_setting), None)
        if match:
            profile_id = int(match["id"])
        else:
            log.warning("Arr sync: %s has no quality profile named %r; using %r",
                        kind, profile_setting, profiles[0].get("name"))
    root = root_setting
    if not root:
        status, roots = _request("GET", f"{base}/api/v3/rootfolder", key)
        if status != 200 or not roots:
            raise ArrError(f"{kind}: no root folders ({status})")
        root = roots[0]["path"]
    out = (profile_id, root)
    with _lock:
        _defaults_cache[cache_key] = out
    return out
```

- [ ] **Step 5: Write `service_tests.py`**

```python
"""One tester per credentialed service and one picker per remote list.

Both the Settings page (POST /ui/api/settings/test/<service>, with the
values as typed) and the setup wizard (POST /setup/test/<kind>) call
run(); the pickers feed the root folder and quality profile dropdowns.
Every function takes the field values as a dict; a blank value falls back
to the saved setting so an untouched secret box still works. Messages
never contain a credential. Nothing here raises past run() or pick().
"""
from __future__ import annotations

import logging

import requests

import config
import settings as _settings

log = logging.getLogger(__name__)

TIMEOUT = 8


def _http(method: str, url: str, **kw):
    """The one HTTP seam; tests replace it."""
    kw.setdefault("timeout", TIMEOUT)
    return requests.request(method, url, **kw)


def _pg_connect(**kw):
    import psycopg2
    return psycopg2.connect(**kw)


def _v(values: dict, key: str) -> str:
    typed = str(values.get(key) or "").strip()
    if typed:
        return typed
    saved = _settings.get(key, getattr(config, key, ""))
    return str(saved or "").strip()


def _need(values: dict, *keys: str) -> str | None:
    """Name of the first blank required field, or None."""
    for k in keys:
        if not _v(values, k):
            return k.replace("_", " ").lower()
    return None


def _status(r) -> str:
    return f"HTTP {r.status_code}"


def _json(r) -> dict:
    try:
        body = r.json()
        return body if isinstance(body, dict) else {}
    except ValueError:
        return {}


def test_torbox(v: dict) -> dict:
    if (m := _need(v, "TORBOX_API_KEY")):
        return {"ok": False, "message": f"{m} is empty"}
    base = (_v(v, "TORBOX_BASE_URL") or config.TORBOX_BASE_URL).rstrip("/")
    r = _http("GET", f"{base}/torrents/mylist", headers={"Authorization": f"Bearer {_v(v, 'TORBOX_API_KEY')}"})
    if r.status_code < 400:
        n = len((_json(r).get("data") or []))
        return {"ok": True, "message": f"TorBox key accepted, {n} torrents in your library"}
    return {"ok": False, "message": f"TorBox refused the key ({_status(r)})"}


def test_realdebrid(v: dict) -> dict:
    if (m := _need(v, "REALDEBRID_API_KEY")):
        return {"ok": False, "message": f"{m} is empty"}
    r = _http("GET", "https://api.real-debrid.com/rest/1.0/user",
              headers={"Authorization": f"Bearer {_v(v, 'REALDEBRID_API_KEY')}"})
    if r.status_code < 400:
        d = _json(r)
        return {"ok": True, "message": f"{d.get('username', 'user')}, {d.get('type', '')} until {str(d.get('expiration', ''))[:10]}".strip()}
    return {"ok": False, "message": f"RealDebrid refused the token ({_status(r)})"}


def test_tmdb(v: dict) -> dict:
    if (m := _need(v, "TMDB_API_KEY")):
        return {"ok": False, "message": f"{m} is empty"}
    r = _http("GET", "https://api.themoviedb.org/3/configuration",
              headers={"Authorization": f"Bearer {_v(v, 'TMDB_API_KEY')}", "Accept": "application/json"})
    if r.status_code < 400:
        return {"ok": True, "message": "TMDB key accepted"}
    return {"ok": False, "message": f"TMDB refused the key ({_status(r)})"}


def test_zilean(v: dict) -> dict:
    if (m := _need(v, "ZILEAN_URL")):
        return {"ok": False, "message": f"{m} is empty"}
    r = _http("GET", f"{_v(v, 'ZILEAN_URL').rstrip('/')}/healthcheck")
    return {"ok": r.status_code < 400, "message": f"Zilean answered {_status(r)}"}


def test_zilean_pg(v: dict) -> dict:
    if (m := _need(v, "ZILEAN_PG_HOST")):
        return {"ok": False, "message": f"{m} is empty"}
    try:
        port = int(_v(v, "ZILEAN_PG_PORT") or 5432)
    except ValueError:
        return {"ok": False, "message": "postgres port is not a number"}
    try:
        with _pg_connect(host=_v(v, "ZILEAN_PG_HOST"), port=port, dbname=_v(v, "ZILEAN_PG_DB") or "zilean",
                         user=_v(v, "ZILEAN_PG_USER") or "postgres", password=_v(v, "ZILEAN_PG_PASSWORD"),
                         connect_timeout=TIMEOUT) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                version = (cur.fetchone() or [""])[0]
        return {"ok": True, "message": str(version).split(" on ")[0] or "connected"}
    except Exception as exc:
        return {"ok": False, "message": f"could not connect: {str(exc).strip()[:120]}"}


def test_debridio(v: dict) -> dict:
    import base64
    import json
    if (m := _need(v, "DEBRIDIO_API_KEY")):
        return {"ok": False, "message": f"{m} is empty"}
    base = (_v(v, "DEBRIDIO_BASE_URL") or config.DEBRIDIO_BASE_URL).rstrip("/")
    token = base64.urlsafe_b64encode(json.dumps({"api_key": _v(v, "DEBRIDIO_API_KEY"), "provider": "torbox"}).encode()).decode().rstrip("=")
    r = _http("GET", f"{base}/{token}/manifest.json")
    if r.status_code < 400:
        d = _json(r)
        return {"ok": True, "message": f"{d.get('name', 'Debridio')} {d.get('version', '')}".strip()}
    return {"ok": False, "message": f"Debridio refused the key ({_status(r)})"}


def test_jellyfin(v: dict) -> dict:
    if (m := _need(v, "JELLYFIN_URL")):
        return {"ok": False, "message": f"{m} is empty"}
    key = _v(v, "JELLYFIN_API_KEY")
    r = _http("GET", f"{_v(v, 'JELLYFIN_URL').rstrip('/')}/System/Info/Public", headers={"X-Emby-Token": key} if key else {})
    if r.status_code < 400:
        d = _json(r)
        return {"ok": True, "message": f"{d.get('ServerName', 'Jellyfin')} {d.get('Version', '')}".strip()}
    return {"ok": False, "message": f"Jellyfin answered {_status(r)}"}


def test_seerr(v: dict) -> dict:
    if (m := _need(v, "SEERR_URL")):
        return {"ok": False, "message": f"{m} is empty"}
    key = _v(v, "SEERR_API_KEY")
    r = _http("GET", f"{_v(v, 'SEERR_URL').rstrip('/')}/api/v1/status", headers={"X-Api-Key": key} if key else {})
    if r.status_code < 400:
        return {"ok": True, "message": f"Seerr {_json(r).get('version', '')}".strip()}
    return {"ok": False, "message": f"Seerr answered {_status(r)}"}


def _test_arr(kind: str, v: dict) -> dict:
    p = kind.upper()
    name = kind.capitalize()
    if (m := _need(v, f"{p}_URL", f"{p}_API_KEY")):
        return {"ok": False, "message": f"{m} is empty"}
    base, headers = _v(v, f"{p}_URL").rstrip("/"), {"X-Api-Key": _v(v, f"{p}_API_KEY")}
    r = _http("GET", f"{base}/api/v3/system/status", headers=headers)
    if r.status_code >= 400:
        return {"ok": False, "message": f"{name} refused the API key ({_status(r)})"}
    version = _json(r).get("version", "")
    resource, noun = ("movie", "movies") if kind == "radarr" else ("series", "series")
    listing = _http("GET", f"{base}/api/v3/{resource}", headers=headers)
    count = len(listing.json() or []) if listing.status_code < 400 else 0
    return {"ok": True, "message": f"{name} {version}, {count} {noun}"}


def test_radarr(v: dict) -> dict:
    return _test_arr("radarr", v)


def test_sonarr(v: dict) -> dict:
    return _test_arr("sonarr", v)


def test_trakt(v: dict) -> dict:
    if (m := _need(v, "TRAKT_CLIENT_ID")):
        return {"ok": False, "message": f"{m} is empty"}
    r = _http("GET", "https://api.trakt.tv/movies/trending",
              headers={"trakt-api-key": _v(v, "TRAKT_CLIENT_ID"), "trakt-api-version": "2"})
    return {"ok": r.status_code < 400, "message": "Trakt client id accepted" if r.status_code < 400 else f"Trakt refused the client id ({_status(r)})"}


def test_opensubtitles(v: dict) -> dict:
    if (m := _need(v, "OPENSUBTITLES_API_KEY")):
        return {"ok": False, "message": f"{m} is empty"}
    r = _http("GET", "https://api.opensubtitles.com/api/v1/infos/user",
              headers={"Api-Key": _v(v, "OPENSUBTITLES_API_KEY"), "Content-Type": "application/json"})
    if r.status_code == 200:
        remaining = (_json(r).get("data") or {}).get("remaining_downloads", "?")
        return {"ok": True, "message": f"{remaining} downloads remaining today"}
    return {"ok": False, "message": f"OpenSubtitles refused the key ({_status(r)})"}


def test_discord(v: dict) -> dict:
    if (m := _need(v, "DISCORD_WEBHOOK_URL")):
        return {"ok": False, "message": f"{m} is empty"}
    r = _http("POST", _v(v, "DISCORD_WEBHOOK_URL"), json={"content": "Mycelium test message"})
    return {"ok": r.status_code < 400, "message": "test message sent" if r.status_code < 400 else f"Discord answered {_status(r)}"}


def test_telegram(v: dict) -> dict:
    if (m := _need(v, "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")):
        return {"ok": False, "message": f"{m} is empty"}
    r = _http("POST", f"https://api.telegram.org/bot{_v(v, 'TELEGRAM_BOT_TOKEN')}/sendMessage",
              json={"chat_id": _v(v, "TELEGRAM_CHAT_ID"), "text": "Mycelium test message"})
    return {"ok": r.status_code < 400, "message": "test message sent" if r.status_code < 400 else f"Telegram answered {_status(r)}"}


def test_oidc(v: dict) -> dict:
    if (m := _need(v, "OIDC_ISSUER_URL")):
        return {"ok": False, "message": f"{m} is empty"}
    r = _http("GET", f"{_v(v, 'OIDC_ISSUER_URL').rstrip('/')}/.well-known/openid-configuration")
    if r.status_code >= 400:
        return {"ok": False, "message": f"discovery document not found ({_status(r)})"}
    d = _json(r)
    missing = [k for k in ("authorization_endpoint", "token_endpoint") if not d.get(k)]
    if missing:
        return {"ok": False, "message": f"discovery document lacks {', '.join(missing)}"}
    return {"ok": True, "message": f"issuer {d.get('issuer', '')}, authorization and token endpoints found"}


TESTS = {
    "torbox": test_torbox, "realdebrid": test_realdebrid, "tmdb": test_tmdb,
    "zilean": test_zilean, "zilean_pg": test_zilean_pg, "debridio": test_debridio,
    "jellyfin": test_jellyfin, "seerr": test_seerr, "radarr": test_radarr, "sonarr": test_sonarr,
    "trakt": test_trakt, "opensubtitles": test_opensubtitles,
    "discord": test_discord, "telegram": test_telegram, "oidc": test_oidc,
}


def run(service: str, values: dict) -> dict:
    """{ok, message}. KeyError for an unknown service; everything else is
    caught and reported, never logged with the values."""
    fn = TESTS[service]
    try:
        return fn(dict(values or {}))
    except requests.Timeout:
        return {"ok": False, "message": f"timed out after {TIMEOUT} s"}
    except requests.RequestException as exc:
        return {"ok": False, "message": f"could not connect: {exc.__class__.__name__}"}
    except Exception as exc:
        log.warning("Service test %s failed: %s", service, exc.__class__.__name__)
        return {"ok": False, "message": f"test failed: {exc.__class__.__name__}"}


def _free(bytes_: int | None) -> str:
    if bytes_ is None:
        return ""
    gb = bytes_ / 1024 ** 3
    return f" ({gb / 1024:.1f} TB free)" if gb >= 1024 else f" ({round(gb)} GB free)"


def _pick_root_folders(kind: str, v: dict) -> list[dict]:
    p = kind.upper()
    r = _http("GET", f"{_v(v, f'{p}_URL').rstrip('/')}/api/v3/rootfolder", headers={"X-Api-Key": _v(v, f"{p}_API_KEY")})
    r.raise_for_status()
    return [{"value": f["path"], "label": f"{f['path']}{_free(f.get('freeSpace'))}"} for f in (r.json() or []) if f.get("path")]


def _pick_quality_profiles(kind: str, v: dict) -> list[dict]:
    p = kind.upper()
    r = _http("GET", f"{_v(v, f'{p}_URL').rstrip('/')}/api/v3/qualityprofile", headers={"X-Api-Key": _v(v, f"{p}_API_KEY")})
    r.raise_for_status()
    return [{"value": q["name"], "label": q["name"]} for q in (r.json() or []) if q.get("name")]


PICKERS = {
    "radarr_root_folders": lambda v: _pick_root_folders("radarr", v),
    "sonarr_root_folders": lambda v: _pick_root_folders("sonarr", v),
    "radarr_quality_profiles": lambda v: _pick_quality_profiles("radarr", v),
    "sonarr_quality_profiles": lambda v: _pick_quality_profiles("sonarr", v),
}


def pick(name: str, values: dict) -> dict:
    """{ok: True, options} or {ok: False, error}. KeyError for an unknown picker."""
    fn = PICKERS[name]
    kind = name.split("_", 1)[0]
    p = kind.upper()
    v = dict(values or {})
    if (m := _need(v, f"{p}_URL", f"{p}_API_KEY")):
        return {"ok": False, "error": f"{m} is empty"}
    try:
        return {"ok": True, "options": fn(v)}
    except requests.Timeout:
        return {"ok": False, "error": f"timed out after {TIMEOUT} s"}
    except Exception as exc:
        log.warning("Picker %s failed: %s", name, exc.__class__.__name__)
        return {"ok": False, "error": f"{kind.capitalize()} did not answer, or refused the API key"}
```

Note: `service_tests` imports `settings`, which imports `db`; the tests' `_isolated_db` fixture covers that. Radarr/Sonarr still keep their own `system_status()` for `health.py`.

- [ ] **Step 6: Rewire `app.py`**

Replace the whole body of `setup_test()` after the auth check (from `f = request.form` through the final `return jsonify(ok=False, error=...)` of that function) with:

```python
    import service_tests
    if kind not in service_tests.TESTS:
        return jsonify(ok=False, error="unknown integration"), 404
    r = service_tests.run(kind, dict(request.form))
    if r["ok"]:
        return jsonify(ok=True, detail=r["message"])
    return jsonify(ok=False, error=r["message"])
```

Replace `_arr_test`, both `ui_api_arr_import_test_*` routes and `ui_api_arr_import_root_folders` (keep `_arr_conn`, other routes use it) with:

```python
def _arr_values(kind: str) -> dict:
    """The old arr-import body {url, api_key} as schema values."""
    p = request.get_json(silent=True) or {}
    prefix = kind.upper()
    return {f"{prefix}_URL": p.get("url") or "", f"{prefix}_API_KEY": p.get("api_key") or ""}


@app.post("/ui/api/arr-import/test-radarr")
def ui_api_arr_import_test_radarr():
    """Alias kept for one release; the Settings page uses /ui/api/settings/test/radarr."""
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import service_tests
    r = service_tests.run("radarr", _arr_values("radarr"))
    return jsonify(ok=r["ok"], version=r["message"] if r["ok"] else None, error=None if r["ok"] else r["message"])


@app.post("/ui/api/arr-import/test-sonarr")
def ui_api_arr_import_test_sonarr():
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import service_tests
    r = service_tests.run("sonarr", _arr_values("sonarr"))
    return jsonify(ok=r["ok"], version=r["message"] if r["ok"] else None, error=None if r["ok"] else r["message"])


@app.post("/ui/api/arr-import/root-folders-<kind>")
def ui_api_arr_import_root_folders(kind: str):
    """Alias kept for one release; the Settings page uses /ui/api/settings/picker/<kind>_root_folders."""
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    if kind not in ("radarr", "sonarr"):
        return jsonify(error="unknown arr"), 404
    import service_tests
    r = service_tests.pick(f"{kind}_root_folders", _arr_values(kind))
    if not r["ok"]:
        return jsonify(ok=False, error=r["error"])
    return jsonify(ok=True, folders=[{"path": o["value"], "free_space": None} for o in r["options"]])


@app.post("/ui/api/settings/test/<service>")
@limiter.limit("30 per minute")
def ui_api_settings_test(service: str):
    """Test one integration with the values as typed on the Settings page.
    Body: {"values": {KEY: value}}. Blank values fall back to saved ones."""
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import service_tests
    if service not in service_tests.TESTS:
        return jsonify(ok=False, message="unknown service"), 404
    p = request.get_json(silent=True) or {}
    return jsonify(**service_tests.run(service, p.get("values") or {}))


@app.post("/ui/api/settings/picker/<name>")
@limiter.limit("30 per minute")
def ui_api_settings_picker(name: str):
    """Options for a field whose values come from a service, for example
    Radarr's root folders. Body: {"values": {KEY: value}}."""
    if not auth.is_admin():
        return jsonify(error="admin required"), 403
    import service_tests
    if name not in service_tests.PICKERS:
        return jsonify(ok=False, error="unknown picker"), 404
    p = request.get_json(silent=True) or {}
    return jsonify(**service_tests.pick(name, p.get("values") or {}))
```

Scheduler: in the block starting `import arr_sync` replace `from config import ARR_SYNC_INTERVAL_MINUTES` and the constant's uses with `ARR_SYNC_INTERVAL_MINUTES = int(_settings_mod.get("ARR_SYNC_INTERVAL_MINUTES", cfg.ARR_SYNC_INTERVAL_MINUTES) or 0)`; same for `DISK_SYNC_INTERVAL_MINUTES` in the `import disk_sync` block. (`_settings_mod` and `cfg` are the module aliases already imported at the top of `app.py`.)

- [ ] **Step 7: Run the tests and the suite**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/test_service_tests.py tests/test_arr_sync.py tests/test_arr_settings_tools.py -q -p no:cacheprovider`, then the full suite. Expected: green. `tests/test_arr_settings_tools.py` checks the old routes on source text; if an assertion there names `system_status` inside `_arr_test`, update that test to assert the alias goes through `service_tests` instead, and say so in the report.

- [ ] **Step 8: Mutation check**

In `run()`, replace `except requests.Timeout:` with `except ValueError:`: `test_a_timeout_reads_as_timed_out` must fail. Restore. In `pick()`, return `{"ok": True, "options": []}` from the generic `except`: `test_a_picker_failure_is_an_error_not_an_empty_list` must fail. Restore. Delete `__pycache__`.

- [ ] **Step 9: Commit**

```bash
git add service_tests.py radarr.py sonarr.py arr_sync.py app.py tests/test_service_tests.py tests/test_arr_sync.py tests/test_arr_settings_tools.py
git commit -m "feat(settings): one tester per service and pickers for arr folders and profiles

Claude-Session: https://claude.ai/code/session_01EZbQf8PvzNCADFo6bW74ko"
```

---

### Task 3: Primitives `Button`, `Select`, `MultiSelect`, `OrderedList`

**Files:**
- Create: `frontend/src/components/primitives/Button.tsx`, `Select.tsx`, `MultiSelect.tsx`, `OrderedList.tsx`
- Modify: `frontend/src/components/primitives/index.ts` (export them)
- Test: `frontend/src/components/primitives/controls.test.tsx` (new)

**Interfaces:**
- Produces:
  - `Button({ variant?: 'default'|'primary'|'ghost', loading?: boolean, children, ...buttonProps })`: renders `<button type="button">`, `disabled` while loading, shows `loadingLabel` (default "Working...") while loading.
  - `Select({ value, onChange(next: string), options: {value,label}[], label, placeholder?, className? })`: a native `<select>` with `aria-label={label}`; `placeholder` renders as an option with value `''`.
  - `MultiSelect({ value: string[], onChange(next: string[]), options, label })`: chips for selected values (remove with the chip's x), a text input that filters `options` and adds on click or Enter.
  - `OrderedList({ value: string[], onChange(next: string[]), options, label })`: one row per value with up/down buttons (`aria-label="Move X up"`/`"Move X down"`) and remove; a `Select` of unused options with placeholder "Add..." appends.

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/primitives/controls.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { Button } from './Button';
import { Select } from './Select';
import { MultiSelect } from './MultiSelect';
import { OrderedList } from './OrderedList';

const OPTS = [
  { value: 'en', label: 'en' },
  { value: 'nl', label: 'nl' },
  { value: 'de', label: 'de' },
];

describe('Button', () => {
  it('is disabled and shows the loading label while loading', () => {
    render(<Button loading loadingLabel="Testing...">Test</Button>);
    const b = screen.getByRole('button');
    expect(b).toBeDisabled();
    expect(b).toHaveTextContent('Testing...');
  });
  it('never submits a form', () => {
    render(<Button>Go</Button>);
    expect(screen.getByRole('button')).toHaveAttribute('type', 'button');
  });
});

describe('Select', () => {
  it('offers the placeholder as the empty value and reports a pick', async () => {
    const onChange = vi.fn();
    render(<Select label="Region" value="" onChange={onChange} options={OPTS} placeholder="(first)" />);
    const s = screen.getByRole('combobox', { name: 'Region' });
    expect(s).toHaveValue('');
    await userEvent.selectOptions(s, 'nl');
    expect(onChange).toHaveBeenCalledWith('nl');
  });
});

describe('MultiSelect', () => {
  it('shows chips, filters by typing, adds on click and removes on x', async () => {
    const onChange = vi.fn();
    render(<MultiSelect label="Languages" value={['en']} onChange={onChange} options={OPTS} />);
    expect(screen.getByText('en')).toBeInTheDocument();
    await userEvent.type(screen.getByRole('textbox', { name: 'Languages' }), 'n');
    expect(screen.getByRole('option', { name: 'nl' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'de' })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('option', { name: 'nl' }));
    expect(onChange).toHaveBeenLastCalledWith(['en', 'nl']);
    await userEvent.click(screen.getByRole('button', { name: 'Remove en' }));
    expect(onChange).toHaveBeenLastCalledWith([]);
  });
});

describe('OrderedList', () => {
  it('moves an entry down and appends from the unused options', async () => {
    const onChange = vi.fn();
    render(<OrderedList label="Sort order" value={['en', 'nl']} onChange={onChange} options={OPTS} />);
    await userEvent.click(screen.getByRole('button', { name: 'Move en down' }));
    expect(onChange).toHaveBeenLastCalledWith(['nl', 'en']);
    await userEvent.selectOptions(screen.getByRole('combobox', { name: 'Add to Sort order' }), 'de');
    expect(onChange).toHaveBeenLastCalledWith(['en', 'nl', 'de']);
    expect(screen.getByRole('button', { name: 'Move en up' })).toBeDisabled();
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npx vitest run src/components/primitives/controls.test.tsx`
Expected: FAIL, cannot resolve `./Button`.

- [ ] **Step 3: Write the primitives**

`Button.tsx`:

```tsx
import type { ButtonHTMLAttributes } from 'react';

type Variant = 'default' | 'primary' | 'ghost';

const VARIANT: Record<Variant, string> = {
  default: 'border border-border bg-card-raised text-accent-light hover:bg-white/[0.06]',
  primary: 'bg-accent text-white hover:bg-accent-light',
  ghost: 'text-muted hover:text-body',
};

export function Button({
  variant = 'default',
  loading = false,
  loadingLabel = 'Working...',
  className = '',
  children,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean; loadingLabel?: string }) {
  return (
    <button
      type="button"
      disabled={disabled || loading}
      className={`rounded px-3 py-1.5 text-xs font-semibold transition disabled:opacity-50 ${VARIANT[variant]} ${className}`.trim()}
      {...rest}
    >
      {loading ? loadingLabel : children}
    </button>
  );
}
```

`Select.tsx`:

```tsx
export type Option = { value: string; label: string };

export function Select({
  value,
  onChange,
  options,
  label,
  placeholder,
  className = '',
}: {
  value: string;
  onChange: (next: string) => void;
  options: Option[];
  label: string;
  placeholder?: string;
  className?: string;
}) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={`rounded border border-border bg-bg px-2 py-1 text-xs ${className}`.trim()}
    >
      {placeholder !== undefined && <option value="">{placeholder}</option>}
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}
```

`MultiSelect.tsx`:

```tsx
import { useState } from 'react';
import { Chip } from './Chip';
import type { Option } from './Select';

export function MultiSelect({
  value,
  onChange,
  options,
  label,
}: {
  value: string[];
  onChange: (next: string[]) => void;
  options: Option[];
  label: string;
}) {
  const [query, setQuery] = useState('');
  const q = query.trim().toLowerCase();
  const candidates = options.filter(
    (o) => !value.includes(o.value) && (q === '' || o.label.toLowerCase().includes(q) || o.value.toLowerCase().includes(q)),
  );
  const add = (v: string) => {
    onChange([...value, v]);
    setQuery('');
  };
  return (
    <div className="w-full max-w-md">
      <div className="flex flex-wrap items-center gap-1.5 rounded border border-border bg-bg px-2 py-1">
        {value.map((v) => (
          <Chip key={v} label={options.find((o) => o.value === v)?.label ?? v} selected onRemove={() => onChange(value.filter((x) => x !== v))} />
        ))}
        <input
          type="text"
          aria-label={label}
          value={query}
          placeholder={value.length ? '' : 'Type to search'}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && candidates[0]) {
              e.preventDefault();
              add(candidates[0].value);
            }
          }}
          className="min-w-[6rem] flex-1 bg-transparent py-1 text-xs outline-none"
        />
      </div>
      {q !== '' && candidates.length > 0 && (
        <ul role="listbox" className="mt-1 max-h-40 overflow-auto rounded border border-border bg-card-raised text-xs">
          {candidates.slice(0, 20).map((o) => (
            <li key={o.value} role="option" aria-selected={false} onClick={() => add(o.value)} className="cursor-pointer px-2 py-1 hover:bg-white/[0.06]">
              {o.label}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

`OrderedList.tsx`:

```tsx
import { Button } from './Button';
import { Select } from './Select';
import type { Option } from './Select';

export function OrderedList({
  value,
  onChange,
  options,
  label,
}: {
  value: string[];
  onChange: (next: string[]) => void;
  options: Option[];
  label: string;
}) {
  const move = (i: number, d: -1 | 1) => {
    const next = [...value];
    const [item] = next.splice(i, 1);
    next.splice(i + d, 0, item);
    onChange(next);
  };
  const unused = options.filter((o) => !value.includes(o.value));
  const name = (v: string) => options.find((o) => o.value === v)?.label ?? v;
  return (
    <div className="w-full max-w-md space-y-1">
      <ol className="space-y-1">
        {value.map((v, i) => (
          <li key={v} className="flex items-center gap-2 rounded border border-border bg-bg px-2 py-1 text-xs">
            <span className="w-4 text-muted">{i + 1}</span>
            <span className="flex-1">{name(v)}</span>
            <Button variant="ghost" aria-label={`Move ${name(v)} up`} disabled={i === 0} onClick={() => move(i, -1)}>&uarr;</Button>
            <Button variant="ghost" aria-label={`Move ${name(v)} down`} disabled={i === value.length - 1} onClick={() => move(i, 1)}>&darr;</Button>
            <Button variant="ghost" aria-label={`Remove ${name(v)}`} onClick={() => onChange(value.filter((x) => x !== v))}>&times;</Button>
          </li>
        ))}
      </ol>
      {unused.length > 0 && (
        <Select label={`Add to ${label}`} value="" placeholder="Add..." options={unused} onChange={(v) => v && onChange([...value, v])} />
      )}
    </div>
  );
}
```

Add to `index.ts`:

```ts
export { Button } from './Button';
export { Select } from './Select';
export type { Option } from './Select';
export { MultiSelect } from './MultiSelect';
export { OrderedList } from './OrderedList';
```

- [ ] **Step 4: Run the tests and type-check**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/components/primitives/controls.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/primitives/
git commit -m "feat(ui): Button, Select, MultiSelect and OrderedList primitives

Claude-Session: https://claude.ai/code/session_01EZbQf8PvzNCADFo6bW74ko"
```

---

### Task 4: `SettingField`, `ServiceTest`, `Picker`, `SectionView` and the pure helpers

**Files:**
- Modify: `frontend/src/api.ts` (types and three functions next to the existing `settings:` entry)
- Create: `frontend/src/pages/admin/settings/visibility.ts`, `SettingField.tsx`, `ServiceTest.tsx`, `Picker.tsx`, `SectionView.tsx`
- Test: `frontend/src/pages/admin/settings/visibility.test.ts`, `SectionView.test.tsx` (new)

**Interfaces:**
- Consumes: primitives from Task 3; the payload shape from Task 1; routes from Task 2.
- Produces (all exported):
  - `api.ts`: `SettingsField` (`key,label,help,kind,options: Option[]|null,placeholder,unit,min,max,advanced,depends_on,test,picker,component,readonly,value,overridden,hot_reload`), `SettingsSection` (`id,title,description,icon,fields`), `api.settingsSchema(): Promise<{sections: SettingsSection[]; hot_reload: string[]}>`, `api.settingsTest(service, values): Promise<{ok, message}>`, `api.settingsPicker(name, values): Promise<{ok, options?, error?}>`.
  - `visibility.ts`: `type FieldValue = string | boolean | string[]`; `type Values = Record<string, FieldValue>`; `initialValue(f)`; `initialValues(sections)`; `dependsSatisfied(f, values)`; `isVisible(f, values, advanced)`; `matchesQuery(f, q)`; `sectionMatches(section, q)`; `serialize(sections, values): Record<string,string>` (form fields `setting_KEY`, secrets with `''` omitted, arrays joined with commas, booleans `'true'/'false'`); `serviceValues(sections, service, values): Record<string,string>`; `countChanges(sections, values, initial)`.
  - `SettingField({ field, value, onChange, values, sections })`; `ServiceTest({ service, label, sections, values })`; `Picker({ field, value, onChange, sections, values })`; `SectionView({ section, values, onChange, advanced, query, sections, custom: Record<string, ComponentType> })`.

- [ ] **Step 1: Extend `api.ts`**

Next to `settings:` in the `api` object:

```ts
  settingsSchema: () =>
    http<{ sections: SettingsSection[]; hot_reload: string[] }>('/ui/api/settings/schema'),
  settingsTest: (service: string, values: Record<string, string>) =>
    http<{ ok: boolean; message: string }>(`/ui/api/settings/test/${service}`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    }),
  settingsPicker: (name: string, values: Record<string, string>) =>
    http<{ ok: boolean; options?: { value: string; label: string }[]; error?: string }>(
      `/ui/api/settings/picker/${name}`,
      { method: 'POST', body: JSON.stringify({ values }) },
    ),
```

And after `SettingItem`:

```ts
export type SettingKind =
  | 'bool' | 'int' | 'float' | 'str' | 'list' | 'url' | 'path' | 'secret'
  | 'select' | 'multiselect' | 'ordered' | 'custom';

export interface SettingsField {
  key: string;
  label: string;
  help: string;
  kind: SettingKind;
  options: { value: string; label: string }[] | null;
  placeholder: string | null;
  unit: string | null;
  min: number | null;
  max: number | null;
  advanced: boolean;
  depends_on: string | null;
  test: string | null;
  picker: string | null;
  component: string | null;
  readonly: boolean;
  value: any;
  overridden: boolean;
  hot_reload: boolean;
}

export interface SettingsSection {
  id: string;
  title: string;
  description: string;
  icon: string;
  fields: SettingsField[];
}
```

- [ ] **Step 2: Write the failing helper tests**

`frontend/src/pages/admin/settings/visibility.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import type { SettingsField, SettingsSection } from '../../../api';
import {
  countChanges, dependsSatisfied, initialValue, initialValues, isVisible, matchesQuery,
  sectionMatches, serialize, serviceValues,
} from './visibility';

const f = (over: Partial<SettingsField>): SettingsField => ({
  key: 'K', label: 'Key', help: 'help', kind: 'str', options: null, placeholder: null, unit: null,
  min: null, max: null, advanced: false, depends_on: null, test: null, picker: null, component: null,
  readonly: false, value: '', overridden: false, hot_reload: true, ...over,
});
const section = (fields: SettingsField[]): SettingsSection => ({ id: 's', title: 'Sec', description: 'd', icon: 'x', fields });

describe('initial values', () => {
  it('turns lists into arrays, bools into booleans and secrets into empty strings', () => {
    expect(initialValue(f({ kind: 'multiselect', value: ['en', 'nl'] }))).toEqual(['en', 'nl']);
    expect(initialValue(f({ kind: 'bool', value: 1 }))).toBe(true);
    expect(initialValue(f({ kind: 'secret', value: true }))).toBe('');
    expect(initialValue(f({ kind: 'int', value: 7 }))).toBe('7');
    expect(initialValue(f({ kind: 'list', value: ['2160p:40'] }))).toBe('2160p:40');
  });
});

describe('visibility', () => {
  const values = { CATBOX_MODE: true, ZILEAN_MODE: 'native' };
  it('follows a bool dependency and a select value dependency', () => {
    expect(dependsSatisfied(f({ depends_on: 'CATBOX_MODE' }), values)).toBe(true);
    expect(dependsSatisfied(f({ depends_on: 'CATBOX_MODE' }), { CATBOX_MODE: false })).toBe(false);
    expect(dependsSatisfied(f({ depends_on: 'ZILEAN_MODE=native' }), values)).toBe(true);
    expect(dependsSatisfied(f({ depends_on: 'ZILEAN_MODE=external' }), values)).toBe(false);
  });
  it('hides advanced fields in simple mode', () => {
    expect(isVisible(f({ advanced: true }), values, false)).toBe(false);
    expect(isVisible(f({ advanced: true }), values, true)).toBe(true);
    expect(isVisible(f({ advanced: true, depends_on: 'CATBOX_MODE' }), { CATBOX_MODE: false }, true)).toBe(false);
  });
});

describe('search', () => {
  it('matches label, key and help, case-insensitively', () => {
    const x = f({ key: 'TORBOX_API_KEY', label: 'TorBox API key', help: 'From TorBox settings.' });
    expect(matchesQuery(x, 'torbox')).toBe(true);
    expect(matchesQuery(x, 'API_KEY')).toBe(true);
    expect(matchesQuery(x, 'settings')).toBe(true);
    expect(matchesQuery(x, 'jellyfin')).toBe(false);
    expect(matchesQuery(x, '')).toBe(true);
    expect(sectionMatches(section([x]), 'jelly')).toBe(false);
    expect(sectionMatches(section([x]), 'torb')).toBe(true);
  });
});

describe('serialize', () => {
  const sections = [section([
    f({ key: 'A', kind: 'bool' }), f({ key: 'B', kind: 'multiselect' }), f({ key: 'S', kind: 'secret' }),
    f({ key: 'T', kind: 'secret' }), f({ key: '__X', kind: 'custom', component: 'X' }),
  ])];
  it('posts setting_ fields, joins arrays, skips untouched secrets and custom cards', () => {
    expect(serialize(sections, { A: false, B: ['en', 'nl'], S: '', T: 'new' })).toEqual({
      setting_A: 'false', setting_B: 'en,nl', setting_T: 'new',
    });
  });
  it('collects the values of one service and counts changes', () => {
    const s = [section([f({ key: 'RADARR_URL', test: 'radarr' }), f({ key: 'RADARR_API_KEY', kind: 'secret', test: 'radarr' }), f({ key: 'OTHER' })])];
    expect(serviceValues(s, 'radarr', { RADARR_URL: 'http://r', RADARR_API_KEY: '', OTHER: 'x' })).toEqual({ RADARR_URL: 'http://r', RADARR_API_KEY: '' });
    const initial = initialValues(s);
    expect(countChanges(s, { ...initial, RADARR_URL: 'http://r' }, initial)).toBe(1);
    expect(countChanges(s, initial, initial)).toBe(0);
  });
});
```

- [ ] **Step 3: Run to verify it fails**

Run: `cd frontend && npx vitest run src/pages/admin/settings/visibility.test.ts`
Expected: FAIL, cannot resolve `./visibility`.

- [ ] **Step 4: Write `visibility.ts`**

```ts
import type { SettingsField, SettingsSection } from '../../../api';

export type FieldValue = string | boolean | string[];
export type Values = Record<string, FieldValue>;

const ARRAY_KINDS = new Set(['multiselect', 'ordered']);

export function initialValue(f: SettingsField): FieldValue {
  if (f.kind === 'bool') return Boolean(f.value);
  if (f.kind === 'secret') return '';
  if (ARRAY_KINDS.has(f.kind)) return Array.isArray(f.value) ? f.value.map(String) : [];
  if (f.kind === 'list') return Array.isArray(f.value) ? f.value.join(',') : String(f.value ?? '');
  if (f.value === null || f.value === undefined) return '';
  return String(f.value);
}

export function initialValues(sections: SettingsSection[]): Values {
  const v: Values = {};
  sections.forEach((s) => s.fields.forEach((f) => {
    if (f.kind !== 'custom') v[f.key] = initialValue(f);
  }));
  return v;
}

export function dependsSatisfied(f: SettingsField, values: Values): boolean {
  if (!f.depends_on) return true;
  const [key, wanted] = f.depends_on.split('=');
  const v = values[key];
  if (wanted === undefined) return Boolean(v);
  return v === wanted;
}

export function isVisible(f: SettingsField, values: Values, advanced: boolean): boolean {
  if (f.advanced && !advanced) return false;
  return dependsSatisfied(f, values);
}

export function matchesQuery(f: SettingsField, q: string): boolean {
  const needle = q.trim().toLowerCase();
  if (!needle) return true;
  return [f.label, f.key, f.help].some((t) => (t || '').toLowerCase().includes(needle));
}

export function sectionMatches(s: SettingsSection, q: string): boolean {
  if (!q.trim()) return true;
  const needle = q.trim().toLowerCase();
  return s.title.toLowerCase().includes(needle) || s.fields.some((f) => matchesQuery(f, q));
}

export function asString(v: FieldValue | undefined): string {
  if (v === undefined) return '';
  if (typeof v === 'boolean') return v ? 'true' : 'false';
  if (Array.isArray(v)) return v.join(',');
  return v;
}

export function serialize(sections: SettingsSection[], values: Values): Record<string, string> {
  const out: Record<string, string> = {};
  sections.forEach((s) => s.fields.forEach((f) => {
    if (f.kind === 'custom' || f.readonly) return;
    const v = values[f.key];
    if (f.kind === 'secret' && (v === '' || v === undefined)) return;
    out[`setting_${f.key}`] = asString(v);
  }));
  return out;
}

export function serviceValues(sections: SettingsSection[], service: string, values: Values): Record<string, string> {
  const out: Record<string, string> = {};
  sections.forEach((s) => s.fields.forEach((f) => {
    if (f.test === service) out[f.key] = asString(values[f.key]);
  }));
  return out;
}

export function countChanges(sections: SettingsSection[], values: Values, initial: Values): number {
  let n = 0;
  sections.forEach((s) => s.fields.forEach((f) => {
    if (f.kind === 'custom') return;
    if (asString(values[f.key]) !== asString(initial[f.key])) n += 1;
  }));
  return n;
}
```

- [ ] **Step 5: Run the helper tests**

Run: `cd frontend && npx vitest run src/pages/admin/settings/visibility.test.ts`
Expected: PASS.

- [ ] **Step 6: Write the failing component tests**

`frontend/src/pages/admin/settings/SectionView.test.tsx`:

```tsx
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { useState } from 'react';
import type { SettingsField, SettingsSection } from '../../../api';
import { SectionView } from './SectionView';
import { initialValues } from './visibility';

const apiMocks = vi.hoisted(() => ({ settingsTest: vi.fn(), settingsPicker: vi.fn() }));
vi.mock('../../../api', async () => {
  const actual = await vi.importActual<typeof import('../../../api')>('../../../api');
  return { ...actual, api: { ...actual.api, ...apiMocks } };
});

const f = (over: Partial<SettingsField>): SettingsField => ({
  key: 'K', label: 'Key', help: 'help', kind: 'str', options: null, placeholder: null, unit: null,
  min: null, max: null, advanced: false, depends_on: null, test: null, picker: null, component: null,
  readonly: false, value: '', overridden: false, hot_reload: true, ...over,
});

const SECTION: SettingsSection = {
  id: 'arrs', title: 'Radarr / Sonarr', description: 'Mirror the library.', icon: 'x',
  fields: [
    f({ key: 'ARR_SYNC_ENABLED', label: 'Mirror the library', kind: 'bool', value: true }),
    f({ key: 'RADARR_URL', label: 'Radarr URL', kind: 'url', depends_on: 'ARR_SYNC_ENABLED', test: 'radarr', value: 'http://r.test' }),
    f({ key: 'RADARR_API_KEY', label: 'Radarr API key', kind: 'secret', depends_on: 'ARR_SYNC_ENABLED', test: 'radarr', value: true }),
    f({ key: 'RADARR_ROOT_FOLDER', label: 'Radarr root folder', kind: 'path', depends_on: 'ARR_SYNC_ENABLED', picker: 'radarr_root_folders', value: '' }),
    f({ key: 'ARR_SYNC_INTERVAL_MINUTES', label: 'Reconcile interval', kind: 'int', unit: 'minutes', advanced: true, hot_reload: false, value: 60 }),
    f({ key: 'SORT_ORDER', label: 'Sort order', kind: 'ordered', options: [{ value: 'a', label: 'a' }, { value: 'b', label: 'b' }], value: ['a'] }),
    f({ key: '__Note', label: 'Note', kind: 'custom', component: 'Note' }),
  ],
};

function Harness({ advanced = false, query = '' }: { advanced?: boolean; query?: string }) {
  const [values, setValues] = useState(initialValues([SECTION]));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return (
    <QueryClientProvider client={qc}>
      <SectionView
        section={SECTION}
        sections={[SECTION]}
        values={values}
        onChange={(k, v) => setValues((p) => ({ ...p, [k]: v }))}
        advanced={advanced}
        query={query}
        custom={{ Note: () => <div>custom card</div> }}
      />
    </QueryClientProvider>
  );
}

describe('SectionView', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders label, help, the right control per kind, and the custom card', () => {
    render(<Harness />);
    expect(screen.getByText('Mirror the library')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: 'Mirror the library' })).toBeChecked();
    expect(screen.getByRole('textbox', { name: 'Radarr URL' })).toHaveValue('http://r.test');
    const secret = screen.getByLabelText('Radarr API key');
    expect(secret).toHaveAttribute('type', 'password');
    expect(secret).toHaveAttribute('placeholder', expect.stringContaining('already set'));
    expect(screen.getByRole('button', { name: 'Move a down' })).toBeInTheDocument();
    expect(screen.getByText('custom card')).toBeInTheDocument();
  });

  it('reveals a secret, hides advanced fields in simple mode and shows them in advanced', async () => {
    const { rerender } = render(<Harness />);
    await userEvent.click(screen.getByRole('button', { name: 'Show Radarr API key' }));
    expect(screen.getByLabelText('Radarr API key')).toHaveAttribute('type', 'text');
    expect(screen.queryByLabelText('Reconcile interval')).not.toBeInTheDocument();
    rerender(<Harness advanced />);
    expect(screen.getByLabelText('Reconcile interval')).toHaveValue(60);
    expect(screen.getByText('minutes')).toBeInTheDocument();
    expect(screen.getByText('restart')).toBeInTheDocument();
  });

  it('hides dependent fields when the toggle goes off', async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole('checkbox', { name: 'Mirror the library' }));
    expect(screen.queryByRole('textbox', { name: 'Radarr URL' })).not.toBeInTheDocument();
  });

  it('dims fields that do not match the search', () => {
    render(<Harness query="root" />);
    expect(screen.getByTestId('field-RADARR_ROOT_FOLDER')).not.toHaveClass('opacity-40');
    expect(screen.getByTestId('field-RADARR_URL')).toHaveClass('opacity-40');
  });

  it('one Test button per service posts the typed values and shows the message', async () => {
    apiMocks.settingsTest.mockResolvedValue({ ok: true, message: 'Radarr 5.2.0, 12 movies' });
    render(<Harness />);
    const url = screen.getByRole('textbox', { name: 'Radarr URL' });
    await userEvent.clear(url);
    await userEvent.type(url, 'http://new.test');
    expect(screen.getAllByRole('button', { name: 'Test Radarr' })).toHaveLength(1);
    await userEvent.click(screen.getByRole('button', { name: 'Test Radarr' }));
    await waitFor(() => expect(apiMocks.settingsTest).toHaveBeenCalledWith('radarr', { RADARR_URL: 'http://new.test', RADARR_API_KEY: '' }));
    expect(await screen.findByText('Radarr 5.2.0, 12 movies')).toBeInTheDocument();
    apiMocks.settingsTest.mockResolvedValue({ ok: false, message: 'Radarr refused the API key (HTTP 401)' });
    await userEvent.click(screen.getByRole('button', { name: 'Test Radarr' }));
    expect(await screen.findByText('Radarr refused the API key (HTTP 401)')).toHaveClass('text-danger');
  });

  it('a picker loads options into a dropdown and keeps a text input on failure', async () => {
    apiMocks.settingsPicker.mockResolvedValue({ ok: true, options: [{ value: '/movies', label: '/movies (5 GB free)' }] });
    render(<Harness />);
    expect(screen.getByRole('textbox', { name: 'Radarr root folder' })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Load Radarr root folder' }));
    const pick = await screen.findByRole('combobox', { name: 'Radarr root folder' });
    await waitFor(() => expect(apiMocks.settingsPicker).toHaveBeenCalledWith('radarr_root_folders', { RADARR_URL: 'http://r.test', RADARR_API_KEY: '' }));
    await userEvent.selectOptions(pick, '/movies');
    expect(pick).toHaveValue('/movies');
    apiMocks.settingsPicker.mockResolvedValue({ ok: false, error: 'Radarr did not answer, or refused the API key' });
    await userEvent.click(screen.getByRole('button', { name: 'Load Radarr root folder' }));
    expect(await screen.findByText('Radarr did not answer, or refused the API key')).toBeInTheDocument();
  });
});
```

- [ ] **Step 7: Write the components**

`SettingField.tsx`:

```tsx
import { useState } from 'react';
import type { SettingsField, SettingsSection } from '../../../api';
import { Button, MultiSelect, OrderedList, Select, Toggle } from '../../../components/primitives';
import { Picker } from './Picker';
import type { FieldValue, Values } from './visibility';

const INPUT = 'w-full max-w-md rounded border border-border bg-bg px-2 py-1 text-xs';

function Badges({ field }: { field: SettingsField }) {
  return (
    <span className="ml-2 inline-flex gap-1 align-middle">
      {!field.hot_reload && <span className="rounded bg-warn/20 px-1.5 text-[10px] font-semibold uppercase text-warn">restart</span>}
      {!field.overridden && field.value !== '' && field.value !== null && field.value !== false && (
        <span className="rounded bg-white/10 px-1.5 text-[10px] font-semibold uppercase text-muted" title="value comes from .env or the default">env</span>
      )}
    </span>
  );
}

function Help({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > 110;
  return (
    <div className="mt-1 text-xs text-muted">
      {long && !open ? `${text.slice(0, 100).trimEnd()}...` : text}
      {long && (
        <button type="button" onClick={() => setOpen((o) => !o)} className="ml-1 text-accent-light hover:underline" aria-label={open ? 'Less' : 'More'}>
          {open ? 'less' : 'more'}
        </button>
      )}
    </div>
  );
}

function isValidUrl(v: string): boolean {
  if (!v) return true;
  try {
    const u = new URL(v);
    return u.protocol === 'http:' || u.protocol === 'https:';
  } catch {
    return false;
  }
}

export function Control({
  field, value, onChange, values, sections,
}: {
  field: SettingsField;
  value: FieldValue;
  onChange: (next: FieldValue) => void;
  values: Values;
  sections: SettingsSection[];
}) {
  const [reveal, setReveal] = useState(false);
  const str = typeof value === 'string' ? value : '';
  switch (field.kind) {
    case 'bool':
      return <Toggle checked={Boolean(value)} onChange={onChange} label={field.label} />;
    case 'select':
      return <Select label={field.label} value={str} onChange={onChange} options={field.options || []} placeholder={field.placeholder ?? undefined} />;
    case 'multiselect':
      return <MultiSelect label={field.label} value={Array.isArray(value) ? value : []} onChange={onChange} options={field.options || []} />;
    case 'ordered':
      return <OrderedList label={field.label} value={Array.isArray(value) ? value : []} onChange={onChange} options={field.options || []} />;
    case 'int':
    case 'float':
      return (
        <span className="inline-flex items-center gap-2">
          <input type="number" aria-label={field.label} value={str} min={field.min ?? undefined} max={field.max ?? undefined}
            step={field.kind === 'float' ? '0.1' : '1'} onChange={(e) => onChange(e.target.value)} className={`${INPUT} max-w-[8rem]`} />
          {field.unit && <span className="text-xs text-muted">{field.unit}</span>}
        </span>
      );
    case 'secret':
      return (
        <span className="inline-flex w-full max-w-md items-center gap-2">
          <input type={reveal ? 'text' : 'password'} aria-label={field.label} value={str} autoComplete="new-password"
            placeholder={field.value ? '(already set, type to replace)' : '(not set)'} onChange={(e) => onChange(e.target.value)} className={INPUT} />
          <Button variant="ghost" aria-label={`${reveal ? 'Hide' : 'Show'} ${field.label}`} onClick={() => setReveal((r) => !r)}>{reveal ? 'Hide' : 'Show'}</Button>
        </span>
      );
    default: {
      if (field.picker) return <Picker field={field} value={str} onChange={onChange} values={values} sections={sections} />;
      const bad = field.kind === 'url' && !isValidUrl(str);
      return (
        <span className="inline-flex w-full max-w-md flex-col gap-1">
          <input type="text" aria-label={field.label} value={str} placeholder={field.placeholder ?? (field.kind === 'list' ? 'comma,separated' : undefined)}
            onChange={(e) => onChange(e.target.value)} className={`${INPUT} ${field.kind === 'path' ? 'font-mono' : ''} ${bad ? 'border-danger' : ''}`} />
          {bad && <span className="text-xs text-danger">Enter a full http or https address.</span>}
        </span>
      );
    }
  }
}

export function SettingField({
  field, value, onChange, values, sections, dimmed = false,
}: {
  field: SettingsField;
  value: FieldValue;
  onChange: (next: FieldValue) => void;
  values: Values;
  sections: SettingsSection[];
  dimmed?: boolean;
}) {
  return (
    <div data-testid={`field-${field.key}`} className={`grid gap-2 border-b border-border py-3 last:border-0 sm:grid-cols-[minmax(0,14rem)_1fr] ${dimmed ? 'opacity-40' : ''}`}>
      <div>
        <span className="text-sm font-medium">{field.label}</span>
        <Badges field={field} />
        <Help text={field.help} />
      </div>
      <div className="flex items-start">
        <Control field={field} value={value} onChange={onChange} values={values} sections={sections} />
      </div>
    </div>
  );
}
```

`ServiceTest.tsx`:

```tsx
import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { api } from '../../../api';
import type { SettingsSection } from '../../../api';
import { Button } from '../../../components/primitives';
import { serviceValues } from './visibility';
import type { Values } from './visibility';

export function ServiceTest({ service, label, sections, values }: { service: string; label: string; sections: SettingsSection[]; values: Values }) {
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const mut = useMutation({
    mutationFn: () => api.settingsTest(service, serviceValues(sections, service, values)),
    onSuccess: (r) => setMsg({ ok: r.ok, text: r.message }),
    onError: (e: Error) => setMsg({ ok: false, text: e.message }),
  });
  return (
    <div className="flex flex-wrap items-center gap-2 py-2">
      <Button onClick={() => mut.mutate()} loading={mut.isPending} loadingLabel="Testing...">{`Test ${label}`}</Button>
      {msg && <span className={`text-xs ${msg.ok ? 'text-ok' : 'text-danger'}`}>{msg.text}</span>}
    </div>
  );
}
```

`Picker.tsx`:

```tsx
import { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { api } from '../../../api';
import type { SettingsField, SettingsSection } from '../../../api';
import { Button, Select } from '../../../components/primitives';
import type { Option } from '../../../components/primitives';
import { serviceValues } from './visibility';
import type { Values } from './visibility';

/** A text input until Load succeeds, then a dropdown of what the service
 * offers with the current value kept even if the service no longer lists it. */
export function Picker({ field, value, onChange, values, sections }: {
  field: SettingsField; value: string; onChange: (next: string) => void; values: Values; sections: SettingsSection[];
}) {
  const [options, setOptions] = useState<Option[] | null>(null);
  const [err, setErr] = useState('');
  const service = (field.picker || '').split('_')[0];
  const mut = useMutation({
    mutationFn: () => api.settingsPicker(field.picker!, serviceValues(sections, service, values)),
    onSuccess: (r) => {
      if (r.ok && r.options) { setOptions(r.options); setErr(r.options.length ? '' : 'nothing to choose from yet'); }
      else setErr(r.error || 'failed');
    },
    onError: (e: Error) => setErr(e.message),
  });
  const shown = options && value && !options.some((o) => o.value === value) ? [{ value, label: value }, ...options] : options;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {shown ? (
        <Select label={field.label} value={value} onChange={onChange} options={shown} placeholder={field.placeholder ?? '(default)'} />
      ) : (
        <input type="text" aria-label={field.label} value={value} placeholder={field.placeholder ?? undefined} onChange={(e) => onChange(e.target.value)}
          className="w-full max-w-xs rounded border border-border bg-bg px-2 py-1 font-mono text-xs" />
      )}
      <Button onClick={() => mut.mutate()} loading={mut.isPending} loadingLabel="Loading..." aria-label={`Load ${field.label}`}>Load</Button>
      {err && <span className="text-xs text-danger">{err}</span>}
    </div>
  );
}
```

`SectionView.tsx`:

```tsx
import type { ComponentType } from 'react';
import type { SettingsField, SettingsSection } from '../../../api';
import { Card } from '../../../components/primitives';
import { ServiceTest } from './ServiceTest';
import { SettingField } from './SettingField';
import { isVisible, matchesQuery } from './visibility';
import type { FieldValue, Values } from './visibility';

const SERVICE_LABEL: Record<string, string> = {
  torbox: 'TorBox', realdebrid: 'RealDebrid', tmdb: 'TMDB', zilean: 'Zilean', zilean_pg: 'Postgres',
  debridio: 'Debridio', jellyfin: 'Jellyfin', seerr: 'Seerr', radarr: 'Radarr', sonarr: 'Sonarr',
  trakt: 'Trakt', opensubtitles: 'OpenSubtitles', discord: 'Discord', telegram: 'Telegram', oidc: 'OIDC',
};

export function SectionView({
  section, sections, values, onChange, advanced, query, custom,
}: {
  section: SettingsSection;
  sections: SettingsSection[];
  values: Values;
  onChange: (key: string, next: FieldValue) => void;
  advanced: boolean;
  query: string;
  custom: Record<string, ComponentType<{ values: Values; onChange: (key: string, next: FieldValue) => void }>>;
}) {
  const visible = section.fields.filter((f) => f.kind === 'custom' || isVisible(f, values, advanced));
  const allAdvancedHidden = visible.every((f) => f.kind === 'custom') && section.fields.some((f) => f.advanced);
  // A service's Test button sits after the last of its fields.
  const lastOfService: Record<string, string> = {};
  visible.forEach((f) => { if (f.test) lastOfService[f.test] = f.key; });
  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-lg font-bold">{section.title}</h2>
        <p className="text-sm text-muted">{section.description}</p>
      </div>
      {allAdvancedHidden && (
        <p className="text-sm text-muted">Everything here is an advanced setting. Switch to Advanced above to see it.</p>
      )}
      <Card>
        {visible.map((f: SettingsField) => {
          if (f.kind === 'custom') {
            const C = custom[f.component || ''];
            return C ? <div key={f.key} className="py-3"><C values={values} onChange={onChange} /></div> : null;
          }
          return (
            <div key={f.key}>
              <SettingField field={f} value={values[f.key]} onChange={(v) => onChange(f.key, v)} values={values} sections={sections} dimmed={!matchesQuery(f, query)} />
              {f.test && lastOfService[f.test] === f.key && (
                <ServiceTest service={f.test} label={SERVICE_LABEL[f.test] || f.test} sections={sections} values={values} />
              )}
            </div>
          );
        })}
      </Card>
    </div>
  );
}
```

- [ ] **Step 8: Run the tests and type-check**

Run: `cd frontend && npx tsc --noEmit && npx vitest run src/pages/admin/settings/`
Expected: PASS. The `env` badge test is not asserted; the `restart` badge is.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/api.ts frontend/src/pages/admin/settings/
git commit -m "feat(ui): schema-driven SettingField, service tests and pickers

Claude-Session: https://claude.ai/code/session_01EZbQf8PvzNCADFo6bW74ko"
```

---

### Task 5: The Settings shell

**Files:**
- Create: `frontend/src/pages/admin/settings/customCards.tsx`
- Rewrite: `frontend/src/pages/admin/Settings.tsx`, `frontend/src/pages/admin/Settings.test.tsx`
- Modify: `frontend/src/api.ts`: remove `arrTest`, `arrRootFolders`, `ArrConn`, `ArrRootFolder` if nothing else imports them (grep first; `Settings.tsx` was the only user)
- Build: `static/app/` (committed)

**Interfaces:**
- Consumes: `SectionView`, `visibility.ts`, `api.settingsSchema`, `api.saveSettings`, `api.genreTabsConfig`, `api.setGenreTabsConfig`, `api.genres`, `api.setLegacyPassword`, `api.autoAddNow`, and the existing `GET /ui/api/webhook-secret` (add `api.webhookSecret: () => http<{ secret: string }>('/ui/api/webhook-secret')` if absent; check the route's JSON key in `app.py` line 1161 onward and use that key).
- Produces: default export `Settings` mounted by `AdminLayout` unchanged; `CUSTOM_CARDS: Record<string, ComponentType>` with `WebhookSecret`, `FilterRulesLink`, `GenreTabs`, `AutoAddNow`, `LegacyPassword`.

- [ ] **Step 1: Write the failing shell tests**

Rewrite `frontend/src/pages/admin/Settings.test.tsx`:

```tsx
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import Settings from './Settings';

function field(over: Record<string, unknown>) {
  return {
    key: 'K', label: 'Key', help: 'help', kind: 'str', options: null, placeholder: null, unit: null, min: null, max: null,
    advanced: false, depends_on: null, test: null, picker: null, component: null, readonly: false, value: '', overridden: false, hot_reload: true,
    ...over,
  };
}

function schemaFixture() {
  return {
    sections: [
      { id: 'mode', title: 'Mode', description: 'How it runs.', icon: 'x', fields: [
        field({ key: 'LITE_MODE', kind: 'bool', value: false, hot_reload: false, label: 'Lite mode' }),
        field({ key: 'CATBOX_MODE', kind: 'bool', value: true, label: 'Catbox mode', hot_reload: false }),
      ] },
      { id: 'jellyfin', title: 'Jellyfin', description: 'The player.', icon: 'x', fields: [
        field({ key: 'JELLYFIN_URL', kind: 'url', label: 'Jellyfin URL', value: 'http://jf' , test: 'jellyfin' }),
        field({ key: 'JELLYFIN_REFRESH_DELAY_SEC', kind: 'int', label: 'Refresh delay', advanced: true, value: 5 }),
      ] },
      { id: 'intervals', title: 'Intervals', description: 'Timers.', icon: 'x', fields: [
        field({ key: 'CLEANUP_INTERVAL_HOURS', kind: 'int', label: 'Cleanup', advanced: true, value: 24, hot_reload: false }),
      ] },
    ],
    hot_reload: [],
  };
}

const apiMocks = vi.hoisted(() => ({
  settingsSchema: vi.fn(), saveSettings: vi.fn(), settingsTest: vi.fn(), settingsPicker: vi.fn(),
  genreTabsConfig: vi.fn(), genres: vi.fn(), setGenreTabsConfig: vi.fn(), autoAddNow: vi.fn(),
  setLegacyPassword: vi.fn(), webhookSecret: vi.fn(),
}));
vi.mock('../../api', async () => {
  const actual = await vi.importActual<typeof import('../../api')>('../../api');
  return { ...actual, api: { ...actual.api, ...apiMocks } };
});

function renderIt() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><Settings /></QueryClientProvider>);
}

describe('Settings shell', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    apiMocks.settingsSchema.mockResolvedValue(schemaFixture());
    apiMocks.saveSettings.mockResolvedValue(undefined);
    apiMocks.genreTabsConfig.mockResolvedValue({ tabs: [] });
    apiMocks.genres.mockResolvedValue({ genres: [] });
    apiMocks.webhookSecret.mockResolvedValue({ secret: 'abc' });
  });

  it('lists sections in a sidebar and shows the first one', async () => {
    renderIt();
    const nav = await screen.findByRole('navigation', { name: 'Settings sections' });
    expect(within(nav).getAllByRole('button')).toHaveLength(3);
    expect(screen.getByRole('heading', { name: 'Mode' })).toBeInTheDocument();
    expect(screen.getByText('Lite mode')).toBeInTheDocument();
  });

  it('switches sections and remembers the Simple/Advanced choice', async () => {
    renderIt();
    await userEvent.click(await screen.findByRole('button', { name: /Jellyfin/ }));
    expect(screen.getByRole('heading', { name: 'Jellyfin' })).toBeInTheDocument();
    expect(screen.queryByLabelText('Refresh delay')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Advanced' }));
    expect(screen.getByLabelText('Refresh delay')).toBeInTheDocument();
    expect(localStorage.getItem('mycelium.settings.advanced')).toBe('true');
  });

  it('an all-advanced section explains itself in simple mode', async () => {
    renderIt();
    await userEvent.click(await screen.findByRole('button', { name: /Intervals/ }));
    expect(screen.getByText(/Everything here is an advanced setting/)).toBeInTheDocument();
  });

  it('search narrows the sidebar to matching sections and opens the first match', async () => {
    renderIt();
    await screen.findByRole('navigation', { name: 'Settings sections' });
    await userEvent.type(screen.getByRole('searchbox', { name: 'Search settings' }), 'refresh');
    const nav = screen.getByRole('navigation', { name: 'Settings sections' });
    expect(within(nav).getAllByRole('button')).toHaveLength(1);
    expect(screen.getByRole('heading', { name: 'Jellyfin' })).toBeInTheDocument();
  });

  it('counts unsaved changes, warns about restart fields and posts the flattened values', async () => {
    renderIt();
    await userEvent.click(await screen.findByRole('button', { name: /Jellyfin/ }));
    const url = screen.getByRole('textbox', { name: 'Jellyfin URL' });
    await userEvent.clear(url);
    await userEvent.type(url, 'http://new');
    expect(screen.getByText('1 unsaved change')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Mode/ }));
    await userEvent.click(screen.getByRole('checkbox', { name: 'Catbox mode' }));
    expect(screen.getByText('2 unsaved changes')).toBeInTheDocument();
    expect(screen.getByText(/restart the container after saving/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(apiMocks.saveSettings).toHaveBeenCalledWith(expect.objectContaining({
      setting_JELLYFIN_URL: 'http://new', setting_CATBOX_MODE: 'false', setting_LITE_MODE: 'false',
    })));
    expect(await screen.findByText('Saved')).toBeInTheDocument();
    expect(screen.queryByText(/unsaved change/)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/pages/admin/Settings.test.tsx`
Expected: FAIL (the old page renders groups from `api.settings`, which is unmocked here).

- [ ] **Step 3: Write `customCards.tsx`**

Move `DiscoverGenreTabsPanel` (as `GenreTabs`), `LegacyPasswordCard` (as `LegacyPassword`) and the "Auto-add now" card (as `AutoAddNow`) from the old `Settings.tsx` verbatim apart from the renames, replacing hand-styled `<button>` elements with `Button`. `ModeCard` is dropped: `LITE_MODE` is an ordinary toggle in the schema now. Add:

```tsx
export function WebhookSecret() {
  const { data } = useQuery({ queryKey: ['webhook-secret'], queryFn: api.webhookSecret });
  const [copied, setCopied] = useState(false);
  const secret = data?.secret || '';
  return (
    <div className="grid gap-2 sm:grid-cols-[minmax(0,14rem)_1fr]">
      <div>
        <span className="text-sm font-medium">Webhook secret</span>
        <div className="mt-1 text-xs text-muted">Paste this into Seerr's webhook as the X-Webhook-Secret header. Generated once; set WEBHOOK_SECRET in the environment to choose your own.</div>
      </div>
      <div className="flex items-center gap-2">
        <input type="text" readOnly aria-label="Webhook secret" value={secret} className="w-full max-w-md rounded border border-border bg-bg px-2 py-1 font-mono text-xs" />
        <Button onClick={() => { navigator.clipboard?.writeText(secret); setCopied(true); }}>{copied ? 'Copied' : 'Copy'}</Button>
      </div>
    </div>
  );
}

export function FilterRulesLink() {
  return (
    <div className="grid gap-2 sm:grid-cols-[minmax(0,14rem)_1fr]">
      <div>
        <span className="text-sm font-medium">Filter rules</span>
        <div className="mt-1 text-xs text-muted">Which resolutions, sources, encodes, tags and languages are preferred, excluded or required.</div>
      </div>
      <a href="#filter-rules" className="text-sm text-accent-light hover:underline">Open the Filter rules tab</a>
    </div>
  );
}

export const CUSTOM_CARDS = { WebhookSecret, FilterRulesLink, GenreTabs, AutoAddNow, LegacyPassword };
```

Every custom card component accepts `{ values, onChange }` (unused where irrelevant).

- [ ] **Step 4: Rewrite `Settings.tsx`**

```tsx
import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../../api';
import type { SettingsSection } from '../../api';
import { Button } from '../../components/primitives';
import { CUSTOM_CARDS } from './settings/customCards';
import { SectionView } from './settings/SectionView';
import { asString, countChanges, initialValues, sectionMatches, serialize } from './settings/visibility';
import type { FieldValue, Values } from './settings/visibility';

const ADVANCED_KEY = 'mycelium.settings.advanced';

function readAdvanced(): boolean {
  try { return localStorage.getItem(ADVANCED_KEY) === 'true'; } catch { return false; }
}

export default function Settings() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ['admin-settings-schema'], queryFn: api.settingsSchema });
  const sections: SettingsSection[] = useMemo(() => data?.sections || [], [data]);
  const [values, setValues] = useState<Values | null>(null);
  const [initial, setInitial] = useState<Values>({});
  const [active, setActive] = useState<string>('');
  const [query, setQuery] = useState('');
  const [advanced, setAdvanced] = useState(readAdvanced);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    if (!sections.length || values) return;
    const v = initialValues(sections);
    setValues(v);
    setInitial(v);
    setActive(sections[0].id);
  }, [sections, values]);

  useEffect(() => {
    try { localStorage.setItem(ADVANCED_KEY, advanced ? 'true' : 'false'); } catch { /* private mode */ }
  }, [advanced]);

  const shown = sections.filter((s) => sectionMatches(s, query));
  useEffect(() => {
    if (shown.length && !shown.some((s) => s.id === active)) setActive(shown[0].id);
  }, [query, shown, active]);

  const saveMut = useMutation({
    mutationFn: async () => { if (values) await api.saveSettings(serialize(sections, values)); },
    onSuccess: () => {
      if (values) setInitial(values);
      setSavedAt(Date.now());
      qc.invalidateQueries({ queryKey: ['admin-settings'] });
    },
  });

  if (!values) return <p className="text-sm text-muted">Loading...</p>;

  const changes = countChanges(sections, values, initial);
  const restartTouched = sections.some((s) => s.fields.some((f) => !f.hot_reload && f.kind !== 'custom' && asString(values[f.key]) !== asString(initial[f.key])));
  const current = sections.find((s) => s.id === active) || shown[0];
  const onChange = (key: string, next: FieldValue) => { setValues((p) => ({ ...(p as Values), [key]: next })); setSavedAt(null); };

  return (
    <div className="grid gap-6 pb-20 md:grid-cols-[13rem_1fr]">
      <aside className="space-y-3">
        <input type="search" aria-label="Search settings" placeholder="Search settings" value={query} onChange={(e) => setQuery(e.target.value)}
          className="w-full rounded border border-border bg-bg px-2 py-1.5 text-xs" />
        <div role="group" aria-label="Detail level" className="flex rounded border border-border text-xs">
          {(['Simple', 'Advanced'] as const).map((m) => (
            <button key={m} type="button" aria-pressed={advanced === (m === 'Advanced')} onClick={() => setAdvanced(m === 'Advanced')}
              className={`flex-1 py-1 ${advanced === (m === 'Advanced') ? 'bg-accent text-white' : 'text-muted hover:text-body'}`}>{m}</button>
          ))}
        </div>
        <nav aria-label="Settings sections" className="space-y-0.5">
          {shown.map((s) => (
            <button key={s.id} type="button" onClick={() => setActive(s.id)} aria-current={s.id === current?.id ? 'page' : undefined}
              className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm ${s.id === current?.id ? 'bg-white/[0.08] text-white' : 'text-muted hover:text-body'}`}>
              <span aria-hidden="true">{s.icon}</span>{s.title}
            </button>
          ))}
          {!shown.length && <p className="px-2 text-xs text-muted">Nothing matches.</p>}
        </nav>
        <a href="/setup?rerun=1" className="block px-2 text-xs text-accent-light hover:underline">Re-run setup wizard</a>
      </aside>
      <main>
        {current && (
          <SectionView section={current} sections={sections} values={values} onChange={onChange} advanced={advanced} query={query} custom={CUSTOM_CARDS} />
        )}
      </main>
      <div className="fixed inset-x-0 bottom-0 z-10 border-t border-border bg-bg/95 px-4 py-3 backdrop-blur md:left-auto">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-3">
          <span className="text-xs text-muted">
            {changes ? `${changes} unsaved change${changes === 1 ? '' : 's'}` : 'Empty a field to clear its override and fall back to the .env value.'}
            {restartTouched && <span className="ml-2 text-warn">A restart-required setting changed; restart the container after saving.</span>}
          </span>
          <div className="flex items-center gap-3">
            {savedAt && !changes && <span className="text-xs text-ok">Saved</span>}
            <Button variant="primary" onClick={() => saveMut.mutate()} loading={saveMut.isPending} loadingLabel="Saving..." disabled={!changes}>Save</Button>
          </div>
        </div>
      </div>
    </div>
  );
}
```

`api.ts`: add `webhookSecret: () => http<{ secret: string }>('/ui/api/webhook-secret')` with the JSON key the route actually returns (check `app.py` `ui_api_webhook_secret`). Remove `arrTest`, `arrRootFolders`, `ArrConn`, `ArrRootFolder` if unused elsewhere (`grep -rn "arrTest\|arrRootFolders\|ArrConn\|ArrRootFolder" frontend/src`).

- [ ] **Step 5: Run everything and build**

Run: `cd frontend && npx tsc --noEmit && npx vitest run && npm run build`
Expected: all green, `static/app/` updated. Then the backend suite once more (unchanged, sanity).

- [ ] **Step 6: Commit**

```bash
git add frontend/src static/app
git commit -m "feat(ui): settings page with section sidebar, search, Simple/Advanced and save bar

Claude-Session: https://claude.ai/code/session_01EZbQf8PvzNCADFo6bW74ko"
```

---

### Task 6: Docs, changelog and the copy read-through

**Files:**
- Modify: `docs/INTEGRATIONS.md` (Radarr/Sonarr section: quality profile setting; Delete webhooks section unchanged), `docs/install-guide.html` (the Settings mentions: Test buttons on every service, Load for root folders and quality profiles, Simple/Advanced), `README.md` (the admin line and the config table rows for the four new keys), `.env.example` (four new keys), `CHANGELOG.md` (`## [Unreleased]`)
- Test: `tests/test_settings_schema.py` gains one read-through guard

- [ ] **Step 1: Read every label and help once against `config.py`**

Open `settings.py` `SECTIONS` next to `config.py` and check each help line states the same default and unit the code uses (for example `CATBOX_IDLE_MINUTES` 1440, `MIN_SEEDERS` 3, `SEERR_DECLINE_WANTED_AFTER_DAYS` 30). Fix any mismatch in the schema. Add to `tests/test_settings_schema.py`:

```python
def test_help_lines_are_short_sentences():
    for f in _fields():
        if f["kind"] == "custom":
            continue
        assert len(f["help"]) <= 220, f["key"]
        assert f["help"].rstrip().endswith("."), f["key"]
        assert len(f["label"]) <= 40, f["key"]
```

Run the schema tests; fix any help line that fails.

- [ ] **Step 2: `.env.example` and README**

Add under the Radarr/Sonarr block of `.env.example`:

```
# Quality profile by name; blank uses the arr's first profile.
RADARR_QUALITY_PROFILE=
SONARR_QUALITY_PROFILE=
```

README: in the configuration table add rows for `RADARR_QUALITY_PROFILE`, `SONARR_QUALITY_PROFILE`, `ARR_SYNC_INTERVAL_MINUTES`, `DISK_SYNC_INTERVAL_MINUTES`; in the admin paragraph replace the Settings sentence with: "Settings is organised in sections with a search box and a Simple/Advanced switch; every integration has a Test button, and Radarr/Sonarr root folders and quality profiles are picked from a list."

- [ ] **Step 3: INTEGRATIONS.md and the manual**

`docs/INTEGRATIONS.md`, Radarr and Sonarr section: after the root-folder sentence add "Pick the quality profile the same way (`RADARR_QUALITY_PROFILE`, `SONARR_QUALITY_PROFILE`); blank uses the first profile, which is what older releases always did." `docs/install-guide.html`: in the Radarr/Sonarr step, replace "Test-knoppen en root-folder-dropdowns" wording with the Test button and Load button wording in both language spans, and mention the quality profile picker.

- [ ] **Step 4: CHANGELOG**

Prepend to `CHANGELOG.md`:

```markdown
## [Unreleased]

### Changed

- The admin Settings tab is rebuilt around a field schema: a section
  sidebar, a label and help line on every setting, real controls
  (toggles, dropdowns, searchable multi-select, an orderable sort order,
  number fields with units, password fields with reveal), a Simple/Advanced
  switch, dependent fields that hide until their toggle is on, and a search
  box. Every integration has a Test button that uses the values as typed;
  Radarr and Sonarr root folders and quality profiles are loaded from the arr.
- New settings `RADARR_QUALITY_PROFILE` and `SONARR_QUALITY_PROFILE` (by
  name; blank keeps the first profile). `ARR_SYNC_INTERVAL_MINUTES` and
  `DISK_SYNC_INTERVAL_MINUTES` are editable in Settings (restart required).
- The setup wizard's connection tests and the old `/ui/api/arr-import/*`
  routes go through the same testers; the arr-import routes are kept as
  aliases for one release.
```

- [ ] **Step 5: Run both suites and commit**

```bash
PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/ -q -p no:cacheprovider
cd frontend && npx tsc --noEmit && npx vitest run && cd ..
git add settings.py tests/test_settings_schema.py .env.example README.md docs/INTEGRATIONS.md docs/install-guide.html CHANGELOG.md
git commit -m "docs(settings): new keys, Test and Load buttons, changelog

Claude-Session: https://claude.ai/code/session_01EZbQf8PvzNCADFo6bW74ko"
```

---

## Self-review notes

- Spec coverage: schema and guards (Task 1), testers and pickers with the five new services and the quality profile keys (Task 2), primitives (Task 3), field renderer, service test, picker, dependent fields, search dimming, Simple mode notice (Tasks 4 and 5), sidebar, search, mode memory, save bar with count and restart warning (Task 5), docs (Task 6). Export/import was declined. The wizard keeps its own field components (follow-up plan) but its test route now goes through the registry.
- Deviations from the spec, stated: `ARR_SYNC_INTERVAL_MINUTES` sits in Intervals with the other timers rather than in the arr section; `TMDB_API_KEY` lives in "Scrapers and metadata"; a `list` kind (free comma-separated text) exists for `MAX_SIZE_GB_BY_RESOLUTION`; `AUTH_SESSION_SECRET` stays environment-only because it is read once at boot.
- Type consistency: `run()` returns `{ok, message}`, the route returns it verbatim, `ServiceTest` reads `message`; `pick()` returns `{ok, options}` or `{ok, error}`, `Picker` reads both; `serviceValues()` sends the field values keyed by setting name, which is what `_v()` reads; `schema_for_ui()` emits `options` as `{value,label}` lists, which `Select`, `MultiSelect` and `OrderedList` consume.
