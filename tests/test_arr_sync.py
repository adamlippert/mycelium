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
    monkeypatch.setattr(arr_sync, "_ensure",
                        lambda imdb, mt, tmdb_id, title: added.append(imdb) or "added")
    out = arr_sync.reconcile()
    assert added == ["tt0113277"]
    assert out == {"checked": 2, "added": 1, "present": 0, "failed": 0, "skipped": 1}


def test_reconcile_is_a_noop_when_disabled(monkeypatch):
    import arr_sync
    import settings
    monkeypatch.setattr(settings, "get", lambda k, d=None: {"ARR_SYNC_ENABLED": False}.get(k, d))
    assert arr_sync.reconcile() == {"checked": 0, "added": 0, "present": 0, "failed": 0, "skipped": 0}


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


# -- hygiene batch after the whole-branch review ------------------------------

def test_a_changed_root_folder_setting_is_picked_up_without_a_restart(enabled, monkeypatch):
    """Settings > Radarr / Sonarr has a root-folder dropdown now; a pick that
    only takes effect after a restart is a bug, not a cache."""
    import arr_sync
    fake = FakeArr({
        ("GET", "/movie/lookup"): (200, RADARR_LOOKUP),
        ("GET", "/movie"): (200, []),
        ("GET", "/qualityprofile"): (200, [{"id": 4}]),
        ("GET", "/rootfolder"): (200, [{"path": "/movies"}]),
        ("POST", "/movie"): (201, {"id": 10}),
    })
    monkeypatch.setattr(arr_sync, "_request", fake)
    assert arr_sync.mirror_add("tt0113277", "movie", 949, "Heat") is True
    enabled["RADARR_ROOT_FOLDER"] = "/mnt/new"
    assert arr_sync.mirror_add("tt0113277", "movie", 949, "Heat") is True
    roots = [c[3]["rootFolderPath"] for c in fake.calls if c[0] == "POST"]
    assert roots == ["/movies", "/mnt/new"]


def test_arr_calls_do_not_hold_the_title_lock_for_long():
    """A success can make up to six arr calls while the per-title lock is
    held; 15 s each was too generous for a bookkeeping mirror."""
    import arr_sync
    assert arr_sync._TIMEOUT <= 8


def test_reconcile_does_not_count_already_present_as_added(enabled, monkeypatch):
    """Sonarr reports a series with no imdb or tmdb id, so it is missing
    from the have-set, the lookup then finds it already added, and that
    used to be counted as an add."""
    import arr_sync
    import radarr
    import sonarr
    db.insert_request("Severance", "tt11280740", "series", tmdb_id=95396)
    db.update_request(db.get_request_by_imdb("tt11280740")["id"], "success")
    monkeypatch.setattr(radarr, "list_movies", lambda u, k: [])
    monkeypatch.setattr(sonarr, "list_series", lambda u, k: [{"imdb_id": "", "tmdb_id": None, "tvdb_id": 371980}])
    fake = FakeArr({
        ("GET", "/series/lookup"): (200, [{**SONARR_LOOKUP[0], "id": 7}]),
    })
    monkeypatch.setattr(arr_sync, "_request", fake)
    out = arr_sync.reconcile()
    assert out == {"checked": 1, "added": 0, "present": 1, "failed": 0, "skipped": 0}
    assert not [c for c in fake.calls if c[0] == "POST"]
