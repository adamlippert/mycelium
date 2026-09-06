# Arr Integration (Level A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Mycelium a first-class citizen of a Seerr + Radarr + Sonarr + Jellyfin stack: the arrs learn which titles Mycelium owns, deletions made anywhere in the stack reach `cleanup.purge_title()`, Jellyfin is told exactly which paths changed instead of being asked for a full scan, and Seerr requests stop showing "Processing" forever.

**Architecture:** Four independent, additive integrations, each its own module with a thin hook into the existing pipeline. `arr_sync.py` mirrors Mycelium's library into Radarr/Sonarr as monitored, search-off entries (one direction: Mycelium decides what exists). `arr_webhook.py` plus a `/webhook/arr` route turn Radarr `MovieDelete`, Sonarr `SeriesDelete` and the Jellyfin webhook plugin's `ItemDeleted` into `purge_title()` calls. `jellyfin.py` grows a path-change collector so `refresh_library()` posts `/Library/Media/Updated` for the paths just written or removed, falling back to `/Library/Refresh` only when it does not know what changed. `seerr_report.py` reports success and terminal failure back to Seerr through its request/media status endpoints. Nothing here changes how streams are resolved or how TorBox is called.

**Tech Stack:** Python 3.12, Flask, `requests`, SQLite via `db.py`, runtime settings via `settings.py`. Radarr/Sonarr API v3 (`X-Api-Key`), Seerr API v1 (`X-Api-Key`, verified against the Seerr 3.4.1 OpenAPI spec served by the local test stack), Jellyfin 10.11 `POST /Library/Media/Updated` (`MediaUpdateInfoDto {Updates: [{Path, UpdateType}]}`, `UpdateType` one of `Created`, `Modified`, `Deleted`, verified against the test stack's OpenAPI).

**Spec:** The design conversation of 2026-09-06 (media-stack integration assessment, "Level A"). Its conclusions, restated so this plan is self-contained:

- Radarr and Sonarr never import `.strm` files (extension whitelist), so in Level A a mirrored title shows as **Missing** in the arr. That is accepted and cosmetic. The arrs are bookkeeping for Seerr, Maintainerr and the calendar widgets (Jellyfin Enhanced, Homarr), not a download path.
- The arrs keep **no download client**. Radarr logs a harmless "no download client available" health warning; document it.
- Mycelium owns the library. Today it has **no inbound delete signal**: Maintainerr deleting via Radarr, or a person deleting in Jellyfin, leaves `virtual_items`, monitoring rows and dedup keys behind, and a re-request is swallowed as a duplicate for 24 hours.
- Seerr has no delete webhook (it only emits `MEDIA_APPROVED`, `MEDIA_AUTO_APPROVED`, `MEDIA_PENDING`), so delete signals come from the arrs and from Jellyfin.
- `jellyfin.refresh_library()` calls `/Library/Refresh` (a full scan) from seven call sites. Jellyfin's `/Library/Media/Updated` refreshes only the given paths. With that in place, Autopulse is redundant for a Mycelium library.
- Level B (a stub-file tree the arrs can scan, reusing Spore's `make_stub_mkv()`) is deliberately **out of scope** here. `MovieFileDelete` / `EpisodeFileDelete` events are accepted and ignored in Level A because Mycelium titles have no files in the arrs; Level B will act on them.

## Global Constraints

- Work on branch `main`. The repo is public: never commit secrets, tokens, hostnames or IP addresses. Test fixtures use `http://radarr.test`, `http://sonarr.test`, `http://seerr.test`, `http://jellyfin.test`.
- No em-dashes and no `--` anywhere, not in code, comments, docs or commit messages. Use `-` or a comma. Existing code writes `  -  ` for a spaced dash; match it.
- No `Co-Authored-By` trailer. End every commit message with the line `Claude-Session: https://claude.ai/code/session_01EZbQf8PvzNCADFo6bW74ko`.
- Test runner: `.venv-sdd/bin/python -m pytest tests/ -q`. Baseline at `5d953f5`: **632 passed**. Every task must leave the full suite green.
- Tests **never import `app.py`** (it starts the scheduler). Route-level checks assert on the source text through the `_src()` helper shown in each task.
- Every test that touches the database uses the `_isolated_db` autouse fixture shown in each task (`_drop_cached_conn()` + `monkeypatch db.DB_PATH` + `db.init()`), so no test reads `/data/requests.db`.
- Every outbound HTTP call is mocked in tests. No test may reach the network.
- New settings are registered in `settings.py` in three places: the type set (`_BOOL_KEYS` / `_INT_KEYS`), `HOT_RELOAD`, and a `SETTING_GROUPS` entry. The Settings tab renders from `settings.all_for_ui()`, so no frontend change is needed. Each new variable also gets a default in `config.py` and a commented entry in `.env.example`.
- Machine-caller routes carry `@_csrf.exempt` directly under the `@app.post(...)` decorator and call `_check_auth()` first. The set of exempted routes is pinned by `tests/test_tier1_residue.py::test_the_only_csrf_exemptions_are_the_machine_callers`; a task that adds a route updates that pin in the same commit.
- Integration code is best-effort: a hook must never raise into the pipeline. Catch, log at `warning`, return `False`.
- `CHANGELOG.md` has no `## [Unreleased]` section right now. The first task to land creates it directly above `## [0.13.0]`; later tasks append bullets to it.
- `docs/INTEGRATIONS.md` does not exist yet. Each task creates it if absent and appends its own `##` section; tasks are independent, so do not assume another task's section is present.
- Frontend: untouched by this plan. Do not run `npm run build`.

---

## File map

| File | Task | Responsibility |
|---|---|---|
| `arr_sync.py` (new) | 1 | Radarr/Sonarr mirror: add on success, remove on purge, reconcile drift |
| `tmdb.py` | 1, 2 | `tvdb_id_for(tmdb_id)` (Task 1), `imdb_from_tvdb(tvdb_id)` (Task 2) |
| `processor.py:713` | 1, 4 | success hook: `arr_sync.mirror_add`, `seerr_report.on_success`; failed hook: `seerr_report.on_failed` |
| `upgrader.py:255` | 1, 4 | wanted-movie job success hook (same two calls) |
| `cleanup.py:949` | 1, 3 | `purge_title`: `arr_sync.mirror_remove`, `jellyfin.note_change(..., "Deleted")` |
| `app.py` | 1, 2 | scheduler job `arr_sync` (Task 1), route `/webhook/arr` (Task 2) |
| `arr_webhook.py` (new) | 2 | parse Radarr/Sonarr/Jellyfin delete payloads into one `DeleteEvent` |
| `jellyfin.py` | 3 | `note_change()`, targeted `/Library/Media/Updated`, `refresh_library(full=)` |
| `strm_generator.py:1544` | 3 | `_write_strm` notes `Created` |
| `cleanup.py` (lines 164, 188, 227, 243, 311, 887) | 3 | deletions note `Deleted`; the cleanup run asks for a full scan |
| `webhook_parser.py:22` | 4 | `MediaRequest.seerr_request_id` |
| `seerr.py` | 4 | `decline_request()`, `set_media_status()` |
| `seerr_report.py` (new) | 4 | success / failed / stale-wanted reporting, gated by a setting |
| `db.py` | 4 | `get_seerr_request_id()`, `wanted_movies.seerr_reported` column + helpers |
| `settings.py`, `config.py`, `.env.example` | all | new keys |
| `docs/INTEGRATIONS.md` (new), `CHANGELOG.md` | all | operator documentation |
| `tests/test_arr_sync.py`, `tests/test_arr_webhook.py`, `tests/test_targeted_refresh.py`, `tests/test_seerr_report.py` | 1-4 | one test file per task |

Merge points between tasks (both edits are additive, keep both): `processor.py` success block (Tasks 1 and 4), `cleanup.purge_title` (Tasks 1 and 3), `settings.py` / `config.py` / `.env.example` / `CHANGELOG.md` / `docs/INTEGRATIONS.md` (all).

---

### Task 1: Arr mirror (`arr_sync.py`)

**Files:**
- Create: `arr_sync.py`
- Create: `tests/test_arr_sync.py`
- Modify: `tmdb.py` (add `tvdb_id_for` after `tmdb_to_imdb`, around line 52)
- Modify: `settings.py:21-52` (`_BOOL_KEYS`), `settings.py:200-214` (`HOT_RELOAD`), `settings.py:321-325` (`arr_import` group)
- Modify: `config.py:296-299`
- Modify: `processor.py:713` (success block), `upgrader.py:255-260` (wanted job success)
- Modify: `cleanup.py:949-1005` (`purge_title`)
- Modify: `app.py:284-291` (scheduler block, after `strm_cleanup`)
- Modify: `.env.example:94-99`, `CHANGELOG.md`, `docs/INTEGRATIONS.md`

**Interfaces:**
- Consumes: `settings.get(key, default)`, `radarr.list_movies(url, api_key) -> list[dict]` (keys `tmdb_id`, `imdb_id`, `title`), `sonarr.list_series(url, api_key) -> list[dict]` (keys `tvdb_id`, `tmdb_id`, `imdb_id`, `title`), `db.get_recent(limit) -> list[dict]` (request rows with `imdb_id`, `media_type`, `tmdb_id`, `status`, `title`), `db.get_request_by_imdb(imdb_id) -> dict | None`, `tmdb._get(path, params=None) -> dict | None`.
- Produces:
  - `arr_sync.is_enabled() -> bool`
  - `arr_sync.mirror_add(imdb_id: str, media_type: str, tmdb_id: int | None = None, title: str = "") -> bool`
  - `arr_sync.mirror_remove(imdb_id: str, media_type: str, tmdb_id: int | None = None) -> bool`
  - `arr_sync.reconcile() -> dict` with keys `checked`, `added`, `failed`, `skipped`
  - `arr_sync._request(method, url, api_key, *, params=None, json=None) -> tuple[int, object]` (the single HTTP seam tests replace)
  - `tmdb.tvdb_id_for(tmdb_id: int) -> int | None`
  - Settings: `ARR_SYNC_ENABLED` (bool, default `false`), `RADARR_ROOT_FOLDER` (str, default `""`), `SONARR_ROOT_FOLDER` (str, default `""`)

`media_type` is `"movie"` for Radarr; anything else (`"series"`, `"tv"`) goes to Sonarr, matching how the rest of the codebase treats the two spellings.

- [ ] **Step 1: Register the settings**

In `config.py`, directly after line 299 (`SONARR_API_KEY = ...`):

```python
# Mirror Mycelium's library into Radarr/Sonarr as monitored, search-off
# entries so Seerr, Maintainerr and calendar widgets see the titles. One
# direction only. Blank root folder = the arr's first root folder.
ARR_SYNC_ENABLED = _env("ARR_SYNC_ENABLED", "false").lower() == "true"
RADARR_ROOT_FOLDER = _env("RADARR_ROOT_FOLDER", "")
SONARR_ROOT_FOLDER = _env("SONARR_ROOT_FOLDER", "")
```

In `settings.py`:
- add `"ARR_SYNC_ENABLED",` to `_BOOL_KEYS` (after `"DEBRIDIO_ENABLED",`)
- add `"ARR_SYNC_ENABLED", "RADARR_ROOT_FOLDER", "SONARR_ROOT_FOLDER",` to `HOT_RELOAD` on the line after `"RADARR_URL", "RADARR_API_KEY", "SONARR_URL", "SONARR_API_KEY",`
- change the `arr_import` group to:

```python
    {
        "id": "arr_import",
        "title": "Radarr / Sonarr",
        "keys": ["RADARR_URL", "RADARR_API_KEY", "SONARR_URL", "SONARR_API_KEY",
                 "ARR_SYNC_ENABLED", "RADARR_ROOT_FOLDER", "SONARR_ROOT_FOLDER"],
    },
```

In `.env.example`, replace the Radarr / Sonarr block (lines 94-99) with:

```
# Radarr / Sonarr (OPTIONAL). Two uses:
#  1. One-way import of their libraries into Mycelium, from the admin UI.
#  2. ARR_SYNC_ENABLED=true mirrors every title Mycelium adds into the arr as
#     a monitored entry with search OFF, and removes it again on "Remove from
#     library". The arrs never import .strm files, so mirrored titles show as
#     "Missing" there; that is expected. Seerr, Maintainerr and calendar
#     widgets read the arrs, which is the point. Give the arrs no download
#     client. Radarr will log a harmless "no download client" warning.
# Root folder: blank = the arr's first configured root folder.
RADARR_URL=
RADARR_API_KEY=
SONARR_URL=
SONARR_API_KEY=
ARR_SYNC_ENABLED=false
RADARR_ROOT_FOLDER=
SONARR_ROOT_FOLDER=
```

- [ ] **Step 2: Write the failing tests for the module**

Create `tests/test_arr_sync.py`:

```python
"""Radarr/Sonarr mirror. The arrs are bookkeeping for the rest of the stack;
Mycelium tells them what it owns and never lets them download anything.
"""
import os
import re
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db

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


class FakeArr:
    """Routes (method, path) to canned (status, body) and records every call."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []
        self.urls = []

    def __call__(self, method, url, api_key, *, params=None, json=None):
        path = url.split("/api/v3", 1)[1]
        self.calls.append((method, path, params, json))
        self.urls.append(url)
        handler = self.routes.get((method, path))
        if handler is None:
            return 404, {"message": "not found"}
        if callable(handler):
            return handler(params, json)
        return handler


@pytest.fixture
def enabled(monkeypatch):
    import arr_sync
    import settings
    values = {
        "ARR_SYNC_ENABLED": True,
        "RADARR_URL": "http://radarr.test", "RADARR_API_KEY": "rk",
        "SONARR_URL": "http://sonarr.test", "SONARR_API_KEY": "sk",
        "RADARR_ROOT_FOLDER": "", "SONARR_ROOT_FOLDER": "",
    }
    monkeypatch.setattr(settings, "get", lambda k, d=None: values.get(k, d))
    arr_sync._defaults_cache.clear()
    return values


RADARR_LOOKUP = [{"title": "Heat", "year": 1995, "tmdbId": 949, "imdbId": "tt0113277",
                  "titleSlug": "heat-949", "images": []}]
SONARR_LOOKUP = [{"title": "Severance", "year": 2022, "tvdbId": 371980,
                  "imdbId": "tt11280740", "titleSlug": "severance",
                  "seasons": [{"seasonNumber": 1, "monitored": True}]}]


def test_disabled_is_a_silent_noop(monkeypatch):
    import arr_sync
    import settings
    monkeypatch.setattr(settings, "get", lambda k, d=None: {"ARR_SYNC_ENABLED": False}.get(k, d))
    fake = FakeArr({})
    monkeypatch.setattr(arr_sync, "_request", fake)
    assert arr_sync.mirror_add("tt0113277", "movie", 949, "Heat") is False
    assert arr_sync.mirror_remove("tt0113277", "movie") is False
    assert fake.calls == []


def test_movie_add_posts_monitored_with_search_off(enabled, monkeypatch):
    import arr_sync
    fake = FakeArr({
        ("GET", "/movie/lookup"): (200, RADARR_LOOKUP),
        ("GET", "/movie"): (200, []),
        ("GET", "/qualityprofile"): (200, [{"id": 4, "name": "HD"}]),
        ("GET", "/rootfolder"): (200, [{"path": "/movies"}]),
        ("POST", "/movie"): (201, {"id": 10}),
    })
    monkeypatch.setattr(arr_sync, "_request", fake)
    assert arr_sync.mirror_add("tt0113277", "movie", 949, "Heat") is True
    posted = [c for c in fake.calls if c[0] == "POST"][0][3]
    assert posted["tmdbId"] == 949
    assert posted["monitored"] is True
    assert posted["qualityProfileId"] == 4
    assert posted["rootFolderPath"] == "/movies"
    assert posted["addOptions"]["searchForMovie"] is False


def test_movie_add_is_idempotent_when_radarr_already_has_it(enabled, monkeypatch):
    import arr_sync
    fake = FakeArr({
        ("GET", "/movie/lookup"): (200, RADARR_LOOKUP),
        ("GET", "/movie"): (200, [{"id": 10, "tmdbId": 949}]),
    })
    monkeypatch.setattr(arr_sync, "_request", fake)
    assert arr_sync.mirror_add("tt0113277", "movie", 949, "Heat") is True
    assert not [c for c in fake.calls if c[0] == "POST"]


def test_root_folder_setting_overrides_the_arr_default(enabled, monkeypatch):
    import arr_sync
    enabled["RADARR_ROOT_FOLDER"] = "/mnt/mycelium"
    fake = FakeArr({
        ("GET", "/movie/lookup"): (200, RADARR_LOOKUP),
        ("GET", "/movie"): (200, []),
        ("GET", "/qualityprofile"): (200, [{"id": 1}]),
        ("POST", "/movie"): (201, {"id": 10}),
    })
    monkeypatch.setattr(arr_sync, "_request", fake)
    assert arr_sync.mirror_add("tt0113277", "movie", 949, "Heat") is True
    assert not [c for c in fake.calls if c[1] == "/rootfolder"]
    posted = [c for c in fake.calls if c[0] == "POST"][0][3]
    assert posted["rootFolderPath"] == "/mnt/mycelium"


def test_series_add_uses_sonarr_and_search_off(enabled, monkeypatch):
    import arr_sync
    fake = FakeArr({
        ("GET", "/series/lookup"): (200, SONARR_LOOKUP),
        ("GET", "/series"): (200, []),
        ("GET", "/qualityprofile"): (200, [{"id": 2}]),
        ("GET", "/rootfolder"): (200, [{"path": "/tv"}]),
        ("POST", "/series"): (201, {"id": 7}),
    })
    monkeypatch.setattr(arr_sync, "_request", fake)
    assert arr_sync.mirror_add("tt11280740", "series", 95396, "Severance") is True
    posted = [c for c in fake.calls if c[0] == "POST"][0][3]
    assert posted["tvdbId"] == 371980
    assert posted["monitored"] is True
    assert posted["addOptions"]["searchForMissingEpisodes"] is False
    assert posted["addOptions"]["searchForCutoffUnmetEpisodes"] is False
    assert all(u.startswith("http://sonarr.test/") for u in fake.urls), "a series never touches Radarr"


def test_series_add_falls_back_to_tvdb_via_tmdb(enabled, monkeypatch):
    import arr_sync
    import tmdb
    monkeypatch.setattr(tmdb, "tvdb_id_for", lambda tmdb_id: 371980)

    def lookup(params, json):
        if params["term"] == "tvdb:371980":
            return 200, SONARR_LOOKUP
        return 200, []

    fake = FakeArr({
        ("GET", "/series/lookup"): lookup,
        ("GET", "/series"): (200, []),
        ("GET", "/qualityprofile"): (200, [{"id": 2}]),
        ("GET", "/rootfolder"): (200, [{"path": "/tv"}]),
        ("POST", "/series"): (201, {"id": 7}),
    })
    monkeypatch.setattr(arr_sync, "_request", fake)
    assert arr_sync.mirror_add("tt11280740", "series", 95396, "Severance") is True
    terms = [c[2]["term"] for c in fake.calls if c[1] == "/series/lookup"]
    assert terms == ["imdb:tt11280740", "tvdb:371980"]


def test_remove_deletes_without_files_and_without_exclusion(enabled, monkeypatch):
    import arr_sync
    fake = FakeArr({
        ("GET", "/movie/lookup"): (200, RADARR_LOOKUP),
        ("GET", "/movie"): (200, [{"id": 10, "tmdbId": 949}]),
        ("DELETE", "/movie/10"): (200, None),
    })
    monkeypatch.setattr(arr_sync, "_request", fake)
    assert arr_sync.mirror_remove("tt0113277", "movie", 949) is True
    method, path, params, _ = [c for c in fake.calls if c[0] == "DELETE"][0]
    assert path == "/movie/10"
    assert params == {"deleteFiles": "false", "addImportExclusion": "false"}


def test_remove_of_an_unknown_title_is_success(enabled, monkeypatch):
    """Purge must not fail because the arr never had the title (or a delete
    webhook already removed it): the two directions must not fight."""
    import arr_sync
    fake = FakeArr({
        ("GET", "/movie/lookup"): (200, RADARR_LOOKUP),
        ("GET", "/movie"): (200, []),
    })
    monkeypatch.setattr(arr_sync, "_request", fake)
    assert arr_sync.mirror_remove("tt0113277", "movie", 949) is True
    assert not [c for c in fake.calls if c[0] == "DELETE"]


def test_a_network_error_never_raises_into_the_pipeline(enabled, monkeypatch):
    import arr_sync

    def boom(*a, **k):
        raise ConnectionError("down")

    monkeypatch.setattr(arr_sync, "_request", boom)
    assert arr_sync.mirror_add("tt0113277", "movie", 949, "Heat") is False
    assert arr_sync.mirror_remove("tt0113277", "movie", 949) is False


def test_reconcile_adds_only_what_the_arr_lacks(enabled, monkeypatch):
    import arr_sync
    import radarr
    import sonarr
    db.insert_request("Heat", "tt0113277", "movie", tmdb_id=949)
    db.update_request(db.get_request_by_imdb("tt0113277")["id"], "success")
    db.insert_request("Alien", "tt0078748", "movie", tmdb_id=348)
    db.update_request(db.get_request_by_imdb("tt0078748")["id"], "success")
    db.insert_request("Nope", "tt0000001", "movie", tmdb_id=1)
    db.update_request(db.get_request_by_imdb("tt0000001")["id"], "failed")
    monkeypatch.setattr(radarr, "list_movies", lambda u, k: [{"imdb_id": "tt0078748", "tmdb_id": 348}])
    monkeypatch.setattr(sonarr, "list_series", lambda u, k: [])
    added = []
    monkeypatch.setattr(arr_sync, "mirror_add",
                        lambda imdb, mt, tmdb_id=None, title="": added.append(imdb) or True)
    out = arr_sync.reconcile()
    assert added == ["tt0113277"]
    assert out == {"checked": 2, "added": 1, "failed": 0, "skipped": 1}


def test_reconcile_is_a_noop_when_disabled(monkeypatch):
    import arr_sync
    import settings
    monkeypatch.setattr(settings, "get", lambda k, d=None: {"ARR_SYNC_ENABLED": False}.get(k, d))
    assert arr_sync.reconcile() == {"checked": 0, "added": 0, "failed": 0, "skipped": 0}


# -- wiring ------------------------------------------------------------------

def test_processor_mirrors_on_success():
    src = _src("processor.py")
    success = src.split("jellyfin.refresh_library()", 1)[1][:1500]
    assert "arr_sync.mirror_add(req.imdb_id, req.media_type" in success


def test_wanted_job_mirrors_when_a_wanted_movie_lands():
    src = _src("upgrader.py")
    block = src.split("db.remove_wanted_movie(w[\"imdb_id\"])", 1)[1][:800]
    assert "arr_sync.mirror_add(w[\"imdb_id\"], \"movie\"" in block


def test_purge_removes_the_mirror():
    src = _src("cleanup.py")
    body = src.split("def purge_title(", 1)[1]
    assert "arr_sync.mirror_remove(imdb_id, media_type" in body


def test_reconcile_is_scheduled():
    src = _src("app.py")
    assert re.search(r'scheduler\.add_job\(\s*arr_sync\.reconcile,[^)]*id="arr_sync"', src)


def test_settings_are_registered():
    src = _src("settings.py")
    assert '"ARR_SYNC_ENABLED"' in src.split("_BOOL_KEYS = {", 1)[1].split("}", 1)[0]
    hot = src.split("HOT_RELOAD = {", 1)[1].split("}", 1)[0]
    for key in ("ARR_SYNC_ENABLED", "RADARR_ROOT_FOLDER", "SONARR_ROOT_FOLDER"):
        assert f'"{key}"' in hot
    env = _src(".env.example")
    for key in ("ARR_SYNC_ENABLED", "RADARR_ROOT_FOLDER", "SONARR_ROOT_FOLDER"):
        assert f"\n{key}=" in env
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv-sdd/bin/python -m pytest tests/test_arr_sync.py -q`
Expected: every test fails with `ModuleNotFoundError: No module named 'arr_sync'` (the wiring tests fail on the missing source text).

- [ ] **Step 4: Add `tmdb.tvdb_id_for`**

In `tmdb.py`, directly after `tmdb_to_imdb` (which ends around line 52):

```python
def tvdb_id_for(tmdb_id: int | str) -> int | None:
    """TVDB id for a TMDB show, via /tv/{id}/external_ids. Sonarr keys on TVDB."""
    data = _get(f"/tv/{tmdb_id}/external_ids")
    raw = (data or {}).get("tvdb_id")
    try:
        return int(raw) if raw else None
    except (TypeError, ValueError):
        return None
```

- [ ] **Step 5: Write `arr_sync.py`**

```python
"""Mirror Mycelium's library into Radarr and Sonarr.

The arrs are bookkeeping for the rest of the stack: Seerr reads them for
availability, Maintainerr deletes through them, and the calendar widgets in
Jellyfin Enhanced and Homarr read their monitored lists. None of that works
for titles they have never heard of, and until now Mycelium never told them.

One direction only. Mycelium decides what exists: a title is added here when
Mycelium adds it and removed here when "Remove from library" runs. Entries
are monitored with search OFF and the arrs are expected to have no download
client, so nothing is ever grabbed. The arrs never import .strm files, so a
mirrored title shows as "Missing" there. That is cosmetic and expected.

Every public function is best-effort: it logs and returns False rather than
raising into the pipeline that called it.
"""
import logging
import threading

import requests

import db
import settings as _settings

log = logging.getLogger(__name__)

_TIMEOUT = 15
_lock = threading.Lock()
# kind -> (quality_profile_id, root_folder). The arr's answer does not change
# between calls; asking once per process keeps reconcile cheap.
_defaults_cache: dict[str, tuple[int, str]] = {}


class ArrError(RuntimeError):
    pass


def is_enabled() -> bool:
    return bool(_settings.get("ARR_SYNC_ENABLED", False))


def _conn(kind: str) -> tuple[str, str]:
    """(base_url, api_key) for 'radarr' or 'sonarr'; empty strings when unset."""
    url = (_settings.get(f"{kind.upper()}_URL", "") or "").strip().rstrip("/")
    key = (_settings.get(f"{kind.upper()}_API_KEY", "") or "").strip()
    return url, key


def _request(method: str, url: str, api_key: str, *, params=None, json=None) -> tuple[int, object]:
    """One HTTP call: (status, decoded body or None). Tests replace this."""
    resp = requests.request(
        method, url,
        headers={"X-Api-Key": api_key, "Accept": "application/json"},
        params=params, json=json, timeout=_TIMEOUT,
    )
    body = None
    if resp.content:
        try:
            body = resp.json()
        except ValueError:
            body = resp.text
    return resp.status_code, body


def _defaults(kind: str, base: str, key: str) -> tuple[int, str]:
    """First quality profile, plus the root folder (setting, else the first)."""
    with _lock:
        if kind in _defaults_cache:
            return _defaults_cache[kind]
    status, profiles = _request("GET", f"{base}/api/v3/qualityprofile", key)
    if status != 200 or not profiles:
        raise ArrError(f"{kind}: no quality profiles ({status})")
    root = (_settings.get(f"{kind.upper()}_ROOT_FOLDER", "") or "").strip()
    if not root:
        status, roots = _request("GET", f"{base}/api/v3/rootfolder", key)
        if status != 200 or not roots:
            raise ArrError(f"{kind}: no root folders ({status})")
        root = roots[0]["path"]
    out = (int(profiles[0]["id"]), root)
    with _lock:
        _defaults_cache[kind] = out
    return out


def _lookup(base: str, key: str, resource: str, terms: list[str], id_field: str) -> dict | None:
    """First lookup hit that carries id_field, trying each term in order."""
    for term in terms:
        status, body = _request("GET", f"{base}/api/v3/{resource}/lookup", key,
                                params={"term": term})
        if status == 200 and body:
            for hit in body:
                if hit.get(id_field):
                    return hit
    return None


def _existing(base: str, key: str, resource: str, id_field: str, value) -> dict | None:
    status, body = _request("GET", f"{base}/api/v3/{resource}", key, params={id_field: value})
    if status == 200 and body:
        return body[0]
    return None


# -- Radarr --------------------------------------------------------------------

def _add_movie(imdb_id: str, tmdb_id: int | None, title: str) -> bool:
    base, key = _conn("radarr")
    if not base or not key:
        log.debug("Arr sync: Radarr not configured; skipping %s", imdb_id)
        return False
    terms = [f"imdb:{imdb_id}"] + ([f"tmdb:{tmdb_id}"] if tmdb_id else [])
    found = _lookup(base, key, "movie", terms, "tmdbId")
    if not found:
        log.info("Arr sync: Radarr has no match for %s (%s)", title or imdb_id, imdb_id)
        return False
    if found.get("id") or _existing(base, key, "movie", "tmdbId", found["tmdbId"]):
        return True
    profile_id, root = _defaults("radarr", base, key)
    body = dict(found)
    body.update({
        "qualityProfileId": profile_id,
        "rootFolderPath": root,
        "monitored": True,
        "minimumAvailability": "released",
        "addOptions": {"searchForMovie": False, "monitor": "movieOnly"},
    })
    status, resp = _request("POST", f"{base}/api/v3/movie", key, json=body)
    if status in (200, 201):
        log.info("Arr sync: mirrored %s (%s) into Radarr", title or imdb_id, imdb_id)
        return True
    if status == 400 and "exist" in str(resp).lower():
        return True
    log.warning("Arr sync: Radarr refused %s: %s %s", imdb_id, status, str(resp)[:200])
    return False


def _remove_movie(imdb_id: str, tmdb_id: int | None) -> bool:
    base, key = _conn("radarr")
    if not base or not key:
        return False
    if not tmdb_id:
        found = _lookup(base, key, "movie", [f"imdb:{imdb_id}"], "tmdbId")
        tmdb_id = found.get("tmdbId") if found else None
    if not tmdb_id:
        log.info("Arr sync: cannot resolve %s for Radarr removal", imdb_id)
        return False
    existing = _existing(base, key, "movie", "tmdbId", tmdb_id)
    if not existing:
        return True
    status, _ = _request("DELETE", f"{base}/api/v3/movie/{existing['id']}", key,
                         params={"deleteFiles": "false", "addImportExclusion": "false"})
    if status in (200, 204, 404):
        log.info("Arr sync: removed %s from Radarr", imdb_id)
        return True
    log.warning("Arr sync: Radarr delete of %s failed: %s", imdb_id, status)
    return False


# -- Sonarr --------------------------------------------------------------------

def _sonarr_find(base: str, key: str, imdb_id: str, tmdb_id: int | None) -> dict | None:
    found = _lookup(base, key, "series", [f"imdb:{imdb_id}"], "tvdbId")
    if found or not tmdb_id:
        return found
    import tmdb
    tvdb_id = tmdb.tvdb_id_for(tmdb_id)
    if not tvdb_id:
        return None
    return _lookup(base, key, "series", [f"tvdb:{tvdb_id}"], "tvdbId")


def _add_series(imdb_id: str, tmdb_id: int | None, title: str) -> bool:
    base, key = _conn("sonarr")
    if not base or not key:
        log.debug("Arr sync: Sonarr not configured; skipping %s", imdb_id)
        return False
    found = _sonarr_find(base, key, imdb_id, tmdb_id)
    if not found:
        log.info("Arr sync: Sonarr has no match for %s (%s)", title or imdb_id, imdb_id)
        return False
    if found.get("id") or _existing(base, key, "series", "tvdbId", found["tvdbId"]):
        return True
    profile_id, root = _defaults("sonarr", base, key)
    body = dict(found)
    body.update({
        "qualityProfileId": profile_id,
        "rootFolderPath": root,
        "monitored": True,
        "seasonFolder": True,
        "addOptions": {
            "searchForMissingEpisodes": False,
            "searchForCutoffUnmetEpisodes": False,
            "monitor": "all",
        },
    })
    status, resp = _request("POST", f"{base}/api/v3/series", key, json=body)
    if status in (200, 201):
        log.info("Arr sync: mirrored %s (%s) into Sonarr", title or imdb_id, imdb_id)
        return True
    if status == 400 and "exist" in str(resp).lower():
        return True
    log.warning("Arr sync: Sonarr refused %s: %s %s", imdb_id, status, str(resp)[:200])
    return False


def _remove_series(imdb_id: str, tmdb_id: int | None) -> bool:
    base, key = _conn("sonarr")
    if not base or not key:
        return False
    found = _sonarr_find(base, key, imdb_id, tmdb_id)
    if not found:
        log.info("Arr sync: cannot resolve %s for Sonarr removal", imdb_id)
        return False
    existing = _existing(base, key, "series", "tvdbId", found["tvdbId"])
    if not existing:
        return True
    status, _ = _request("DELETE", f"{base}/api/v3/series/{existing['id']}", key,
                         params={"deleteFiles": "false", "addImportListExclusion": "false"})
    if status in (200, 204, 404):
        log.info("Arr sync: removed %s from Sonarr", imdb_id)
        return True
    log.warning("Arr sync: Sonarr delete of %s failed: %s", imdb_id, status)
    return False


# -- public --------------------------------------------------------------------

def mirror_add(imdb_id: str, media_type: str, tmdb_id: int | None = None, title: str = "") -> bool:
    """Ensure the title exists in the matching arr. Never raises."""
    if not is_enabled() or not imdb_id:
        return False
    try:
        if media_type == "movie":
            return _add_movie(imdb_id, tmdb_id, title)
        return _add_series(imdb_id, tmdb_id, title)
    except Exception as exc:
        log.warning("Arr sync: add of %s failed: %s", imdb_id, exc)
        return False


def mirror_remove(imdb_id: str, media_type: str, tmdb_id: int | None = None) -> bool:
    """Ensure the title is absent from the matching arr. Never raises.
    A title the arr does not have counts as success, so a purge that was
    itself triggered by the arr's delete webhook does not fail."""
    if not is_enabled() or not imdb_id:
        return False
    try:
        if media_type == "movie":
            return _remove_movie(imdb_id, tmdb_id)
        return _remove_series(imdb_id, tmdb_id)
    except Exception as exc:
        log.warning("Arr sync: removal of %s failed: %s", imdb_id, exc)
        return False


def reconcile() -> dict:
    """Add every successful Mycelium title the arrs lack. Never removes from
    the arrs: they may hold titles Mycelium does not own. Scheduled."""
    out = {"checked": 0, "added": 0, "failed": 0, "skipped": 0}
    if not is_enabled():
        return out
    import radarr
    import sonarr
    have: dict[str, set] = {"movie": set(), "series": set()}
    r_base, r_key = _conn("radarr")
    s_base, s_key = _conn("sonarr")
    try:
        if r_base and r_key:
            for m in radarr.list_movies(r_base, r_key):
                have["movie"].update(x for x in (m.get("imdb_id"), m.get("tmdb_id")) if x)
        if s_base and s_key:
            for s in sonarr.list_series(s_base, s_key):
                have["series"].update(x for x in (s.get("imdb_id"), s.get("tmdb_id")) if x)
    except Exception as exc:
        log.warning("Arr sync: reconcile could not list the arrs: %s", exc)
        return out
    for row in db.get_recent(100000):
        if row.get("status") != "success":
            out["skipped"] += 1
            continue
        out["checked"] += 1
        kind = "movie" if row["media_type"] == "movie" else "series"
        if row["imdb_id"] in have[kind] or (row.get("tmdb_id") and row["tmdb_id"] in have[kind]):
            continue
        if mirror_add(row["imdb_id"], row["media_type"], row.get("tmdb_id"), row.get("title") or ""):
            out["added"] += 1
        else:
            out["failed"] += 1
    log.info("Arr sync: reconcile %s", out)
    return out
```

- [ ] **Step 6: Wire the hooks**

`processor.py`, in `_process_locked`, directly after the line `jellyfin.refresh_library()` (line 713, inside the success branch):

```python
        jellyfin.refresh_library()
        try:
            import arr_sync
            arr_sync.mirror_add(req.imdb_id, req.media_type, req.tmdb_id, req.title)
        except Exception as exc:
            log.debug("arr_sync skipped: %s", exc)
```

`upgrader.py`, in `recheck_wanted()` (line 228), inside `if ok:` directly after `db.remove_wanted_movie(w["imdb_id"])`:

```python
            db.remove_wanted_movie(w["imdb_id"])
            try:
                import arr_sync
                arr_sync.mirror_add(w["imdb_id"], "movie", w.get("tmdb_id"), w["title"])
            except Exception as exc:
                log.debug("arr_sync skipped: %s", exc)
```

`cleanup.py`, `purge_title`: the media type must be captured before the rows are deleted. Replace the first two lines of the body (`result = {...}` and `dirs: set[Path] = set()`) with:

```python
    result = {"strms": 0, "items": 0, "errors": 0}
    dirs: set[Path] = set()
    req_row = db.get_request_by_imdb(imdb_id) or {}
    media_type = req_row.get("media_type") or "movie"
    tmdb_id = req_row.get("tmdb_id")
```

and directly before `log.info("Purged %s from library: %s", imdb_id, result)` add:

```python
    try:
        import arr_sync
        result["arr_removed"] = arr_sync.mirror_remove(imdb_id, media_type, tmdb_id)
    except Exception as exc:
        log.debug("Purge %s: arr_sync skipped: %s", imdb_id, exc)
```

Check that `db` is already imported at the top of `cleanup.py` (it is; `db.get_virtual_items_by_imdb` is used a few lines down).

`app.py`, in the scheduler block directly after the `strm_cleanup` job (after line 291, before `if CATBOX_MODE:`):

```python
    import arr_sync
    scheduler.add_job(
        arr_sync.reconcile,
        trigger="interval", hours=6,
        id="arr_sync", next_run_time=None,
    )
    log.info("Scheduled Radarr/Sonarr mirror reconcile every 6h (active when ARR_SYNC_ENABLED)")
```

The job is registered unconditionally and returns immediately when the setting is off, so toggling `ARR_SYNC_ENABLED` in the UI takes effect without a restart.

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv-sdd/bin/python -m pytest tests/test_arr_sync.py -q`
Expected: all pass.

Then: `.venv-sdd/bin/python -m pytest tests/ -q`
Expected: 632 + the new tests, all green.

- [ ] **Step 8: Mutation check**

Temporarily change `"searchForMovie": False` to `True` in `_add_movie`; run `tests/test_arr_sync.py::test_movie_add_posts_monitored_with_search_off`; it must fail. Revert. Temporarily make `_remove_movie` return `False` when `existing` is None; `test_remove_of_an_unknown_title_is_success` must fail. Revert.

- [ ] **Step 9: Document**

`docs/INTEGRATIONS.md` (create if absent, with the heading `# Integrations` and one line: `How Mycelium talks to the rest of a media stack.`), append:

```markdown
## Radarr and Sonarr

Mycelium can mirror its library into Radarr and Sonarr. Turn it on with
`ARR_SYNC_ENABLED=true` (Settings > Radarr / Sonarr). Every title Mycelium
adds is created in the arr as a monitored entry with **search off**, and
removed again on "Remove from library". A reconcile job runs every six hours
and adds anything the arrs are missing; it never deletes from the arrs.

What this gives you:

- Seerr sees the title in the arr and stops treating it as unknown.
- Maintainerr can manage the title through the arr. When it deletes there,
  the arr's delete webhook tells Mycelium to purge (see Delete webhooks).
- Calendar widgets (Jellyfin Enhanced, Homarr) list the title.

What to expect:

- The arrs **never import `.strm` files**, so every mirrored title shows as
  **Missing** in Radarr/Sonarr. That is cosmetic. Do not "fix" it by giving
  the arr a download client.
- Give the arrs **no download client**. Radarr logs a "no download client is
  available" health warning; ignore it.
- Root folder: blank means the arr's first root folder. Set
  `RADARR_ROOT_FOLDER` / `SONARR_ROOT_FOLDER` to pick another. The quality
  profile is the arr's first one; it does not matter, nothing is searched.
- Mycelium sends `imdb:` lookups; for a series Sonarr cannot find that way it
  resolves the TVDB id through TMDB and retries.
```

`CHANGELOG.md`: if `## [Unreleased]` is absent, insert it directly above `## [0.13.0]`. Under it, under `### Added`:

```
- Radarr/Sonarr mirror (`ARR_SYNC_ENABLED`): titles Mycelium adds are created
  in the arr as monitored, search-off entries and removed on purge, with a
  six-hourly reconcile. The arrs are bookkeeping for Seerr, Maintainerr and
  calendar widgets; they never download anything.
```

- [ ] **Step 10: Commit**

```bash
git add arr_sync.py tmdb.py processor.py upgrader.py cleanup.py app.py settings.py config.py .env.example docs/INTEGRATIONS.md CHANGELOG.md tests/test_arr_sync.py
git commit -m "feat(arr): mirror the library into Radarr/Sonarr as monitored, search-off entries

One direction: Mycelium adds on success and removes on purge, and a
six-hourly reconcile catches drift. The arrs keep no download client, so
mirrored titles show as Missing there; that is the accepted cost of Level A.

Claude-Session: https://claude.ai/code/session_01EZbQf8PvzNCADFo6bW74ko"
```

---

### Task 2: Delete webhooks (`/webhook/arr`)

**Files:**
- Create: `arr_webhook.py`
- Create: `tests/test_arr_webhook.py`
- Modify: `tmdb.py` (add `imdb_from_tvdb` after `tmdb_to_imdb`)
- Modify: `app.py:652-661` (add the route directly after `torbox_webhook`)
- Modify: `tests/test_tier1_residue.py:68-78` (the CSRF exemption pin)
- Modify: `docs/INTEGRATIONS.md`, `CHANGELOG.md`

**Interfaces:**
- Consumes: `cleanup.purge_title(imdb_id: str, row_id: int | None = None) -> dict`, `db.get_virtual_items_by_imdb(imdb_id) -> list[dict]`, `db.get_request_by_imdb(imdb_id) -> dict | None`, `tmdb.tmdb_to_imdb(tmdb_id, media_type) -> str | None`, `tmdb._get(path, params=None) -> dict | None`, `_check_auth()` and `_csrf` in `app.py`.
- Produces:
  - `arr_webhook.DeleteEvent` dataclass: `imdb_id: str | None`, `tmdb_id: int | None`, `tvdb_id: int | None`, `media_type: str` (`"movie"` or `"series"`), `source: str` (`"radarr"`, `"sonarr"`, `"jellyfin"`), `event: str`
  - `arr_webhook.parse(payload: dict) -> DeleteEvent | None` (`None` = not a delete we act on; raises `ValueError` when the payload is a delete but carries no usable id)
  - `arr_webhook.resolve_imdb(ev: DeleteEvent) -> str | None`
  - `tmdb.imdb_from_tvdb(tvdb_id: int) -> str | None`
  - Route `POST /webhook/arr`

Event mapping:

| Sender | eventType | Action |
|---|---|---|
| Radarr | `MovieDelete` | purge |
| Radarr | `MovieFileDelete` | ignore (Level B) |
| Sonarr | `SeriesDelete` | purge |
| Sonarr | `EpisodeFileDelete` | ignore (Level B) |
| Jellyfin webhook plugin | `ItemDeleted` with `itemType` `Movie` or `Series` | purge |
| Jellyfin webhook plugin | `ItemDeleted` with any other `itemType` | ignore |
| any | `Test`, `Health`, `Grab`, `Download`, anything else | ignore |

Loop safety: Task 1's `mirror_remove` makes the arr fire `MovieDelete` back at this route, and Task 3's targeted refresh makes Jellyfin fire `ItemDeleted` after a purge. Both arrive for a title Mycelium no longer knows; the route answers `ignored: unknown title` **without** calling `purge_title`, so nothing loops and no extra Jellyfin refresh is triggered.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_arr_webhook.py`:

```python
"""Deletions made elsewhere in the stack (Maintainerr via Radarr/Sonarr, a
person in Jellyfin) must reach cleanup.purge_title, or the title's rows,
monitoring and dedup keys outlive its files and a re-request is swallowed.
"""
import os
import re
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db

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


RADARR_DELETE = {
    "eventType": "MovieDelete", "instanceName": "Radarr", "deletedFiles": False,
    "movie": {"id": 3, "title": "Heat", "year": 1995, "tmdbId": 949, "imdbId": "tt0113277"},
}
SONARR_DELETE = {
    "eventType": "SeriesDelete", "instanceName": "Sonarr", "deletedFiles": False,
    "series": {"id": 5, "title": "Severance", "tvdbId": 371980, "imdbId": "tt11280740"},
}
JELLYFIN_DELETE = {
    "eventType": "ItemDeleted", "itemType": "Movie", "name": "Heat",
    "imdb": "tt0113277", "tmdb": "949",
}


def test_radarr_movie_delete_parses():
    import arr_webhook
    ev = arr_webhook.parse(RADARR_DELETE)
    assert (ev.source, ev.event, ev.media_type) == ("radarr", "MovieDelete", "movie")
    assert (ev.imdb_id, ev.tmdb_id) == ("tt0113277", 949)


def test_sonarr_series_delete_parses():
    import arr_webhook
    ev = arr_webhook.parse(SONARR_DELETE)
    assert (ev.source, ev.media_type) == ("sonarr", "series")
    assert (ev.imdb_id, ev.tvdb_id) == ("tt11280740", 371980)


def test_jellyfin_item_deleted_parses_movies_and_series():
    import arr_webhook
    ev = arr_webhook.parse(JELLYFIN_DELETE)
    assert (ev.source, ev.media_type, ev.imdb_id, ev.tmdb_id) == ("jellyfin", "movie", "tt0113277", 949)
    ev = arr_webhook.parse({**JELLYFIN_DELETE, "itemType": "Series", "tmdb": "95396"})
    assert ev.media_type == "series"


@pytest.mark.parametrize("payload", [
    {"eventType": "Test", "movie": {"imdbId": "tt0113277"}},
    {"eventType": "MovieFileDelete", "movie": {"imdbId": "tt0113277"}, "deleteReason": "manual"},
    {"eventType": "EpisodeFileDelete", "series": {"imdbId": "tt11280740"}},
    {"eventType": "Grab", "movie": {"imdbId": "tt0113277"}},
    {"eventType": "ItemDeleted", "itemType": "Episode", "imdb": "tt11280740"},
    {"eventType": "ItemDeleted", "itemType": "Season", "imdb": "tt11280740"},
    {},
])
def test_everything_else_is_ignored(payload):
    import arr_webhook
    assert arr_webhook.parse(payload) is None


def test_a_delete_without_any_id_is_an_error():
    import arr_webhook
    with pytest.raises(ValueError):
        arr_webhook.parse({"eventType": "MovieDelete", "movie": {"title": "Heat"}})


def test_jellyfin_unrendered_template_placeholders_count_as_missing():
    """The webhook plugin leaves {{Provider_imdb}} literal when the item has
    no such provider id; that must not become an imdb id."""
    import arr_webhook
    ev = arr_webhook.parse({**JELLYFIN_DELETE, "imdb": "{{Provider_imdb}}", "tmdb": "949"})
    assert ev.imdb_id is None and ev.tmdb_id == 949


def test_resolve_prefers_imdb_then_tmdb_then_tvdb(monkeypatch):
    import arr_webhook
    import tmdb
    monkeypatch.setattr(tmdb, "tmdb_to_imdb", lambda tmdb_id, media_type="movie": f"via-tmdb-{tmdb_id}-{media_type}")
    monkeypatch.setattr(tmdb, "imdb_from_tvdb", lambda tvdb_id: f"via-tvdb-{tvdb_id}")
    D = arr_webhook.DeleteEvent
    assert arr_webhook.resolve_imdb(D("tt1", 9, 8, "movie", "radarr", "MovieDelete")) == "tt1"
    assert arr_webhook.resolve_imdb(D(None, 9, 8, "series", "sonarr", "SeriesDelete")) == "via-tmdb-9-tv"
    assert arr_webhook.resolve_imdb(D(None, None, 8, "series", "sonarr", "SeriesDelete")) == "via-tvdb-8"
    assert arr_webhook.resolve_imdb(D(None, None, None, "movie", "radarr", "MovieDelete")) is None


def test_tmdb_imdb_from_tvdb_uses_the_find_endpoint(monkeypatch):
    import tmdb
    seen = {}

    def fake_get(path, params=None, timeout=10):
        seen["path"], seen["params"] = path, params
        if path.startswith("/find/"):
            return {"tv_results": [{"id": 95396}]}
        return {"imdb_id": "tt11280740"}

    monkeypatch.setattr(tmdb, "_get", fake_get)
    assert tmdb.imdb_from_tvdb(371980) == "tt11280740"
    assert seen["path"] == "/tv/95396/external_ids"


# -- the route -----------------------------------------------------------------

def _route_body():
    src = _src("app.py")
    m = re.search(r'@app\.post\("/webhook/arr"\)\s*\n\s*@_csrf\.exempt\s*\ndef arr_webhook_route\(\):\n(.*?)\n@app\.', src, re.S)
    assert m, "route /webhook/arr with @_csrf.exempt directly under @app.post not found"
    return m.group(1)


def test_route_is_a_machine_caller():
    body = _route_body()
    first_statements = "\n".join(body.splitlines()[:10])
    assert "_check_auth()" in first_statements, "the secret check must run before the payload is read"


def test_route_ignores_titles_mycelium_does_not_own():
    """Both loops (arr delete echo after mirror_remove, Jellyfin ItemDeleted
    after a purge) arrive here for a title that is already gone."""
    body = _route_body()
    assert "db.get_virtual_items_by_imdb(" in body
    assert "db.get_request_by_imdb(" in body
    assert '"unknown title"' in body


def test_route_purges_in_a_thread_and_returns_202():
    body = _route_body()
    assert "cleanup.purge_title" in body
    assert "threading.Thread(" in body
    assert "202" in body


def test_exemption_pin_includes_the_arr_webhook():
    src = _src("tests/test_tier1_residue.py")
    assert '"/webhook/arr"' in src
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv-sdd/bin/python -m pytest tests/test_arr_webhook.py -q`
Expected: `ModuleNotFoundError: No module named 'arr_webhook'` for the parser tests; `AttributeError` for `tmdb.imdb_from_tvdb`; the route tests fail on the missing source text.

- [ ] **Step 3: Add `tmdb.imdb_from_tvdb`**

In `tmdb.py`, directly after `tmdb_to_imdb` (and after Task 1's `tvdb_id_for` if it is already there):

```python
def imdb_from_tvdb(tvdb_id: int | str) -> str | None:
    """TVDB id -> IMDB id, via /find (external_source=tvdb_id) then external_ids.
    Sonarr's delete webhook carries tvdbId and sometimes no imdbId."""
    data = _get(f"/find/{tvdb_id}", params={"external_source": "tvdb_id"})
    hits = (data or {}).get("tv_results") or []
    if not hits:
        return None
    return tmdb_to_imdb(hits[0]["id"], media_type="tv")
```

- [ ] **Step 4: Write `arr_webhook.py`**

```python
"""Turn delete notifications from Radarr, Sonarr and the Jellyfin webhook
plugin into one shape the /webhook/arr route can act on.

Level A only acts on whole-title deletions. File-level events
(MovieFileDelete, EpisodeFileDelete) are accepted and ignored: Mycelium
titles have no files in the arrs until the Level B stub tree exists.
"""
import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)

_PLACEHOLDER = re.compile(r"^\s*\{\{.*\}\}\s*$")
_IMDB = re.compile(r"^tt\d+$")


@dataclass
class DeleteEvent:
    imdb_id: str | None
    tmdb_id: int | None
    tvdb_id: int | None
    media_type: str      # "movie" or "series"
    source: str          # "radarr", "sonarr", "jellyfin"
    event: str


def _clean_imdb(raw) -> str | None:
    s = str(raw or "").strip()
    return s if _IMDB.match(s) else None


def _clean_int(raw) -> int | None:
    s = str(raw or "").strip()
    if not s or _PLACEHOLDER.match(s):
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _finish(ev: DeleteEvent) -> DeleteEvent:
    if not (ev.imdb_id or ev.tmdb_id or ev.tvdb_id):
        raise ValueError(f"{ev.source} {ev.event}: no imdb, tmdb or tvdb id in payload")
    return ev


def parse(payload: dict) -> DeleteEvent | None:
    """None when this is not a whole-title deletion we act on."""
    if not isinstance(payload, dict):
        return None
    event = str(payload.get("eventType") or "")
    if event == "MovieDelete":
        m = payload.get("movie") or {}
        return _finish(DeleteEvent(_clean_imdb(m.get("imdbId")), _clean_int(m.get("tmdbId")),
                                   None, "movie", "radarr", event))
    if event == "SeriesDelete":
        s = payload.get("series") or {}
        return _finish(DeleteEvent(_clean_imdb(s.get("imdbId")), _clean_int(s.get("tmdbId")),
                                   _clean_int(s.get("tvdbId")), "series", "sonarr", event))
    if event == "ItemDeleted":
        item_type = str(payload.get("itemType") or "")
        if item_type not in ("Movie", "Series"):
            log.info("Arr webhook: ignoring Jellyfin ItemDeleted for %s", item_type or "?")
            return None
        return _finish(DeleteEvent(_clean_imdb(payload.get("imdb")), _clean_int(payload.get("tmdb")),
                                   _clean_int(payload.get("tvdb")),
                                   "movie" if item_type == "Movie" else "series",
                                   "jellyfin", event))
    if event:
        log.info("Arr webhook: ignoring %s", event)
    return None


def resolve_imdb(ev: DeleteEvent) -> str | None:
    """imdb straight from the payload, else via TMDB, else via TVDB."""
    if ev.imdb_id:
        return ev.imdb_id
    import tmdb
    kind = "movie" if ev.media_type == "movie" else "tv"
    if ev.tmdb_id:
        found = tmdb.tmdb_to_imdb(ev.tmdb_id, media_type=kind)
        if found:
            return found
    if ev.tvdb_id:
        return tmdb.imdb_from_tvdb(ev.tvdb_id)
    return None
```

- [ ] **Step 5: Add the route**

In `app.py`, directly after `torbox_webhook` (after its `return jsonify(status="ok")`, before the `# ── Dashboard` comment):

```python
@app.post("/webhook/arr")
@_csrf.exempt
def arr_webhook_route():
    """Delete notifications from Radarr (MovieDelete), Sonarr (SeriesDelete)
    and the Jellyfin webhook plugin (ItemDeleted). Same secret as /webhook.

    A title Mycelium does not own is answered with "ignored" and no purge:
    that is how the echo of our own mirror_remove, and Jellyfin's ItemDeleted
    after our own purge, are kept from looping."""
    _check_auth()
    import arr_webhook
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(status="error", error="expected a JSON object"), 400
    try:
        ev = arr_webhook.parse(payload)
    except ValueError as exc:
        log.warning("Arr webhook: %s", exc)
        return jsonify(status="error", error=str(exc)), 400
    if ev is None:
        return jsonify(status="ignored", reason="not a title deletion")
    imdb_id = arr_webhook.resolve_imdb(ev)
    if not imdb_id:
        log.warning("Arr webhook: could not resolve %s %s to an imdb id", ev.source, ev.event)
        return jsonify(status="error", error="unresolvable id"), 400
    req_row = db.get_request_by_imdb(imdb_id)
    if not req_row and not db.get_virtual_items_by_imdb(imdb_id):
        log.info("Arr webhook: %s %s for %s ignored: unknown title", ev.source, ev.event, imdb_id)
        return jsonify(status="ignored", reason="unknown title", imdb_id=imdb_id)
    log.info("Arr webhook: %s %s -> purging %s", ev.source, ev.event, imdb_id)
    threading.Thread(
        target=cleanup.purge_title,
        args=(imdb_id,), kwargs={"row_id": req_row["id"] if req_row else None},
        name=f"arr-purge-{imdb_id}", daemon=True,
    ).start()
    return jsonify(status="accepted", imdb_id=imdb_id, source=ev.source), 202
```

Confirm `cleanup` and `threading` are already imported at the top of `app.py` (both are used by existing routes).

- [ ] **Step 6: Update the CSRF exemption pin**

In `tests/test_tier1_residue.py`, `test_the_only_csrf_exemptions_are_the_machine_callers`, change the expected list to:

```python
    assert sorted(exempted) == sorted([
        "/webhook", "/torbox-webhook", "/webhook/arr",
        "/internal/stream-report/<token>"]), (
        f"the CSRF exemption set changed: {exempted}")
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv-sdd/bin/python -m pytest tests/test_arr_webhook.py tests/test_tier1_residue.py -q`
Expected: all pass.

Then: `.venv-sdd/bin/python -m pytest tests/ -q`
Expected: green.

- [ ] **Step 8: Mutation check**

In `parse`, temporarily make `MovieFileDelete` return a `DeleteEvent`; `test_everything_else_is_ignored` must fail. Revert. In the route, temporarily delete the `unknown title` early return; `test_route_ignores_titles_mycelium_does_not_own` must fail. Revert.

- [ ] **Step 9: Document**

Append to `docs/INTEGRATIONS.md` (create it with `# Integrations` if absent):

````markdown
## Delete webhooks

Mycelium owns the `.strm` library, so a deletion made anywhere else has to
reach it, or the title's database rows, monitoring and 24-hour duplicate
guard outlive the files and the next request for it is silently swallowed.

Point these at `POST https://<mycelium>/webhook/arr`. It uses the same
secret as the Seerr webhook: send it as the `X-Webhook-Secret` header
(preferred) or as `?secret=` in the URL.

**Radarr** Settings > Connect > Webhook: URL as above, method POST, tick
**On Movie Delete**. Add the secret under Headers. Leave the file-delete
events unticked; Mycelium ignores them in this version anyway.

**Sonarr** Settings > Connect > Webhook: same, tick **On Series Delete**.

**Jellyfin** (Webhook plugin): add a Generic destination with the URL above,
tick **Item Deleted**, item types Movies and Series, and use this template:

```
{"eventType":"ItemDeleted","itemType":"{{ItemType}}","name":"{{Name}}","imdb":"{{Provider_imdb}}","tmdb":"{{Provider_tmdb}}","tvdb":"{{Provider_tvdb}}"}
```

Add a request header `X-Webhook-Secret` with your secret.

What happens: a `MovieDelete`, `SeriesDelete` or `ItemDeleted` for a title
Mycelium owns runs the same purge as "Remove from library" (files, `.nfo`,
artwork, Spore stubs, database rows, monitoring, dedup keys, then a Jellyfin
refresh). Deletions of titles Mycelium does not own are answered `ignored`
and nothing happens, which is also what stops the arr echoing our own
removal back into a loop. `Test` events return `ignored` too, so the arr's
"Test" button succeeds.

Deleting a single **episode** in Jellyfin removes that `.strm` file (Jellyfin
has the rights to do so) but is not a title deletion, so it is ignored here;
the repair job may regenerate the file. Delete the series instead.
````

`CHANGELOG.md`, under `## [Unreleased]` / `### Added` (create both if absent, above `## [0.13.0]`):

```
- `/webhook/arr`: Radarr `MovieDelete`, Sonarr `SeriesDelete` and the
  Jellyfin webhook plugin's `ItemDeleted` now run the full library purge, so
  Maintainerr and deletions made in Jellyfin no longer leave rows, monitoring
  and dedup keys behind.
```

- [ ] **Step 10: Commit**

```bash
git add arr_webhook.py tmdb.py app.py tests/test_arr_webhook.py tests/test_tier1_residue.py docs/INTEGRATIONS.md CHANGELOG.md
git commit -m "feat(webhooks): purge on Radarr/Sonarr/Jellyfin delete events

Mycelium had no inbound delete signal. /webhook/arr maps MovieDelete,
SeriesDelete and ItemDeleted onto cleanup.purge_title; unknown titles are
ignored so the arr's echo of our own removal cannot loop.

Claude-Session: https://claude.ai/code/session_01EZbQf8PvzNCADFo6bW74ko"
```

---

### Task 3: Targeted Jellyfin refresh

**Files:**
- Modify: `jellyfin.py:10-78`
- Modify: `strm_generator.py:1544-1575` (`_write_strm`)
- Modify: `cleanup.py` lines 164, 188, 227, 243, 311 (deletions), 887 (the cleanup run), and `purge_title` (949+)
- Modify: `settings.py` (`HOT_RELOAD`, `connections` group), `config.py:57-58`, `.env.example:67-69`
- Create: `tests/test_targeted_refresh.py`
- Modify: `docs/INTEGRATIONS.md`, `CHANGELOG.md`

**Interfaces:**
- Consumes: `settings.get("JELLYFIN_URL")`, `settings.get("JELLYFIN_API_KEY")`, `jellyfin._jf_headers()`, `config.MEDIA_PATH`.
- Produces:
  - `jellyfin.note_change(path: str | Path, update_type: str) -> None` where `update_type` is `"Created"`, `"Modified"` or `"Deleted"`
  - `jellyfin.pending_count() -> int`
  - `jellyfin.refresh_library(timeout: int = 30, force: bool = False, full: bool = False) -> bool` (existing signature plus `full`)
  - `jellyfin._map_path(path: str) -> str`
  - Setting `JELLYFIN_MEDIA_PATH` (str, default `""`): the path at which Jellyfin's container sees Mycelium's `MEDIA_PATH`. Blank means the same path.

Behaviour of `refresh_library()` after this task:

1. `full=True`: drain the pending list and run the old `/Library/Refresh` full scan, with the old debounce and is-scanning checks. Used by the cleanup run, which renames and merges folders it cannot itemise.
2. Otherwise, if paths are pending: `POST /Library/Media/Updated` with all of them (batches of 200), no debounce, no is-scanning check. Returns `True` on 204/200. On failure the paths are put back and it falls through to the full scan so nothing is lost.
3. Otherwise: the old full-scan behaviour, unchanged. Anything that writes or deletes a path without calling `note_change` still ends up with a full scan, exactly as today.

- [ ] **Step 1: Register the setting**

`config.py`, directly after line 58 (`JELLYFIN_API_KEY = ...`):

```python
# The path at which the Jellyfin container sees MEDIA_PATH. Blank means the
# two containers mount the media at the same path. Used to translate the
# paths in targeted refresh calls (/Library/Media/Updated).
JELLYFIN_MEDIA_PATH = _env("JELLYFIN_MEDIA_PATH", "")
```

`settings.py`: add `"JELLYFIN_MEDIA_PATH",` to `HOT_RELOAD` (after `"RADARR_URL", "RADARR_API_KEY", "SONARR_URL", "SONARR_API_KEY",`) and change the `connections` group's Jellyfin line to `"JELLYFIN_URL", "JELLYFIN_API_KEY", "JELLYFIN_MEDIA_PATH",`.

`.env.example`, replace lines 67-69 with:

```
# Jellyfin: set to your own server, e.g. http://192.168.1.50:8096
JELLYFIN_URL=
JELLYFIN_API_KEY=
# Where the Jellyfin container sees MEDIA_PATH. Leave blank when both
# containers mount the media at the same path (the compose in this repo
# does). Mycelium tells Jellyfin exactly which files changed instead of
# asking for a full library scan; this translates the paths.
JELLYFIN_MEDIA_PATH=
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_targeted_refresh.py`:

```python
"""Jellyfin was asked for a full library scan after every add and purge.
/Library/Media/Updated refreshes only the paths named, which is what makes
Autopulse redundant for a Mycelium library.
"""
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db

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
    def __init__(self, status):
        self.status_code = status
        self.text = ""


@pytest.fixture
def jf(monkeypatch):
    import jellyfin
    import settings
    values = {"JELLYFIN_URL": "http://jellyfin.test", "JELLYFIN_API_KEY": "k", "JELLYFIN_MEDIA_PATH": ""}
    monkeypatch.setattr(settings, "get", lambda k, d=None: values.get(k, d))
    monkeypatch.setattr(jellyfin, "is_scanning", lambda timeout=10: False)
    jellyfin._last_refresh_ts = 0.0
    with jellyfin._pending_lock:
        jellyfin._pending.clear()
    posts = []

    def fake_post(url, headers=None, json=None, timeout=None):
        posts.append((url, json))
        return FakeResp(204)

    monkeypatch.setattr(jellyfin.requests, "post", fake_post)
    return values, posts


def test_pending_paths_go_to_media_updated_not_a_full_scan(jf):
    import jellyfin
    jellyfin.note_change("/media/movies/Heat (1995)/Heat (1995).strm", "Created")
    assert jellyfin.refresh_library() is True
    values, posts = jf
    assert len(posts) == 1
    url, body = posts[0]
    assert url == "http://jellyfin.test/Library/Media/Updated"
    assert body == {"Updates": [{"Path": "/media/movies/Heat (1995)/Heat (1995).strm", "UpdateType": "Created"}]}
    assert jellyfin.pending_count() == 0


def test_no_pending_paths_means_the_old_full_scan(jf):
    import jellyfin
    assert jellyfin.refresh_library() is True
    assert jf[1][0][0] == "http://jellyfin.test/Library/Refresh"


def test_full_true_drains_pending_and_runs_a_full_scan(jf):
    import jellyfin
    jellyfin.note_change("/media/movies/x.strm", "Deleted")
    assert jellyfin.refresh_library(full=True) is True
    assert [u for u, _ in jf[1]] == ["http://jellyfin.test/Library/Refresh"]
    assert jellyfin.pending_count() == 0


def test_targeted_refresh_ignores_the_debounce(jf):
    import jellyfin
    import time
    jellyfin._last_refresh_ts = time.monotonic()
    jellyfin.note_change("/media/movies/x.strm", "Created")
    assert jellyfin.refresh_library() is True
    assert jf[1][0][0].endswith("/Library/Media/Updated")


def test_same_path_same_type_is_sent_once(jf):
    import jellyfin
    for _ in range(3):
        jellyfin.note_change(Path("/media/movies/x.strm"), "Created")
    jellyfin.refresh_library()
    assert len(jf[1][0][1]["Updates"]) == 1


def test_paths_are_translated_to_jellyfins_mount(jf, monkeypatch):
    import jellyfin
    import config
    monkeypatch.setattr(config, "MEDIA_PATH", "/media")
    jf[0]["JELLYFIN_MEDIA_PATH"] = "/data/library"
    jellyfin.note_change("/media/series/Show/Season 01/S01E01.strm", "Created")
    jellyfin.refresh_library()
    assert jf[1][0][1]["Updates"][0]["Path"] == "/data/library/series/Show/Season 01/S01E01.strm"


def test_a_failed_targeted_post_falls_back_to_a_full_scan(jf, monkeypatch):
    import jellyfin
    calls = []

    def flaky(url, headers=None, json=None, timeout=None):
        calls.append(url)
        return FakeResp(500 if url.endswith("/Media/Updated") else 204)

    monkeypatch.setattr(jellyfin.requests, "post", flaky)
    jellyfin.note_change("/media/movies/x.strm", "Created")
    assert jellyfin.refresh_library() is True
    assert calls == ["http://jellyfin.test/Library/Media/Updated", "http://jellyfin.test/Library/Refresh"]
    assert jellyfin.pending_count() == 0


def test_large_batches_are_chunked(jf):
    import jellyfin
    for i in range(450):
        jellyfin.note_change(f"/media/movies/m{i}/m{i}.strm", "Created")
    jellyfin.refresh_library()
    sizes = [len(body["Updates"]) for _, body in jf[1]]
    assert sizes == [200, 200, 50]


# -- wiring ------------------------------------------------------------------

def test_strm_writes_are_noted_as_created():
    src = _src("strm_generator.py")
    body = src.split("def _write_strm(", 1)[1].split("\ndef ", 1)[0]
    assert 'jellyfin.note_change(path, "Created")' in body


def test_purge_notes_each_deleted_strm():
    src = _src("cleanup.py")
    body = src.split("def purge_title(", 1)[1]
    assert 'jellyfin.note_change(path, "Deleted")' in body


def test_cleanup_deletions_are_noted():
    src = _src("cleanup.py")
    assert src.count('jellyfin.note_change(') >= 6, "every unlink of a .strm in cleanup notes Deleted"


def test_the_cleanup_run_asks_for_a_full_scan():
    """Cleanup renames and merges folders it cannot itemise."""
    src = _src("cleanup.py")
    body = src.split("def _run_cleanup_locked(", 1)[1].split("\ndef ", 1)[0]
    assert "jellyfin.refresh_library(full=True)" in body


def test_setting_is_registered():
    src = _src("settings.py")
    assert '"JELLYFIN_MEDIA_PATH"' in src.split("HOT_RELOAD = {", 1)[1].split("}", 1)[0]
    assert "\nJELLYFIN_MEDIA_PATH=" in _src(".env.example")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv-sdd/bin/python -m pytest tests/test_targeted_refresh.py -q`
Expected: `AttributeError: module 'jellyfin' has no attribute '_pending_lock'` and the wiring tests fail on missing source text.

- [ ] **Step 4: Implement in `jellyfin.py`**

Replace the module header (lines 10-15, the `_REFRESH_DEBOUNCE_SEC` block) with:

```python
# Coalesce rapid successive refresh triggers (new strm right after another, an
# upgrade batch, cleanup, etc.) into a single scan instead of queueing one per call.
_REFRESH_DEBOUNCE_SEC = 60
_refresh_lock = threading.Lock()
_last_refresh_ts = 0.0

# Paths written or removed since the last refresh. When refresh_library() has
# any, it sends them to /Library/Media/Updated (a path-scoped refresh) instead
# of asking for a full library scan. Ordered, deduplicated on (path, type).
_pending_lock = threading.Lock()
_pending: dict[tuple[str, str], None] = {}
_TARGETED_BATCH = 200
```

Add after `_jf_headers()`:

```python
def note_change(path, update_type: str) -> None:
    """Record that a path was Created, Modified or Deleted, for the next refresh."""
    if update_type not in ("Created", "Modified", "Deleted"):
        raise ValueError(f"bad UpdateType {update_type!r}")
    with _pending_lock:
        _pending[(str(path), update_type)] = None


def pending_count() -> int:
    with _pending_lock:
        return len(_pending)


def _take_pending() -> list[tuple[str, str]]:
    with _pending_lock:
        items = list(_pending)
        _pending.clear()
    return items


def _map_path(path: str) -> str:
    """Translate a Mycelium path into the path Jellyfin's container sees."""
    import config
    target = (settings.get("JELLYFIN_MEDIA_PATH", "") or "").strip().rstrip("/")
    if not target:
        return path
    source = config.MEDIA_PATH.rstrip("/")
    if path == source or path.startswith(source + "/"):
        return target + path[len(source):]
    return path


def _post_targeted(base: str, items: list[tuple[str, str]], timeout: int) -> bool:
    """POST /Library/Media/Updated in batches. False on the first failure."""
    url = f"{base}/Library/Media/Updated"
    for start in range(0, len(items), _TARGETED_BATCH):
        chunk = items[start:start + _TARGETED_BATCH]
        body = {"Updates": [{"Path": _map_path(p), "UpdateType": t} for p, t in chunk]}
        resp = requests.post(url, headers=_jf_headers(), json=body, timeout=timeout)
        if resp.status_code >= 400:
            log.error("Jellyfin targeted refresh failed: %s %s", resp.status_code, resp.text[:200])
            return False
    log.info("Jellyfin targeted refresh: %d path(s)", len(items))
    return True
```

Replace `refresh_library` entirely with:

```python
def refresh_library(timeout: int = 30, force: bool = False, full: bool = False) -> bool:
    """Tell Jellyfin what changed.

    If paths were noted with note_change() since the last call, they are sent
    to /Library/Media/Updated, which refreshes only those paths. That is cheap
    enough to skip the debounce. If the targeted call fails, or nothing was
    noted, or full=True (the cleanup run, which renames and merges folders it
    cannot itemise), this falls back to a full /Library/Refresh scan.

    The full scan keeps its debounce (_REFRESH_DEBOUNCE_SEC) and its
    is-scanning check unless force=True. force exists for a person acting on
    one title: a dropped scan there looks like the title was never removed."""
    JELLYFIN_URL = settings.get("JELLYFIN_URL")
    if not JELLYFIN_URL:
        # Drop what was noted, or the list grows for the life of the process
        # on an install that has no Jellyfin.
        _take_pending()
        log.warning("JELLYFIN_URL not set; skipping library refresh")
        return False
    base = JELLYFIN_URL.rstrip("/")
    pending = _take_pending()
    if pending and not full:
        try:
            if _post_targeted(base, pending, timeout):
                return True
        except Exception as exc:
            log.warning("Jellyfin targeted refresh error: %s", exc)
        # Fall through: the paths are consumed, so a full scan must cover them.
        force = True
    with _refresh_lock:
        global _last_refresh_ts
        now = time.monotonic()
        if not force and now - _last_refresh_ts < _REFRESH_DEBOUNCE_SEC:
            log.info("Jellyfin refresh skipped: last triggered %.0fs ago", now - _last_refresh_ts)
            return False
        if not force and is_scanning(timeout=min(timeout, 10)):
            log.info("Jellyfin refresh skipped: a scan is already running")
            return False
        url = f"{base}/Library/Refresh"
        log.info("Triggering Jellyfin library refresh: %s", url)
        resp = requests.post(url, headers=_jf_headers(), timeout=timeout)
        if resp.status_code >= 400:
            log.error("Jellyfin refresh failed: %s %s", resp.status_code, resp.text[:200])
            return False
        _last_refresh_ts = now
        log.info("Jellyfin library refresh accepted (%s)", resp.status_code)
        return True
```

Note the full-scan POST now uses `_jf_headers()` (which adds `Content-Type: application/json`); Jellyfin accepts that on `/Library/Refresh`. The old code built the header inline; the behaviour is the same.

- [ ] **Step 5: Wire the producers**

`strm_generator.py`, in `_write_strm`, after `path.write_text(url, encoding='utf-8')` and before `log.info("Created .strm: %s", path)`:

```python
        path.write_text(url, encoding='utf-8')
        jellyfin.note_change(path, "Created")
        log.info("Created .strm: %s", path)
```

`jellyfin` is already imported in `strm_generator.py` (it calls `jellyfin.refresh_library()` at line 1936).

`cleanup.py`: at each of these lines, add `jellyfin.note_change(path, "Deleted")` on the line directly after the `.strm` unlink (use the variable name that line actually unlinks):

- line 164: `path.unlink()` in `_repair_strm`
- line 188: `path.unlink()` in `_repair_strm`
- line 227: `path.unlink(missing_ok=True)` in `_repair_strm`
- line 243: `path.unlink()` in `_repair_strm`
- line 311: `dup.unlink()` in `_remove_duplicates`, so `jellyfin.note_change(dup, "Deleted")`

In `purge_title`, directly after `path.unlink()` / `result["strms"] += 1`:

```python
                if path.exists():
                    path.unlink()
                    result["strms"] += 1
                    jellyfin.note_change(path, "Deleted")
```

In `_run_cleanup_locked` (line 887) change `jellyfin.refresh_library()` to `jellyfin.refresh_library(full=True)`.

Leave the six other `refresh_library()` call sites alone: `processor.py:713`, `strm_generator.py:1936`, `upgrader.py:150/223/268`, and `purge_title`'s `refresh_library(force=True)`. Each of them now finds pending paths (written through `_write_strm` or noted in `purge_title`) and sends a targeted refresh.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv-sdd/bin/python -m pytest tests/test_targeted_refresh.py -q`
Expected: all pass.

Then: `.venv-sdd/bin/python -m pytest tests/ -q`
Expected: green. If an existing test mocked `requests.post` for `/Library/Refresh` and now sees `/Library/Media/Updated`, that test wrote a `.strm` through `_write_strm` first; read it and decide whether it should note nothing (clear `jellyfin._pending` in its setup) or whether the targeted call is the correct new expectation.

- [ ] **Step 7: Mutation check**

Temporarily make `_map_path` return `path` unconditionally; `test_paths_are_translated_to_jellyfins_mount` must fail. Revert. Temporarily remove the `force = True` fall-through line; `test_a_failed_targeted_post_falls_back_to_a_full_scan` must fail. Revert.

- [ ] **Step 8: Document**

Append to `docs/INTEGRATIONS.md` (create with `# Integrations` if absent):

```markdown
## Jellyfin: targeted refresh

After an add, an upgrade or a purge, Mycelium now tells Jellyfin exactly
which files changed (`POST /Library/Media/Updated`) instead of asking for a
full library scan. New titles appear within seconds and a large library is
no longer rescanned on every request. The full scan is still used by the
cleanup job, which renames and merges folders, and as a fallback whenever
the targeted call fails.

If Jellyfin mounts the media at a different path than Mycelium does, set
`JELLYFIN_MEDIA_PATH` to Jellyfin's path (Settings > Connections). Blank
means both containers use the same path, which is what the compose in this
repo does.

**Autopulse** is redundant for a Mycelium library once this is in place; you
can keep it for other sources.

While you are in Jellyfin's library settings for the Mycelium library: turn
**off** Trickplay, chapter image extraction and intro detection for that
library. Each of those opens every file, which for a `.strm` means pulling
the whole title through the TorBox CDN and resetting its retention clock.
```

`CHANGELOG.md`, under `## [Unreleased]` / `### Changed` (create as needed):

```
- Jellyfin is told which paths changed (`/Library/Media/Updated`) after adds,
  upgrades and purges instead of being asked for a full library scan. The
  cleanup job still requests a full scan. `JELLYFIN_MEDIA_PATH` translates
  paths when the two containers mount the media differently.
```

- [ ] **Step 9: Commit**

```bash
git add jellyfin.py strm_generator.py cleanup.py settings.py config.py .env.example tests/test_targeted_refresh.py docs/INTEGRATIONS.md CHANGELOG.md
git commit -m "feat(jellyfin): refresh only the paths that changed

refresh_library() now sends noted paths to /Library/Media/Updated and
keeps the full scan for the cleanup run and as a fallback. Every .strm
write and delete notes its path. JELLYFIN_MEDIA_PATH translates paths when
the containers mount the media differently.

Claude-Session: https://claude.ai/code/session_01EZbQf8PvzNCADFo6bW74ko"
```

---

### Task 4: Seerr status reporting

**Files:**
- Create: `seerr_report.py`
- Create: `tests/test_seerr_report.py`
- Modify: `webhook_parser.py:22-28` (`MediaRequest`), and `parse()` where it constructs the `MediaRequest`
- Modify: `seerr.py` (append two functions)
- Modify: `db.py` (migration for `wanted_movies.seerr_reported`; three helpers after `touch_wanted_movie`, around line 1910)
- Modify: `processor.py` (after `db.insert_request` in `_process_locked`; the success block; the `failed` block at line 748)
- Modify: `upgrader.py:255-262` (wanted job: success and still-wanted branches)
- Modify: `settings.py` (`_BOOL_KEYS`, `_INT_KEYS`, `HOT_RELOAD`, `connections` group), `config.py:60-61`, `.env.example:71-74`
- Modify: `docs/INTEGRATIONS.md`, `CHANGELOG.md`

**Interfaces:**
- Consumes: `seerr._seerr_url()`, `seerr._headers()`, `seerr.is_configured()`, `seerr.get_request(request_id) -> dict` (Seerr request object; `["media"]["id"]` is the media id), `db.upsert_media_item(imdb_id, title, media_type, seerr_request_id=None, ...)`, `db.get_wanted_movies() -> list[dict]` (rows with `imdb_id`, `title`, `added_at`, `attempts`).
- Produces:
  - `webhook_parser.MediaRequest.seerr_request_id: int | None = None`
  - `seerr.decline_request(request_id: int) -> bool` (`POST /api/v1/request/{id}/decline`)
  - `seerr.set_media_status(request_id: int, status: str) -> bool` (`GET /api/v1/request/{id}` then `POST /api/v1/media/{mediaId}/{status}` with body `{"is4k": false}`; `status` is one of `available`, `partial`, `processing`, `pending`, `unknown`, `deleted`)
  - `db.get_seerr_request_id(imdb_id: str) -> int | None`
  - `db.get_stale_wanted_movies(older_than_days: int) -> list[dict]` (unreported rows older than the cutoff)
  - `db.mark_wanted_seerr_reported(imdb_id: str) -> None`
  - `seerr_report.on_success(imdb_id: str) -> bool`
  - `seerr_report.on_failed(imdb_id: str, reason: str) -> bool`
  - `seerr_report.report_stale_wanted() -> int` (number declined)
  - Settings: `SEERR_REPORT_STATUS` (bool, default `true`), `SEERR_DECLINE_WANTED_AFTER_DAYS` (int, default `30`, `0` disables the stale-wanted decline)

Verified against the Seerr 3.4.1 spec: `POST /request/{requestId}/{status}` accepts `approve` or `decline`; `POST /media/{mediaId}/{status}` accepts `available`, `partial`, `processing`, `pending`, `unknown`, `deleted` and an optional `{"is4k": bool}` body; request status codes are 1 pending, 2 approved, 3 declined; media status codes are 1 unknown, 2 pending, 3 processing, 4 partially available, 5 available, 6 deleted.

Mapping:

| Mycelium outcome | Seerr call | Why |
|---|---|---|
| `success` | media -> `available` | Seerr would find it on its next Jellyfin scan; this makes it immediate |
| `failed` (no suitable stream, terminal) | request -> `decline` | the "Processing" spinner stops; the user can re-request |
| `wanted` (released, nothing acceptable yet) | nothing, Mycelium keeps searching | honest: it is still processing |
| `wanted` for more than `SEERR_DECLINE_WANTED_AFTER_DAYS` | request -> `decline`, once | "no release found" after a month is a fair reading; Mycelium still keeps looking |
| `upcoming`, `rate_limited` | nothing | transient |

The Seerr request id comes from the webhook payload (`request.request_id`) and is persisted in `media_items.seerr_request_id`, the column `monitor.sync_movies` already fills for polled requests. Titles that entered through the SPA have no Seerr request and are skipped silently.

- [ ] **Step 1: Register the settings**

`config.py`, directly after line 61 (`SEERR_API_KEY = ...`):

```python
# Report outcomes back to Seerr: success marks the media available, a
# terminal failure declines the request, and a title wanted for longer than
# SEERR_DECLINE_WANTED_AFTER_DAYS is declined once (0 disables that part).
SEERR_REPORT_STATUS = _env("SEERR_REPORT_STATUS", "true").lower() == "true"
SEERR_DECLINE_WANTED_AFTER_DAYS = _env_int("SEERR_DECLINE_WANTED_AFTER_DAYS", 30)
```

`settings.py`: `"SEERR_REPORT_STATUS",` into `_BOOL_KEYS`; `"SEERR_DECLINE_WANTED_AFTER_DAYS",` into `_INT_KEYS`; both into `HOT_RELOAD`; the `connections` group's Seerr line becomes `"SEERR_URL", "SEERR_API_KEY", "SEERR_REPORT_STATUS", "SEERR_DECLINE_WANTED_AFTER_DAYS",`.

`.env.example`, replace lines 71-74 with:

```
# Seerr (Jellyseerr / Overseerr): used to look up the IMDB ID when the
# webhook does not carry it. Leave blank if you don't run Seerr.
SEERR_URL=
SEERR_API_KEY=
# Report outcomes back to Seerr so requests do not sit on "Processing"
# forever: success marks the media available at once, a title with no
# suitable stream is declined (the user can re-request), and a title that
# has been wanted for longer than the number of days below is declined once
# while Mycelium keeps searching. 0 disables the day limit.
SEERR_REPORT_STATUS=true
SEERR_DECLINE_WANTED_AFTER_DAYS=30
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_seerr_report.py`:

```python
"""Seerr shows "Processing" until something tells it otherwise. Mycelium
knew the outcome and kept it to itself.
"""
import os
import re
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db

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
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body or {}
        self.text = ""

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


@pytest.fixture
def seerr_env(monkeypatch):
    import seerr
    import settings
    values = {"SEERR_URL": "http://seerr.test", "SEERR_API_KEY": "k",
              "SEERR_REPORT_STATUS": True, "SEERR_DECLINE_WANTED_AFTER_DAYS": 30}
    monkeypatch.setattr(settings, "get", lambda k, d=None: values.get(k, d))
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(("POST", url, json))
        return FakeResp(200, {"id": 1})

    def fake_get(url, headers=None, timeout=None):
        calls.append(("GET", url, None))
        return FakeResp(200, {"id": 42, "status": 2, "media": {"id": 7, "tmdbId": 949}})

    monkeypatch.setattr(seerr.requests, "post", fake_post)
    monkeypatch.setattr(seerr.requests, "get", fake_get)
    return values, calls


# -- db ----------------------------------------------------------------------

def test_seerr_request_id_round_trips_through_media_items():
    db.upsert_media_item("tt0113277", "Heat", "movie", seerr_request_id=42)
    assert db.get_seerr_request_id("tt0113277") == 42
    assert db.get_seerr_request_id("tt0000000") is None


def test_stale_wanted_movies_are_listed_once():
    db.upsert_wanted_movie("tt0113277", 949, "Heat", "nothing acceptable")
    with db._connect() as conn:
        conn.execute("UPDATE wanted_movies SET added_at = datetime('now', '-40 days')")
        conn.commit()
    db.upsert_wanted_movie("tt0078748", 348, "Alien", "nothing acceptable")
    stale = db.get_stale_wanted_movies(30)
    assert [r["imdb_id"] for r in stale] == ["tt0113277"]
    db.mark_wanted_seerr_reported("tt0113277")
    assert db.get_stale_wanted_movies(30) == []


# -- seerr client ------------------------------------------------------------

def test_decline_posts_to_the_status_endpoint(seerr_env):
    import seerr
    assert seerr.decline_request(42) is True
    assert seerr_env[1] == [("POST", "http://seerr.test/api/v1/request/42/decline", None)]


def test_set_media_status_resolves_the_media_id_first(seerr_env):
    import seerr
    assert seerr.set_media_status(42, "available") is True
    assert seerr_env[1] == [
        ("GET", "http://seerr.test/api/v1/request/42", None),
        ("POST", "http://seerr.test/api/v1/media/7/available", {"is4k": False}),
    ]


def test_set_media_status_rejects_unknown_states(seerr_env):
    import seerr
    with pytest.raises(ValueError):
        seerr.set_media_status(42, "failed")


# -- reporter ----------------------------------------------------------------

def test_success_marks_available(seerr_env):
    import seerr_report
    db.upsert_media_item("tt0113277", "Heat", "movie", seerr_request_id=42)
    assert seerr_report.on_success("tt0113277") is True
    assert seerr_env[1][-1][1] == "http://seerr.test/api/v1/media/7/available"


def test_failed_declines(seerr_env):
    import seerr_report
    db.upsert_media_item("tt0113277", "Heat", "movie", seerr_request_id=42)
    assert seerr_report.on_failed("tt0113277", "no suitable stream found") is True
    assert seerr_env[1] == [("POST", "http://seerr.test/api/v1/request/42/decline", None)]


def test_titles_without_a_seerr_request_are_skipped(seerr_env):
    import seerr_report
    assert seerr_report.on_success("tt0113277") is False
    assert seerr_report.on_failed("tt0113277", "x") is False
    assert seerr_env[1] == []


def test_reporting_can_be_switched_off(seerr_env):
    import seerr_report
    seerr_env[0]["SEERR_REPORT_STATUS"] = False
    db.upsert_media_item("tt0113277", "Heat", "movie", seerr_request_id=42)
    assert seerr_report.on_failed("tt0113277", "x") is False
    assert seerr_env[1] == []


def test_stale_wanted_is_declined_once(seerr_env):
    import seerr_report
    db.upsert_media_item("tt0113277", "Heat", "movie", seerr_request_id=42)
    db.upsert_wanted_movie("tt0113277", 949, "Heat", "nothing acceptable")
    with db._connect() as conn:
        conn.execute("UPDATE wanted_movies SET added_at = datetime('now', '-40 days')")
        conn.commit()
    assert seerr_report.report_stale_wanted() == 1
    assert seerr_report.report_stale_wanted() == 0
    assert seerr_env[1] == [("POST", "http://seerr.test/api/v1/request/42/decline", None)]
    assert db.get_wanted_movies()[0]["imdb_id"] == "tt0113277", "Mycelium keeps searching"


def test_stale_wanted_is_off_at_zero_days(seerr_env):
    import seerr_report
    seerr_env[0]["SEERR_DECLINE_WANTED_AFTER_DAYS"] = 0
    db.upsert_media_item("tt0113277", "Heat", "movie", seerr_request_id=42)
    db.upsert_wanted_movie("tt0113277", 949, "Heat", "x")
    with db._connect() as conn:
        conn.execute("UPDATE wanted_movies SET added_at = datetime('now', '-400 days')")
        conn.commit()
    assert seerr_report.report_stale_wanted() == 0


def test_a_seerr_outage_never_raises(seerr_env, monkeypatch):
    import seerr
    import seerr_report

    def boom(*a, **k):
        raise ConnectionError("down")

    monkeypatch.setattr(seerr.requests, "post", boom)
    monkeypatch.setattr(seerr.requests, "get", boom)
    db.upsert_media_item("tt0113277", "Heat", "movie", seerr_request_id=42)
    assert seerr_report.on_success("tt0113277") is False
    assert seerr_report.on_failed("tt0113277", "x") is False


# -- wiring ------------------------------------------------------------------

def test_media_request_carries_the_seerr_request_id():
    from webhook_parser import MediaRequest
    req = MediaRequest(title="Heat", media_type="movie", imdb_id="tt0113277")
    assert req.seerr_request_id is None
    src = _src("webhook_parser.py")
    assert "seerr_request_id=" in src.split("def parse(", 1)[1]


def test_processor_persists_the_id_and_reports_both_outcomes():
    src = _src("processor.py")
    locked = src.split("def _process_locked(", 1)[1]
    assert "seerr_request_id=req.seerr_request_id" in locked.split("db.insert_request(", 1)[1][:600]
    success = locked.split("jellyfin.refresh_library()", 1)[1][:1500]
    assert "seerr_report.on_success(req.imdb_id)" in success
    failed = locked.split('db.update_request(row_id, "failed", error=reason)', 1)[1][:800]
    assert "seerr_report.on_failed(req.imdb_id, reason)" in failed


def test_wanted_job_reports_success_and_sweeps_stale():
    src = _src("upgrader.py")
    block = src.split("db.remove_wanted_movie(w[\"imdb_id\"])", 1)[1][:800]
    assert "seerr_report.on_success(w[\"imdb_id\"])" in block
    assert "seerr_report.report_stale_wanted()" in src


def test_settings_are_registered():
    src = _src("settings.py")
    assert '"SEERR_REPORT_STATUS"' in src.split("_BOOL_KEYS = {", 1)[1].split("}", 1)[0]
    assert '"SEERR_DECLINE_WANTED_AFTER_DAYS"' in src.split("_INT_KEYS = {", 1)[1].split("}", 1)[0]
    env = _src(".env.example")
    assert "\nSEERR_REPORT_STATUS=" in env and "\nSEERR_DECLINE_WANTED_AFTER_DAYS=" in env
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `.venv-sdd/bin/python -m pytest tests/test_seerr_report.py -q`
Expected: `AttributeError` on `db.get_seerr_request_id`, `seerr.decline_request`; `ModuleNotFoundError` for `seerr_report`; wiring tests fail on source text.

- [ ] **Step 4: `db.py` helpers and migration**

In `db.init()`, next to the existing `PRAGMA table_info(requests)` migration (around line 380), add:

```python
        wanted_cols = {r["name"] for r in conn.execute("PRAGMA table_info(wanted_movies)")}
        if "seerr_reported" not in wanted_cols:
            conn.execute("ALTER TABLE wanted_movies ADD COLUMN seerr_reported INTEGER NOT NULL DEFAULT 0")
            log.info("Migration: added wanted_movies.seerr_reported")
```

Directly after `touch_wanted_movie` (around line 1910):

```python
def get_stale_wanted_movies(older_than_days: int) -> list[dict]:
    """Wanted movies older than the cutoff that Seerr has not been told about."""
    with _connect() as conn:
        rows = conn.execute(
            """SELECT * FROM wanted_movies
               WHERE seerr_reported = 0
                 AND added_at < datetime('now', ?)
               ORDER BY added_at""",
            (f"-{int(older_than_days)} days",),
        ).fetchall()
        return [dict(r) for r in rows]


def mark_wanted_seerr_reported(imdb_id: str) -> None:
    with _connect() as conn:
        conn.execute("UPDATE wanted_movies SET seerr_reported = 1 WHERE imdb_id=?", (imdb_id,))
        conn.commit()


def get_seerr_request_id(imdb_id: str) -> int | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT seerr_request_id FROM media_items "
            "WHERE imdb_id=? AND seerr_request_id IS NOT NULL LIMIT 1",
            (imdb_id,),
        ).fetchone()
        return int(row["seerr_request_id"]) if row else None
```

- [ ] **Step 5: `seerr.py` client functions**

Append to `seerr.py`:

```python
_MEDIA_STATES = ("available", "partial", "processing", "pending", "unknown", "deleted")


def decline_request(request_id: int, timeout: int = 10) -> bool:
    """POST /request/{id}/decline. Needs MANAGE_REQUESTS on the API key's user."""
    base = _seerr_url()
    if not base:
        return False
    resp = requests.post(f"{base.rstrip('/')}/api/v1/request/{request_id}/decline",
                         headers=_headers(), timeout=timeout)
    if resp.status_code >= 400:
        log.warning("Seerr decline of request %s failed: %s %s", request_id, resp.status_code, resp.text[:200])
        return False
    return True


def set_media_status(request_id: int, status: str, timeout: int = 10) -> bool:
    """Resolve the request's media id, then POST /media/{mediaId}/{status}."""
    if status not in _MEDIA_STATES:
        raise ValueError(f"bad Seerr media status {status!r}")
    base = _seerr_url()
    if not base:
        return False
    media_id = ((get_request(request_id, timeout=timeout).get("media") or {}).get("id"))
    if not media_id:
        log.warning("Seerr request %s has no media id", request_id)
        return False
    resp = requests.post(f"{base.rstrip('/')}/api/v1/media/{media_id}/{status}",
                         headers=_headers(), json={"is4k": False}, timeout=timeout)
    if resp.status_code >= 400:
        log.warning("Seerr media %s -> %s failed: %s %s", media_id, status, resp.status_code, resp.text[:200])
        return False
    return True
```

- [ ] **Step 6: `seerr_report.py`**

```python
"""Report request outcomes back to Seerr.

Seerr shows "Processing" from approval until something says otherwise. It
learns about success on its own eventually (its Jellyfin scan), and never
learns about failure. This closes both: success is reported at once, a
terminal failure declines the request so the person can re-request, and a
title that has been wanted for longer than SEERR_DECLINE_WANTED_AFTER_DAYS
is declined once while Mycelium keeps searching.

Only titles that came in through Seerr have a request id; everything else
is skipped silently. Every function is best-effort and never raises.
"""
import logging

import db
import seerr
import settings as _settings

log = logging.getLogger(__name__)


def _enabled() -> bool:
    return bool(_settings.get("SEERR_REPORT_STATUS", True)) and seerr.is_configured()


def _request_id(imdb_id: str) -> int | None:
    try:
        return db.get_seerr_request_id(imdb_id)
    except Exception as exc:
        log.debug("seerr_report: lookup of %s failed: %s", imdb_id, exc)
        return None


def on_success(imdb_id: str) -> bool:
    if not _enabled():
        return False
    rid = _request_id(imdb_id)
    if not rid:
        return False
    try:
        ok = seerr.set_media_status(rid, "available")
    except Exception as exc:
        log.warning("seerr_report: could not mark %s available: %s", imdb_id, exc)
        return False
    if ok:
        log.info("Seerr: request %s (%s) marked available", rid, imdb_id)
    return ok


def on_failed(imdb_id: str, reason: str) -> bool:
    if not _enabled():
        return False
    rid = _request_id(imdb_id)
    if not rid:
        return False
    try:
        ok = seerr.decline_request(rid)
    except Exception as exc:
        log.warning("seerr_report: could not decline %s: %s", imdb_id, exc)
        return False
    if ok:
        log.info("Seerr: request %s (%s) declined: %s", rid, imdb_id, reason)
    return ok


def report_stale_wanted() -> int:
    """Decline, once, every wanted movie older than the configured cutoff."""
    if not _enabled():
        return 0
    days = int(_settings.get("SEERR_DECLINE_WANTED_AFTER_DAYS", 30) or 0)
    if days <= 0:
        return 0
    declined = 0
    for row in db.get_stale_wanted_movies(days):
        if on_failed(row["imdb_id"], f"no acceptable release after {days} days"):
            declined += 1
        # Mark it either way. A row with no Seerr id can never be reported,
        # and a decline that failed on a Seerr outage is not worth retrying
        # on every run for a title that is a month old already.
        db.mark_wanted_seerr_reported(row["imdb_id"])
    return declined
```

- [ ] **Step 7: Wire it**

`webhook_parser.py`, `MediaRequest`: add the field after `tmdb_id`:

```python
    tmdb_id: int | None = None
    seerr_request_id: int | None = None
```

In `parse()`, where the `MediaRequest(...)` is constructed, pass `seerr_request_id=_to_int(_extract_request_id(payload))`. Add the tiny helper next to `_extract_request_id`:

```python
def _to_int(raw) -> int | None:
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None
```

`processor.py`, `_process_locked`, directly after `row_id = db.insert_request(...)`:

```python
    if req.seerr_request_id:
        try:
            db.upsert_media_item(req.imdb_id, req.title, req.media_type,
                                 seerr_request_id=req.seerr_request_id)
        except Exception as exc:
            log.debug("media_items upsert skipped: %s", exc)
```

In the success block, directly after Task 1's `arr_sync` hook (or directly after `jellyfin.refresh_library()` if Task 1 has not landed):

```python
        try:
            import seerr_report
            seerr_report.on_success(req.imdb_id)
        except Exception as exc:
            log.debug("seerr_report skipped: %s", exc)
```

In the failed block, directly after `db.update_request(row_id, "failed", error=reason)`:

```python
        try:
            import seerr_report
            seerr_report.on_failed(req.imdb_id, reason)
        except Exception as exc:
            log.debug("seerr_report skipped: %s", exc)
```

`upgrader.py`, in `recheck_wanted()` (line 228): inside `if ok:` after `db.remove_wanted_movie(w["imdb_id"])` (after Task 1's hook if present):

```python
            try:
                import seerr_report
                seerr_report.on_success(w["imdb_id"])
            except Exception as exc:
                log.debug("seerr_report skipped: %s", exc)
```

and at the end of `recheck_wanted()`, directly before its `return added` (line 270):

```python
    try:
        import seerr_report
        seerr_report.report_stale_wanted()
    except Exception as exc:
        log.debug("seerr_report stale sweep skipped: %s", exc)
    return added
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `.venv-sdd/bin/python -m pytest tests/test_seerr_report.py -q`
Expected: all pass.

Then: `.venv-sdd/bin/python -m pytest tests/ -q`
Expected: green.

- [ ] **Step 9: Mutation check**

Temporarily remove `db.mark_wanted_seerr_reported(...)` from `report_stale_wanted`; `test_stale_wanted_is_declined_once` must fail on the second call. Revert. Temporarily change `"available"` to `"processing"` in `on_success`; `test_success_marks_available` must fail. Revert.

- [ ] **Step 10: Document**

Append to `docs/INTEGRATIONS.md` (create with `# Integrations` if absent):

```markdown
## Seerr: outcome reporting

With `SEERR_REPORT_STATUS=true` (the default) Mycelium reports back to Seerr
for every request that came in through the Seerr webhook:

| Mycelium outcome | Seerr |
|---|---|
| Added | media marked **Available** at once, no need to wait for Seerr's Jellyfin scan |
| No suitable stream (terminal) | request **Declined**; the person can re-request |
| Released but nothing acceptable yet | left as **Processing**, Mycelium keeps searching |
| Still nothing after `SEERR_DECLINE_WANTED_AFTER_DAYS` (default 30) | request **Declined** once; Mycelium keeps searching anyway |

The Seerr API key must belong to a user with **Manage Requests** (an admin
key does). Titles added from Mycelium's own Discover, Trakt or MDBList have
no Seerr request and are not reported.
```

`CHANGELOG.md`, under `## [Unreleased]` / `### Added`:

```
- Seerr outcome reporting (`SEERR_REPORT_STATUS`): success marks the media
  available immediately, a terminal failure declines the request, and a
  title wanted for longer than `SEERR_DECLINE_WANTED_AFTER_DAYS` is declined
  once. Requests no longer sit on "Processing" forever.
```

- [ ] **Step 11: Commit**

```bash
git add seerr_report.py seerr.py db.py webhook_parser.py processor.py upgrader.py settings.py config.py .env.example tests/test_seerr_report.py docs/INTEGRATIONS.md CHANGELOG.md
git commit -m "feat(seerr): report outcomes so requests stop showing Processing forever

Success marks the media available at once, a terminal failure declines the
request, and a title wanted for longer than SEERR_DECLINE_WANTED_AFTER_DAYS
is declined once while Mycelium keeps searching. The Seerr request id from
the webhook is now persisted in media_items.

Claude-Session: https://claude.ai/code/session_01EZbQf8PvzNCADFo6bW74ko"
```

---

## After all four tasks

- Run the whole suite once more: `.venv-sdd/bin/python -m pytest tests/ -q`.
- Read `docs/INTEGRATIONS.md` top to bottom: four sections, one heading, no duplicated intro line.
- Add a one-line pointer to it in `README.md` under `## ⚙️ Configuration`, directly after the `Full reference:` line: `Talking to the rest of the stack (Radarr, Sonarr, Seerr, Jellyfin webhooks and targeted refresh): [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md).`
- Do not cut a release from this plan; the user decides when.

## Self-review

**Spec coverage.** Arr mirror on every Mycelium-originated add: `processor._process_locked` is the funnel for the Seerr webhook, Discover, trending, Trakt, MDBList and auto-approve (all go through `_kick_off_processing` or `/webhook` into `processor.process`), plus the wanted-movie job's own success path; covered by Task 1 hooks and the reconcile. Remove on purge: Task 1. Delete webhook for Radarr, Sonarr, Jellyfin: Task 2, with the loop guard. Targeted refresh replacing the seven full-scan call sites: Task 3, six become targeted through the pending list, the cleanup run stays full by design. Seerr status: Task 4, including the stale-wanted case the user described as "spinning forever". Jellyfin Trickplay/intro-detection warning: documented in Task 3's docs section rather than built into the health card (that was surfaced as a separate follow-up, not part of Level A).

**Placeholder scan.** No TBD/TODO, every code step has its code, every test is written out, no "similar to Task N".

**Type consistency.** `arr_sync.mirror_add(imdb_id, media_type, tmdb_id=None, title="")` and `mirror_remove(imdb_id, media_type, tmdb_id=None)` match their calls in `processor.py`, `upgrader.py`, `cleanup.py` and the reconcile test's monkeypatched lambda. `jellyfin.note_change(path, update_type)` matches every producer. `seerr_report.on_success(imdb_id)`, `on_failed(imdb_id, reason)`, `report_stale_wanted()` match the wiring tests. `arr_webhook.DeleteEvent` positional order `(imdb_id, tmdb_id, tvdb_id, media_type, source, event)` matches `test_resolve_prefers_imdb_then_tmdb_then_tvdb`. `tmdb.tvdb_id_for` (Task 1) and `tmdb.imdb_from_tvdb` (Task 2) are distinct names in distinct tasks.
