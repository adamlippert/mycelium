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
    monkeypatch.setattr(arr_sync, "_ensure_with_stubs",
                        lambda imdb, mt, tmdb_id, title, write_stubs=True: (added.append(imdb) or "added", 0))
    out = arr_sync.reconcile()
    assert added == ["tt0113277"]
    assert out == {"checked": 2, "added": 1, "present": 0, "failed": 0, "skipped": 1, "stubs": 0, "purged": 0}


def test_reconcile_is_a_noop_when_disabled(monkeypatch):
    import arr_sync
    import settings
    monkeypatch.setattr(settings, "get", lambda k, d=None: {"ARR_SYNC_ENABLED": False}.get(k, d))
    assert arr_sync.reconcile() == {"checked": 0, "added": 0, "present": 0, "failed": 0, "skipped": 0, "stubs": 0, "purged": 0}


class _FakeListResp:
    def __init__(self, body):
        self._body = body
        self.status_code = 200

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


def test_radarr_list_movies_exposes_id_and_path(monkeypatch):
    """reconcile() needs id and path from the listing to write a stub and
    rescan a known title without a separate lookup call."""
    import radarr
    body = [{"id": 10, "tmdbId": 949, "imdbId": "tt0113277", "title": "Heat", "year": 1995,
            "monitored": True, "hasFile": False, "path": "/movies/Heat (1995)"}]
    monkeypatch.setattr(radarr.requests, "get", lambda *a, **k: _FakeListResp(body))
    out = radarr.list_movies("http://radarr.test", "k")
    assert out[0]["id"] == 10
    assert out[0]["path"] == "/movies/Heat (1995)"


def test_sonarr_list_series_exposes_id_and_path(monkeypatch):
    import sonarr
    body = [{"id": 7, "tvdbId": 371980, "tmdbId": 95396, "imdbId": "tt11280740",
            "title": "Severance", "year": 2022, "monitored": True, "seasons": [],
            "path": "/tv/Severance"}]
    monkeypatch.setattr(sonarr.requests, "get", lambda *a, **k: _FakeListResp(body))
    out = sonarr.list_series("http://sonarr.test", "k")
    assert out[0]["id"] == 7
    assert out[0]["path"] == "/tv/Severance"


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
    assert out == {"checked": 1, "added": 0, "present": 1, "failed": 0, "skipped": 0, "stubs": 0, "purged": 0}
    assert not [c for c in fake.calls if c[0] == "POST"]


# -- Level B: stubs ------------------------------------------------------------

@pytest.fixture
def stubs_on(enabled, tmp_path, monkeypatch):
    import config
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    media = tmp_path / "media"
    monkeypatch.setattr(config, "MEDIA_PATH", str(media))
    enabled.update({"ARR_STUBS_ENABLED": True, "ARR_STUB_PATH": str(stubs), "CATBOX_MODE": True,
                    "RADARR_ROOT_FOLDER": "/mnt/arr/movies", "SONARR_ROOT_FOLDER": "/mnt/arr/series"})
    import tmdb
    monkeypatch.setattr(tmdb, "get_movie_runtime_sec", lambda imdb: 5400)
    monkeypatch.setattr(tmdb, "get_episode_runtime_sec", lambda imdb, s, e: 2700)
    folder = media / "movies" / "Heat (1995)"
    folder.mkdir(parents=True)
    strm = folder / "Heat (1995).strm"
    strm.write_text("http://x/stream/abc")
    db.insert_request("Heat", "tt0113277", "movie", tmdb_id=949)
    db.update_request(db.get_request_by_imdb("tt0113277")["id"], "success", quality="1080p")
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, strm_path, imdb_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("tok1", "h" * 40, f"magnet:?xt=urn:btih:{'h' * 40}&dn=Heat.1995.1080p.WEB-DL.x264",
             "Heat", "movie", str(strm), "tt0113277"))
        conn.commit()
    return stubs


def test_add_writes_the_stub_into_the_arr_folder_and_asks_for_a_rescan(stubs_on, monkeypatch):
    import arr_sync
    fake = FakeArr({
        ("GET", "/movie/lookup"): (200, RADARR_LOOKUP),
        ("GET", "/movie"): (200, []),
        ("GET", "/qualityprofile"): (200, [{"id": 4}]),
        ("GET", "/rootfolder"): (200, [{"path": "/mnt/arr/movies"}]),
        ("POST", "/movie"): (201, {"id": 10, "path": "/mnt/arr/movies/Heat (1995)"}),
        ("POST", "/command"): (201, {"id": 1}),
    })
    monkeypatch.setattr(arr_sync, "_request", fake)
    assert arr_sync.mirror_add("tt0113277", "movie", 949, "Heat") is True
    assert (stubs_on / "movies" / "Heat (1995)" / "Heat (1995) - WEBDL-1080p.mkv").exists()
    cmd = [c for c in fake.calls if c[1] == "/command"]
    assert cmd and cmd[0][3] == {"name": "RescanMovie", "movieId": 10}


def test_present_title_gets_its_stub_too(stubs_on, monkeypatch):
    """Backfill: a title the arr already has (Level A left it Missing)."""
    import arr_sync
    fake = FakeArr({
        ("GET", "/movie/lookup"): (200, RADARR_LOOKUP),
        ("GET", "/movie"): (200, [{"id": 10, "tmdbId": 949, "path": "/mnt/arr/movies/Heat (1995)"}]),
        ("POST", "/command"): (201, {"id": 1}),
    })
    monkeypatch.setattr(arr_sync, "_request", fake)
    assert arr_sync.mirror_add("tt0113277", "movie", 949, "Heat") is True
    assert (stubs_on / "movies" / "Heat (1995)" / "Heat (1995) - WEBDL-1080p.mkv").exists()
    assert [c for c in fake.calls if c[1] == "/command"]


def test_no_rescan_when_nothing_was_written(stubs_on, monkeypatch):
    import arr_sync
    fake = FakeArr({
        ("GET", "/movie/lookup"): (200, RADARR_LOOKUP),
        ("GET", "/movie"): (200, [{"id": 10, "tmdbId": 949, "path": "/mnt/arr/movies/Heat (1995)"}]),
        ("POST", "/command"): (201, {"id": 1}),
    })
    monkeypatch.setattr(arr_sync, "_request", fake)
    arr_sync.mirror_add("tt0113277", "movie", 949, "Heat")
    fake.calls.clear()
    arr_sync.mirror_add("tt0113277", "movie", 949, "Heat")
    assert not [c for c in fake.calls if c[1] == "/command"], "idempotent: no second rescan"


def test_remove_deletes_the_stubs_before_the_arr_entry(stubs_on, monkeypatch):
    """Order matters: with the stub gone first, the arr's own delete has no
    file to report, so no MovieFileDelete echoes back at the webhook."""
    import arr_sync
    fake = FakeArr({
        ("GET", "/movie/lookup"): (200, RADARR_LOOKUP),
        ("GET", "/movie"): (200, [{"id": 10, "tmdbId": 949, "path": "/mnt/arr/movies/Heat (1995)"}]),
        ("POST", "/command"): (201, {"id": 1}),
        ("DELETE", "/movie/10"): (200, None),
    })
    monkeypatch.setattr(arr_sync, "_request", fake)
    arr_sync.mirror_add("tt0113277", "movie", 949, "Heat")
    folder = stubs_on / "movies" / "Heat (1995)"
    assert folder.exists()
    existed_at_delete = {}
    real_request = fake

    def spying(method, url, key, *, params=None, json=None):
        if method == "DELETE":
            existed_at_delete["folder"] = folder.exists()
        return real_request(method, url, key, params=params, json=json)

    monkeypatch.setattr(arr_sync, "_request", spying)
    assert arr_sync.mirror_remove("tt0113277", "movie", 949) is True
    assert existed_at_delete == {"folder": False}
    assert not folder.exists()


def test_stub_failure_does_not_fail_the_add(stubs_on, monkeypatch):
    import arr_stubs
    import arr_sync
    monkeypatch.setattr(arr_stubs, "write_title", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    fake = FakeArr({
        ("GET", "/movie/lookup"): (200, RADARR_LOOKUP),
        ("GET", "/movie"): (200, [{"id": 10, "tmdbId": 949, "path": "/mnt/arr/movies/Heat (1995)"}]),
    })
    monkeypatch.setattr(arr_sync, "_request", fake)
    assert arr_sync.mirror_add("tt0113277", "movie", 949, "Heat") is True


def test_reconcile_backfills_stubs_and_reports_them(stubs_on, monkeypatch):
    import arr_sync
    import radarr
    import sonarr
    monkeypatch.setattr(radarr, "list_movies", lambda u, k: [])
    monkeypatch.setattr(sonarr, "list_series", lambda u, k: [])
    fake = FakeArr({
        ("GET", "/movie/lookup"): (200, RADARR_LOOKUP),
        ("GET", "/movie"): (200, [{"id": 10, "tmdbId": 949, "path": "/mnt/arr/movies/Heat (1995)"}]),
        ("POST", "/command"): (201, {"id": 1}),
    })
    monkeypatch.setattr(arr_sync, "_request", fake)
    out = arr_sync.reconcile()
    assert out == {"checked": 1, "added": 0, "present": 1, "failed": 0, "skipped": 0, "stubs": 1, "purged": 0}
    assert (stubs_on / "movies" / "Heat (1995)" / "Heat (1995) - WEBDL-1080p.mkv").exists()


def test_reconcile_backfills_a_title_the_arr_already_lists(enabled, stubs_on, monkeypatch):
    """The have-set short-circuit must not skip the stub backfill when
    Level B is on: a title Level A already left "Missing" in the arr still
    needs its stub written. With stubs off, the old short-circuit applies
    again and the listing is never even looked up."""
    import arr_sync
    import radarr
    import sonarr
    monkeypatch.setattr(radarr, "list_movies", lambda u, k: [
        {"imdb_id": "tt0113277", "tmdb_id": 949, "id": 10, "path": "/mnt/arr/movies/Heat (1995)"}])
    monkeypatch.setattr(sonarr, "list_series", lambda u, k: [])
    fake = FakeArr({
        ("POST", "/command"): (201, {"id": 1}),
    })
    monkeypatch.setattr(arr_sync, "_request", fake)
    out = arr_sync.reconcile()
    assert out == {"checked": 1, "added": 0, "present": 1, "failed": 0, "skipped": 0, "stubs": 1, "purged": 0}
    assert (stubs_on / "movies" / "Heat (1995)" / "Heat (1995) - WEBDL-1080p.mkv").exists()
    assert not [c for c in fake.calls if c[1] == "/movie/lookup"], \
        "known title with stubs on: the listing entry is enough, no lookup needed"

    enabled["ARR_STUBS_ENABLED"] = False
    fake.calls.clear()
    arr_sync.reconcile()
    assert not [c for c in fake.calls if c[1] == "/movie/lookup"]


def test_reconcile_warns_once_when_the_stub_root_is_missing(enabled, stubs_on, monkeypatch, caplog):
    """The stub root was checked once per item before this fix; a missing
    mount then warned once per title, every reconcile. One check, one
    warning, and neither the listing path nor _ensure_with_stubs writes a
    stub for the rest of the run."""
    import arr_sync
    import radarr
    import sonarr
    enabled["ARR_STUB_PATH"] = str(stubs_on / "gone")
    monkeypatch.setattr(radarr, "list_movies", lambda u, k: [])
    monkeypatch.setattr(sonarr, "list_series", lambda u, k: [])
    fake = FakeArr({
        ("GET", "/movie/lookup"): (200, RADARR_LOOKUP),
        ("GET", "/movie"): (200, [{"id": 10, "tmdbId": 949, "path": "/mnt/arr/movies/Heat (1995)"}]),
    })
    monkeypatch.setattr(arr_sync, "_request", fake)
    with caplog.at_level("WARNING"):
        out = arr_sync.reconcile()
    assert out["stubs"] == 0
    warnings = [r for r in caplog.records if "Arr stubs" in r.getMessage()]
    assert len(warnings) == 1, warnings


def test_present_via_lookup_id_still_writes_the_stub(stubs_on, monkeypatch):
    """found.get("id") is enough to call a title present; that branch must
    still hand its object (with path) to the stub writer without a
    needless call to /movie."""
    import arr_sync
    fake = FakeArr({
        ("GET", "/movie/lookup"): (200, [{**RADARR_LOOKUP[0], "id": 10,
                                          "path": "/mnt/arr/movies/Heat (1995)"}]),
        ("POST", "/command"): (201, {"id": 1}),
    })
    monkeypatch.setattr(arr_sync, "_request", fake)
    assert arr_sync.mirror_add("tt0113277", "movie", 949, "Heat") is True
    assert (stubs_on / "movies" / "Heat (1995)" / "Heat (1995) - WEBDL-1080p.mkv").exists()
    assert not [c for c in fake.calls if c[0] == "GET" and c[1] == "/movie"]
    assert [c for c in fake.calls if c[1] == "/command"]


# -- deletions made elsewhere: the reconcile is the source of truth ------------

@pytest.fixture
def mirrored(enabled, tmp_path, monkeypatch):
    """Two successful movies, both mirrored earlier, both with a .strm on disk."""
    import config
    media = tmp_path / "media"
    monkeypatch.setattr(config, "MEDIA_PATH", str(media))
    rows = {}
    with db._connect() as conn:
        for imdb, tmdb, title in (("tt0113277", 949, "Heat"), ("tt0078748", 348, "Alien")):
            folder = media / "movies" / f"{title} (1)"
            folder.mkdir(parents=True)
            strm = folder / f"{title} (1).strm"
            strm.write_text("http://x/stream/t")
            rid = db.insert_request(title, imdb, "movie", tmdb_id=tmdb)
            db.update_request(rid, "success")
            conn.execute(
                "INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, strm_path, imdb_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"tok-{imdb}", "h" * 40, "magnet:?xt=urn:btih:" + "h" * 40, title, "movie", str(strm), imdb))
            rows[imdb] = {"id": rid, "strm": strm, "tmdb": tmdb}
        # Mirrored well before now, so the "still being processed" grace does not apply.
        conn.execute("UPDATE requests SET updated_at = datetime('now', '-1 day')")
        conn.commit()
    for imdb in rows:
        db.mark_arr_mirrored(imdb)
    with db._connect() as conn:
        conn.execute("UPDATE requests SET arr_mirrored_at = datetime('now', '-1 day')")
        conn.commit()
    purged = []
    import cleanup
    monkeypatch.setattr(cleanup, "purge_title", lambda imdb, row_id=None: purged.append(imdb) or {})
    import radarr
    import sonarr
    monkeypatch.setattr(sonarr, "list_series", lambda u, k: [])
    return rows, purged, radarr


def _radarr_confirms_absent(monkeypatch):
    """Radarr can match the title (lookup) but holds no entry for it (GET /movie
    by tmdbId is empty): the confirming check answers 'absent'."""
    import arr_sync
    fake = FakeArr({
        ("GET", "/movie/lookup"): (200, RADARR_LOOKUP),
        ("GET", "/movie"): (200, []),
    })
    monkeypatch.setattr(arr_sync, "_request", fake)
    return fake


def test_a_successful_add_marks_the_title_as_mirrored(enabled, monkeypatch):
    import arr_sync
    db.insert_request("Heat", "tt0113277", "movie", tmdb_id=949)
    fake = FakeArr({
        ("GET", "/movie/lookup"): (200, RADARR_LOOKUP),
        ("GET", "/movie"): (200, [{"id": 10, "tmdbId": 949, "path": "/movies/Heat (1995)"}]),
    })
    monkeypatch.setattr(arr_sync, "_request", fake)
    assert db.get_request_by_imdb("tt0113277")["arr_mirrored_at"] is None
    arr_sync.mirror_add("tt0113277", "movie", 949, "Heat")
    assert db.get_request_by_imdb("tt0113277")["arr_mirrored_at"] is not None


def test_reconcile_purges_a_mirrored_title_the_arr_no_longer_lists(mirrored, monkeypatch):
    """A delete made in Radarr while the webhook was missed used to be undone
    by the reconcile re-adding the title. The marker tells the two cases apart."""
    import arr_sync
    rows, purged, radarr = mirrored
    monkeypatch.setattr(radarr, "list_movies", lambda u, k: [{"imdb_id": "tt0078748", "tmdb_id": 348, "id": 2, "path": "/movies/Alien (1)"}])
    fake = _radarr_confirms_absent(monkeypatch)
    out = arr_sync.reconcile()
    assert purged == ["tt0113277"], "Heat was mirrored and is gone from Radarr"
    assert out["purged"] == 1
    assert not [c for c in fake.calls if c[0] == "POST"], "never re-added"
    assert ("GET", "/movie", {"tmdbId": 949}, None) in fake.calls, "absence was confirmed with Radarr first"


def test_reconcile_still_adds_a_title_that_was_never_mirrored(mirrored, monkeypatch):
    import arr_sync
    rows, purged, radarr = mirrored
    with db._connect() as conn:
        conn.execute("UPDATE requests SET arr_mirrored_at = NULL WHERE imdb_id = 'tt0113277'")
        conn.commit()
    monkeypatch.setattr(radarr, "list_movies", lambda u, k: [{"imdb_id": "tt0078748", "tmdb_id": 348, "id": 2, "path": "/movies/Alien (1)"}])
    added = []
    monkeypatch.setattr(arr_sync, "_ensure_with_stubs",
                        lambda imdb, mt, tmdb_id, title, write_stubs=True: added.append(imdb) or ("added", 0))
    out = arr_sync.reconcile()
    assert added == ["tt0113277"] and purged == [] and out["purged"] == 0


def test_reconcile_refuses_to_purge_when_the_arr_listing_is_empty(mirrored, monkeypatch, caplog):
    """An empty or collapsed listing is a rebuilt or half-broken arr, not a
    hundred deletions. Mirror of the 'never delete from the arrs' rule."""
    import arr_sync
    rows, purged, radarr = mirrored
    monkeypatch.setattr(radarr, "list_movies", lambda u, k: [])
    _radarr_confirms_absent(monkeypatch)
    readded = []
    monkeypatch.setattr(arr_sync, "_ensure_with_stubs",
                        lambda imdb, *a, **k: readded.append(imdb) or ("added", 0))
    with caplog.at_level("WARNING"):
        out = arr_sync.reconcile()
    assert purged == [] and out["purged"] == 0
    assert any("refusing to purge" in r.message for r in caplog.records)
    assert sorted(readded) == ["tt0078748", "tt0113277"], "a refused purge falls back to re-adding"
    assert out["added"] == 2


def test_reconcile_refuses_to_purge_when_most_mirrored_titles_vanished(mirrored, monkeypatch):
    import arr_sync
    rows, purged, radarr = mirrored
    # Five mirrored titles, Radarr lists only one: 80 percent gone at once.
    with db._connect() as conn:
        for i in range(3):
            rid = db.insert_request(f"X{i}", f"tt000000{i}", "movie", tmdb_id=100 + i)
            db.update_request(rid, "success")
        conn.execute("UPDATE requests SET arr_mirrored_at = datetime('now', '-1 day'), "
                     "updated_at = datetime('now', '-1 day')")
        conn.commit()
    monkeypatch.setattr(radarr, "list_movies", lambda u, k: [{"imdb_id": "tt0078748", "tmdb_id": 348, "id": 2, "path": "/x"}])
    _radarr_confirms_absent(monkeypatch)
    monkeypatch.setattr(arr_sync, "_ensure_with_stubs", lambda *a, **k: ("present", 0))
    out = arr_sync.reconcile()
    assert purged == [] and out["purged"] == 0





def test_a_series_sonarr_lists_without_ids_is_confirmed_present_not_purged(mirrored, monkeypatch):
    """Sonarr is tvdb-first and often lists a series with no imdb or tmdb id.
    Absent from the listing is not absent from Sonarr: the reconcile asks
    before believing it, or a mirrored series would purge itself on the
    second pass."""
    import arr_sync
    import sonarr
    rows, purged, radarr = mirrored
    monkeypatch.setattr(radarr, "list_movies", lambda u, k: [
        {"imdb_id": "tt0113277", "tmdb_id": 949, "id": 1, "path": "/x"},
        {"imdb_id": "tt0078748", "tmdb_id": 348, "id": 2, "path": "/y"}])
    rid = db.insert_request("Severance", "tt11280740", "series", tmdb_id=95396)
    db.update_request(rid, "success")
    db.mark_arr_mirrored("tt11280740")
    with db._connect() as conn:
        conn.execute("UPDATE requests SET arr_mirrored_at = datetime('now', '-1 day'), "
                     "updated_at = datetime('now', '-1 day')")
        conn.commit()
    monkeypatch.setattr(sonarr, "list_series", lambda u, k: [{"imdb_id": "", "tmdb_id": None, "tvdb_id": 371980, "id": 7, "path": "/s"}])
    fake = FakeArr({("GET", "/series/lookup"): (200, [{**SONARR_LOOKUP[0], "id": 7}])})
    monkeypatch.setattr(arr_sync, "_request", fake)
    out = arr_sync.reconcile()
    assert purged == []
    assert out["present"] == 1 and out["purged"] == 0
    assert not [c for c in fake.calls if c[0] == "POST"]


def test_a_title_the_arr_cannot_confirm_is_never_purged(mirrored, monkeypatch):
    """Lookup failing, or the arr not even matching the title, is 'unknown':
    the add path handles it and nothing is deleted."""
    import arr_sync
    rows, purged, radarr = mirrored
    monkeypatch.setattr(radarr, "list_movies", lambda u, k: [{"imdb_id": "tt0078748", "tmdb_id": 348, "id": 2, "path": "/y"}])
    monkeypatch.setattr(arr_sync, "_request", FakeArr({}))
    out = arr_sync.reconcile()
    assert purged == [] and out["purged"] == 0 and out["failed"] == 1


def test_a_title_mirrored_moments_ago_is_not_purged_for_missing_from_the_listing(mirrored, monkeypatch):
    """The listing is a snapshot taken before a loop that can run for minutes;
    a title mirrored during that window is absent from it and is not gone."""
    import arr_sync
    rows, purged, radarr = mirrored
    with db._connect() as conn:
        conn.execute("UPDATE requests SET arr_mirrored_at = datetime('now') WHERE imdb_id = 'tt0113277'")
        conn.commit()
    monkeypatch.setattr(radarr, "list_movies", lambda u, k: [{"imdb_id": "tt0078748", "tmdb_id": 348, "id": 2, "path": "/y"}])
    fake = _radarr_confirms_absent(monkeypatch)
    out = arr_sync.reconcile()
    assert purged == [] and out["purged"] == 0
    assert not [c for c in fake.calls if c[0] == "POST"]



def test_an_unconfigured_arr_never_purges_its_kind(mirrored, monkeypatch):
    """No Radarr URL means no Radarr listing to be absent from."""
    import arr_sync
    rows, purged, radarr = mirrored
    monkeypatch.setattr(radarr, "list_movies", lambda u, k: (_ for _ in ()).throw(AssertionError("not called")))
    monkeypatch.setattr(arr_sync, "_conn", lambda kind: ("", "") if kind == "radarr" else ("http://sonarr.test", "sk"))
    out = arr_sync.reconcile()
    assert purged == [] and out["purged"] == 0


def test_purge_can_be_switched_off_and_falls_back_to_re_adding(mirrored, monkeypatch):
    import arr_sync
    import settings
    rows, purged, radarr = mirrored
    values = {"ARR_SYNC_PURGE_ENABLED": False, "ARR_SYNC_ENABLED": True,
              "RADARR_URL": "http://radarr.test", "RADARR_API_KEY": "rk",
              "SONARR_URL": "http://sonarr.test", "SONARR_API_KEY": "sk"}
    monkeypatch.setattr(settings, "get", lambda k, d=None: values.get(k, d))
    monkeypatch.setattr(radarr, "list_movies", lambda u, k: [{"imdb_id": "tt0078748", "tmdb_id": 348, "id": 2, "path": "/y"}])
    _radarr_confirms_absent(monkeypatch)
    readded = []
    monkeypatch.setattr(arr_sync, "_ensure_with_stubs",
                        lambda imdb, *a, **k: readded.append(imdb) or ("added", 0))
    out = arr_sync.reconcile()
    assert purged == [] and out["purged"] == 0 and readded == ["tt0113277"]
    assert "ARR_SYNC_PURGE_ENABLED" in _src("settings.py")


def test_a_purge_by_the_reconcile_leaves_an_activity_row(mirrored, monkeypatch):
    import arr_sync
    rows, purged, radarr = mirrored
    monkeypatch.setattr(radarr, "list_movies", lambda u, k: [{"imdb_id": "tt0078748", "tmdb_id": 348, "id": 2, "path": "/y"}])
    _radarr_confirms_absent(monkeypatch)
    arr_sync.reconcile()
    rows_ = [r for r in db.get_activity(20) if r["event"] == "purged"]
    assert rows_ and "Radarr" in rows_[0]["message"]


def test_the_mirror_column_is_added_to_an_existing_database(tmp_path, monkeypatch):
    """Upgrade path: a pre-0.16 requests table gains arr_mirrored_at, and the
    tmdb_id backfill stays under its own guard."""
    import sqlite3
    _drop_cached_conn()
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE requests (id INTEGER PRIMARY KEY, title TEXT, imdb_id TEXT UNIQUE, media_type TEXT,
            status TEXT, created_at TEXT, updated_at TEXT);
        INSERT INTO requests (title, imdb_id, media_type, status) VALUES ('Heat', 'tt0113277', 'movie', 'success');
    """)
    conn.commit(); conn.close()
    monkeypatch.setattr(db, "DB_PATH", str(path))
    _drop_cached_conn()
    db.init()
    with db._connect() as conn:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(requests)")}
    assert "arr_mirrored_at" in cols and "tmdb_id" in cols
    assert db.get_request_by_imdb("tt0113277")["arr_mirrored_at"] is None
    src = _src("db.py")
    assert src.index('if "tmdb_id" not in req_cols') < src.index("backfilled requests.tmdb_id") \
        < src.index('if "arr_mirrored_at" not in req_cols')


def test_a_failed_path_update_rolls_the_folder_rename_back():
    """cleanup.rename_messy_series_folders: folder and DB must agree, or the
    reconcile sees a title whose files are 'gone'."""
    src = _src("cleanup.py")
    assert "renaming back" in src and "new_folder.rename(folder)" in src


def test_a_kind_without_an_arr_is_counted_as_skipped_not_failed(enabled, monkeypatch):
    """Radarr only: series rows are not this arr's business."""
    import arr_sync
    import radarr
    enabled.update({"SONARR_URL": "", "SONARR_API_KEY": ""})
    rid = db.insert_request("Severance", "tt11280740", "series", tmdb_id=95396)
    db.update_request(rid, "success")
    monkeypatch.setattr(radarr, "list_movies", lambda u, k: [])
    out = arr_sync.reconcile()
    assert out["failed"] == 0 and out["skipped"] == 1 and out["purged"] == 0


def test_reconcile_interval_is_a_setting():
    src = _src("app.py")
    assert "ARR_SYNC_INTERVAL_MINUTES" in src.split("arr_sync.reconcile", 1)[1][:400]
    assert "\nARR_SYNC_INTERVAL_MINUTES=" in _src(".env.example")
