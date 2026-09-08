"""Stub files so Radarr and Sonarr hold a real file per title.

Truthful naming: the quality tag is what Mycelium found. The stub is the
Spore MKV header with a Segment Duration, so the arrs' sample detection
(runtime first, size second) accepts a few kilobytes as a film.
"""
import os
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


@pytest.fixture
def stubs_env(tmp_path, monkeypatch):
    """Enabled, with MEDIA_PATH, ARR_STUB_PATH and the arr root folders all
    under tmp_path. The arr sees /mnt/arr/movies where Mycelium sees
    <tmp>/stubs/movies."""
    import arr_stubs
    import config
    import settings
    import tmdb
    media = tmp_path / "media"
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    monkeypatch.setattr(config, "MEDIA_PATH", str(media))
    values = {
        "ARR_STUBS_ENABLED": True, "ARR_SYNC_ENABLED": True, "CATBOX_MODE": True,
        "ARR_STUB_PATH": str(stubs),
        "RADARR_URL": "http://radarr.test", "SONARR_URL": "http://sonarr.test",
        "RADARR_ROOT_FOLDER": "/mnt/arr/movies", "SONARR_ROOT_FOLDER": "/mnt/arr/series",
    }
    monkeypatch.setattr(settings, "get", lambda k, d=None: values.get(k, d))
    monkeypatch.setattr(tmdb, "get_movie_runtime_sec", lambda imdb: 5400)
    monkeypatch.setattr(tmdb, "get_episode_runtime_sec", lambda imdb, s, e: 2700)
    return values, media, stubs


def _movie(media, imdb="tt0113277", quality="1080p", dn="Heat.1995.1080p.WEB-DL.x264", source=None):
    folder = media / "movies" / "Heat (1995)"
    folder.mkdir(parents=True, exist_ok=True)
    strm = folder / "Heat (1995).strm"
    strm.write_text("http://x/stream/abc")
    db.insert_request("Heat", imdb, "movie", tmdb_id=949)
    db.update_request(db.get_request_by_imdb(imdb)["id"], "success", quality=quality)
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, strm_path, imdb_id, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("tok1", "h" * 40, f"magnet:?xt=urn:btih:{'h' * 40}&dn={dn}" if dn else f"magnet:?xt=urn:btih:{'h' * 40}",
             "Heat", "movie", str(strm), imdb, source),
        )
        conn.commit()
    return strm


def _series(media, imdb="tt11280740"):
    db.insert_request("Severance", imdb, "series", tmdb_id=95396)
    db.update_request(db.get_request_by_imdb(imdb)["id"], "success", quality="2160p")
    paths = []
    with db._connect() as conn:
        for ep in (1, 2):
            folder = media / "series" / "Severance" / "Season 01"
            folder.mkdir(parents=True, exist_ok=True)
            strm = folder / f"Severance - S01E0{ep}.strm"
            strm.write_text("http://x/stream/e")
            conn.execute(
                "INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, strm_path, imdb_id, season, episode) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (f"tok{ep}", "h" * 40, f"magnet:?xt=urn:btih:{'h' * 40}&dn=Severance.S01.2160p.WEB-DL.HEVC",
                 "Severance", "series", str(strm), imdb, 1, ep),
            )
            paths.append(strm)
        conn.commit()
    return paths


# -- pure --------------------------------------------------------------------

@pytest.mark.parametrize("resolution,name,expected", [
    ("1080p", "Heat.1995.1080p.WEB-DL.x264", "WEBDL-1080p"),
    ("2160p", "Heat.1995.2160p.UHD.BluRay.REMUX", "Remux-2160p"),
    ("1080p", "Heat.1995.1080p.BluRay.x264", "Bluray-1080p"),
    ("720p", "Heat.1995.720p.WEBRip.x264", "WEBRip-720p"),
    ("1080p", "Heat.1995.1080p.HDTV.x264", "HDTV-1080p"),
    ("480p", "Heat.1995.DVDRip.XviD", "DVD-480p"),
    ("1080p", "Heat.1995.x264", "1080p"),
    (None, "Heat.1995.WEB-DL", "WEBDL"),
    (None, "", ""),
])
def test_quality_tag_maps_onto_the_arr_vocabulary(resolution, name, expected):
    import arr_stubs
    assert arr_stubs.quality_tag(resolution, name) == expected


def test_stub_name_keeps_the_strm_stem_and_adds_the_tag():
    import arr_stubs
    assert arr_stubs.stub_name(Path("/m/movies/Heat (1995)/Heat (1995).strm"), "WEBDL-1080p") == "Heat (1995) - WEBDL-1080p.mkv"
    assert arr_stubs.stub_name(Path("/m/x/Untagged.strm"), "") == "Untagged.mkv"


def test_local_dir_swaps_the_arr_root_for_ours(stubs_env):
    import arr_stubs
    values, media, stubs = stubs_env
    assert arr_stubs.local_dir("movie", "/mnt/arr/movies/Heat (1995)") == stubs / "movies" / "Heat (1995)"
    assert arr_stubs.local_dir("series", "/mnt/arr/series/Severance") == stubs / "series" / "Severance"
    assert arr_stubs.local_dir("movie", "/somewhere/else/Heat (1995)") is None, "outside the arr root: refuse"
    assert arr_stubs.local_dir("movie", "/mnt/arr/movies/../../etc") is None, "no escaping the tree"


def test_is_enabled_needs_the_mirror_too(stubs_env):
    import arr_stubs
    assert arr_stubs.is_enabled() is True
    stubs_env[0]["ARR_SYNC_ENABLED"] = False
    assert arr_stubs.is_enabled() is False


# -- writing -----------------------------------------------------------------

def test_write_title_writes_a_stub_and_a_marker_into_the_arr_folder(stubs_env):
    import arr_stubs
    values, media, stubs = stubs_env
    _movie(media)
    assert arr_stubs.write_title("tt0113277", "movie", "/mnt/arr/movies/Heat (1995)") == 1
    folder = stubs / "movies" / "Heat (1995)"
    mkv = folder / "Heat (1995) - WEBDL-1080p.mkv"
    assert mkv.exists()
    assert mkv.read_bytes()[:4] == b"\x1a\x45\xdf\xa3", "EBML magic"
    assert (folder / ".mycelium").read_text().strip() == "tt0113277"
    assert (stubs / ".ignore").exists(), "a Jellyfin library pointed here skips it"


def test_write_title_tags_the_stub_from_the_source_column(stubs_env):
    """Scraper magnets never carry a dn= name, so the release label stored in
    virtual_items.source is what names the stub."""
    import arr_stubs
    values, media, stubs = stubs_env
    _movie(media, dn="", source="BluRay")
    assert arr_stubs.write_title("tt0113277", "movie", "/mnt/arr/movies/Heat (1995)") == 1
    assert (stubs / "movies" / "Heat (1995)" / "Heat (1995) - Bluray-1080p.mkv").exists()


def test_write_title_falls_back_to_the_magnet_name_without_a_source(stubs_env):
    import arr_stubs
    values, media, stubs = stubs_env
    _movie(media, dn="Heat.1995.1080p.WEBRip.x264", source=None)
    assert arr_stubs.write_title("tt0113277", "movie", "/mnt/arr/movies/Heat (1995)") == 1
    assert (stubs / "movies" / "Heat (1995)" / "Heat (1995) - WEBRip-1080p.mkv").exists()


def test_write_title_replaces_a_stale_stub_after_an_upgrade(stubs_env):
    import arr_stubs
    values, media, stubs = stubs_env
    _movie(media)
    arr_stubs.write_title("tt0113277", "movie", "/mnt/arr/movies/Heat (1995)")
    with db._connect() as conn:
        conn.execute("UPDATE requests SET quality='2160p'")
        conn.execute("UPDATE virtual_items SET magnet=?", (f"magnet:?xt=urn:btih:{'h' * 40}&dn=Heat.1995.2160p.BluRay.x265",))
        conn.commit()
    assert arr_stubs.write_title("tt0113277", "movie", "/mnt/arr/movies/Heat (1995)") == 1
    names = sorted(p.name for p in (stubs / "movies" / "Heat (1995)").glob("*.mkv"))
    assert names == ["Heat (1995) - Bluray-2160p.mkv"]


def test_sweep_never_deletes_a_file_that_is_not_our_stub(stubs_env):
    import arr_stubs
    values, media, stubs = stubs_env
    _movie(media)
    folder = stubs / "movies" / "Heat (1995)"
    folder.mkdir(parents=True)
    foreign = folder / "Some Real File.mkv"
    foreign.write_bytes(b"not a stub" * 5)
    assert arr_stubs.write_title("tt0113277", "movie", "/mnt/arr/movies/Heat (1995)") == 1
    assert foreign.exists()
    assert foreign.read_bytes() == b"not a stub" * 5


def test_a_stub_renamed_by_the_arr_is_kept_not_duplicated(stubs_env):
    import arr_stubs
    values, media, stubs = stubs_env
    _movie(media)
    assert arr_stubs.write_title("tt0113277", "movie", "/mnt/arr/movies/Heat (1995)") == 1
    folder = stubs / "movies" / "Heat (1995)"
    old = folder / "Heat (1995) - WEBDL-1080p.mkv"
    renamed = folder / "Heat (1995) WEBDL-1080p [Radarr].mkv"
    old.rename(renamed)
    assert arr_stubs.write_title("tt0113277", "movie", "/mnt/arr/movies/Heat (1995)") == 0
    mkvs = list(folder.glob("*.mkv"))
    assert len(mkvs) == 1
    assert mkvs[0] == renamed


def test_equivalent_does_not_match_a_more_specific_tag(stubs_env):
    import arr_stubs
    values, media, stubs = stubs_env
    folder = stubs / "movies" / "Heat (1995)"
    folder.mkdir(parents=True)
    (folder / "Heat (1995) - WEBDL-1080p.mkv").write_bytes(b"\x1a\x45\xdf\xa3stub")
    assert arr_stubs._equivalent(folder, "Heat (1995)", "1080p") is None


def test_equivalent_never_matches_an_empty_tag(stubs_env):
    import arr_stubs
    values, media, stubs = stubs_env
    folder = stubs / "movies" / "Heat (1995)"
    folder.mkdir(parents=True)
    (folder / "Heat (1995) - WEBDL-1080p.mkv").write_bytes(b"\x1a\x45\xdf\xa3stub")
    assert arr_stubs._equivalent(folder, "Heat (1995)", "") is None


def test_write_title_skips_items_whose_strm_is_gone(stubs_env):
    import arr_stubs
    values, media, stubs = stubs_env
    paths = _series(media)
    paths[0].unlink()
    assert arr_stubs.write_title("tt11280740", "series", "/mnt/arr/series/Severance") == 1
    season = stubs / "series" / "Severance" / "Season 01"
    assert sorted(p.name for p in season.glob("*.mkv")) == ["Severance - S01E02 - WEBDL-2160p.mkv"]


def test_write_title_is_idempotent(stubs_env):
    import arr_stubs
    values, media, stubs = stubs_env
    _movie(media)
    arr_stubs.write_title("tt0113277", "movie", "/mnt/arr/movies/Heat (1995)")
    mkv = stubs / "movies" / "Heat (1995)" / "Heat (1995) - WEBDL-1080p.mkv"
    before = mkv.stat().st_mtime_ns
    assert arr_stubs.write_title("tt0113277", "movie", "/mnt/arr/movies/Heat (1995)") == 0
    assert mkv.stat().st_mtime_ns == before


def test_write_title_places_episodes_in_their_season_folders(stubs_env, monkeypatch):
    import arr_stubs
    import tmdb
    values, media, stubs = stubs_env
    calls = []

    def counting_runtime(imdb, season, episode):
        calls.append((imdb, season, episode))
        return 2700

    monkeypatch.setattr(tmdb, "get_episode_runtime_sec", counting_runtime)
    _series(media)
    assert arr_stubs.write_title("tt11280740", "series", "/mnt/arr/series/Severance") == 2
    season = stubs / "series" / "Severance" / "Season 01"
    assert sorted(p.name for p in season.glob("*.mkv")) == [
        "Severance - S01E01 - WEBDL-2160p.mkv", "Severance - S01E02 - WEBDL-2160p.mkv"]
    assert (stubs / "series" / "Severance" / ".mycelium").read_text().strip() == "tt11280740"
    assert len(calls) == 1, "one runtime lookup reused for every stub in the call, not one per episode"


def test_write_title_uses_the_tmdb_runtime(stubs_env, monkeypatch):
    import arr_stubs
    import strm_generator
    seen = {}

    def fake_make(title, quality=None, duration_sec=7200.0, **kw):
        seen["duration"] = duration_sec
        seen["quality"] = quality
        return b"\x1a\x45\xdf\xa3stub"

    monkeypatch.setattr(strm_generator, "make_stub_mkv", fake_make)
    values, media, stubs = stubs_env
    _movie(media)
    # The request row says 1080p (the _movie default); the virtual item's own
    # quality, which write_title must prefer for both the stub and the file
    # name, is bumped to 2160p here.
    with db._connect() as conn:
        conn.execute("UPDATE virtual_items SET quality='2160p'")
        conn.commit()
    arr_stubs.write_title("tt0113277", "movie", "/mnt/arr/movies/Heat (1995)")
    assert seen["duration"] == 5400
    assert seen["quality"] == "2160p"
    assert (stubs / "movies" / "Heat (1995)" / "Heat (1995) - WEBDL-2160p.mkv").exists()


def test_write_title_survives_a_db_failure(stubs_env, monkeypatch):
    import arr_stubs
    values, media, stubs = stubs_env
    _movie(media)

    def _boom(*a, **kw):
        raise RuntimeError("db is down")

    monkeypatch.setattr(db, "get_virtual_items_by_imdb", _boom)
    assert arr_stubs.write_title("tt0113277", "movie", "/mnt/arr/movies/Heat (1995)") == 0


def test_write_title_does_nothing_when_disabled_or_unmounted(stubs_env):
    import arr_stubs
    values, media, stubs = stubs_env
    _movie(media)
    values["ARR_STUBS_ENABLED"] = False
    assert arr_stubs.write_title("tt0113277", "movie", "/mnt/arr/movies/Heat (1995)") == 0
    values["ARR_STUBS_ENABLED"] = True
    values["ARR_STUB_PATH"] = str(stubs / "not-mounted")
    assert arr_stubs.write_title("tt0113277", "movie", "/mnt/arr/movies/Heat (1995)") == 0
    assert not (stubs / "not-mounted").exists(), "never create the mount point ourselves"


def test_root_status_reports_a_missing_mount(stubs_env):
    import arr_stubs
    values, media, stubs = stubs_env
    assert arr_stubs.root_status() == (True, str(stubs))
    values["ARR_STUB_PATH"] = str(stubs / "gone")
    ok, note = arr_stubs.root_status()
    assert ok is False and "not mounted" in note
    values["ARR_STUB_PATH"] = str(stubs)
    values["RADARR_ROOT_FOLDER"] = ""
    ok, note = arr_stubs.root_status()
    assert ok is False and "RADARR_ROOT_FOLDER" in note
    values["RADARR_ROOT_FOLDER"] = "/mnt/arr/movies"
    values["SONARR_URL"] = ""
    values["SONARR_ROOT_FOLDER"] = ""
    assert arr_stubs.root_status() == (True, str(stubs)), \
        "no Sonarr configured: its root folder is not required"


def test_root_status_requires_a_root_folder_only_for_a_configured_arr(stubs_env):
    import arr_stubs
    values, media, stubs = stubs_env
    values["SONARR_URL"] = ""
    values["SONARR_ROOT_FOLDER"] = ""
    assert arr_stubs.root_status() == (True, str(stubs)), "Sonarr not configured: ok without its root folder"
    values["RADARR_URL"] = ""
    values["RADARR_ROOT_FOLDER"] = ""
    assert arr_stubs.root_status() == (True, str(stubs)), "neither arr configured: still ok"
    values["SONARR_URL"] = "http://sonarr.test"
    ok, note = arr_stubs.root_status()
    assert ok is False and "SONARR_ROOT_FOLDER" in note, "Sonarr configured again: its root folder is required"


def test_root_status_needs_catbox_mode(stubs_env):
    import arr_stubs
    values, media, stubs = stubs_env
    values["CATBOX_MODE"] = False
    ok, note = arr_stubs.root_status()
    assert ok is False and "CATBOX_MODE" in note


def test_a_relative_stub_path_is_refused(stubs_env):
    import arr_stubs
    values, media, stubs = stubs_env
    values["ARR_STUB_PATH"] = "relative/stubs"
    ok, note = arr_stubs.root_status()
    assert ok is False and "not an absolute path" in note
    assert arr_stubs.write_title("tt0113277", "movie", "/mnt/arr/movies/Heat (1995)") == 0
    assert arr_stubs.remove_title("movie", "tt0113277", "/mnt/arr/movies/Heat (1995)") == 0


# -- removing ----------------------------------------------------------------

def test_remove_title_by_arr_path(stubs_env):
    import arr_stubs
    values, media, stubs = stubs_env
    _movie(media)
    arr_stubs.write_title("tt0113277", "movie", "/mnt/arr/movies/Heat (1995)")
    assert arr_stubs.remove_title("movie", "tt0113277", "/mnt/arr/movies/Heat (1995)") == 1
    assert not (stubs / "movies" / "Heat (1995)").exists()


def test_remove_title_finds_the_folder_by_marker_when_the_arr_is_unreachable(stubs_env):
    """The arr may have renamed the folder or be down at purge time; the
    .mycelium marker is what says a folder is this title's."""
    import arr_stubs
    values, media, stubs = stubs_env
    _movie(media)
    arr_stubs.write_title("tt0113277", "movie", "/mnt/arr/movies/Heat (1995)")
    (stubs / "movies" / "Heat (1995)").rename(stubs / "movies" / "Heat (1995) [renamed]")
    assert arr_stubs.remove_title("movie", "tt0113277") == 1
    assert list((stubs / "movies").iterdir()) == []


def test_remove_title_never_deletes_a_folder_without_our_marker(stubs_env):
    import arr_stubs
    values, media, stubs = stubs_env
    foreign = stubs / "movies" / "Heat (1995)"
    foreign.mkdir(parents=True)
    (foreign / "Heat (1995).mkv").write_bytes(b"real file")
    assert arr_stubs.remove_title("movie", "tt0113277", "/mnt/arr/movies/Heat (1995)") == 0
    assert (foreign / "Heat (1995).mkv").exists()


def test_remove_title_treats_a_corrupt_marker_as_not_ours(stubs_env):
    import arr_stubs
    values, media, stubs = stubs_env
    folder = stubs / "movies" / "Heat (1995)"
    folder.mkdir(parents=True)
    (folder / arr_stubs.MARKER).write_bytes(b"\xff\xfe")
    assert arr_stubs.remove_title("movie", "tt0113277", "/mnt/arr/movies/Heat (1995)") == 0
    assert folder.exists()


def test_settings_are_registered():
    src = _src("settings.py")
    assert '"ARR_STUBS_ENABLED"' in src.split("_BOOL_KEYS = {", 1)[1].split("}", 1)[0]
    hot = src.split("HOT_RELOAD = {", 1)[1].split("}", 1)[0]
    assert '"ARR_STUBS_ENABLED"' in hot and '"ARR_STUB_PATH"' in hot
    env = _src(".env.example")
    assert "\nARR_STUBS_ENABLED=" in env and "\nARR_STUB_PATH=" in env


# -- hooks and health -------------------------------------------------------------

def test_upgrades_refresh_the_stubs():
    src = _src("upgrader.py")
    auto = src.split("def run_auto_upgrade(", 1)[1].split("\ndef ", 1)[0]
    assert 'arr_sync.mirror_add(row["imdb_id"], "movie", row.get("tmdb_id"), row["title"])' in auto
    assert auto.index('strm_generator._cache_cdn_url(') < auto.index('arr_sync.mirror_add(')
    catbox = src.split("def _run_auto_upgrade_catbox(", 1)[1].split("\ndef ", 1)[0]
    assert 'arr_sync.mirror_add(item["imdb_id"], "movie", item.get("tmdb_id"), item["title"])' in catbox
    # The catbox path shares its DB write with the admin swap panel via
    # release_swap.swap (action="upgraded") instead of writing the virtual
    # item inline.
    assert 'release_swap.swap(item, candidate, action="upgraded")' in catbox
    assert catbox.index('release_swap.swap(') < catbox.index('arr_sync.mirror_add(')
    pack = src.split("def run_pack_consolidation(", 1)[1].split("\ndef ", 1)[0]
    assert "arr_sync.mirror_add(" in pack
    assert pack.index('db.log_activity("consolidated"') < pack.index('arr_sync.mirror_add(')


def test_catbox_auto_upgrade_shares_release_swaps_side_effects(monkeypatch):
    """Behavioural companion to test_upgrades_refresh_the_stubs: the catbox
    auto-upgrade path really does drive release_swap.swap, so the virtual
    item, the request-adjacent DB write, and the activity log all come out
    exactly as a manual admin swap would - just labelled "upgraded"."""
    import catbox
    import debrid
    import upgrader
    from streams import Stream

    h_old, h_new = "a" * 40, "b" * 40
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, strm_path, imdb_id, quality) "
            "VALUES (?, ?, ?, 'Heat (1995)', 'movie', ?, 'tt1', '1080p')",
            ("tok1", h_old, f"magnet:?xt=urn:btih:{h_old}", "/media/tok1.strm"),
        )
        conn.commit()

    better = Stream(name="Heat.1995.2160p.BluRay.x264", title="Heat.1995.2160p.BluRay.x264",
                    info_hash=h_new, quality="2160p", seeders=10, size_gb=40.0,
                    is_season_pack=False, source="torrentio")
    monkeypatch.setattr(upgrader, "_fetch_movie_candidates", lambda imdb: [better])
    monkeypatch.setattr(debrid, "check_cached_multi", lambda hashes: {"torbox": {h_new}})
    monkeypatch.setattr(catbox, "invalidate_url_cache", lambda token=None: None)

    upgraded = upgrader._run_auto_upgrade_catbox()

    assert upgraded == 1
    item = db.get_virtual_item("tok1")
    assert item["info_hash"] == h_new and item["quality"] == "2160p" and item["source"] == "BluRay"
    act = db.get_activity_for_title("tt1", "Heat (1995)")[0]
    assert act["event"] == "upgraded"


def test_fixed_mode_auto_upgrade_stores_the_release_label_not_the_scraper_name(monkeypatch):
    """The non-catbox upgrade path (run_auto_upgrade) used to write
    better.name.split()[0], the first whitespace token of the release name.
    It must now write the same release-source label the catbox path writes,
    and NULL when the release name carries no source tag at all."""
    import jellyfin
    import settings
    import strm_generator
    import torbox
    import upgrader
    from streams import Stream

    imdb = "tt0113277"
    db.insert_request("Heat", imdb, "movie", tmdb_id=949)
    row = db.get_request_by_imdb(imdb)
    db.update_request(row["id"], "success", quality="1080p", info_hash="a" * 40)

    better = Stream(name="Heat.1995.2160p.BluRay.x264", title="Heat.1995.2160p.BluRay.x264",
                    info_hash="b" * 40, quality="2160p", seeders=10, size_gb=40.0,
                    is_season_pack=False, source="torrentio")
    monkeypatch.setattr(settings, "get", lambda k, d=None: {"AUTO_UPGRADE_ENABLED": True,
                                                             "CATBOX_MODE": False}.get(k, d))
    monkeypatch.setattr(upgrader, "_fetch_movie_candidates", lambda imdb: [better])
    monkeypatch.setattr(torbox, "check_cached", lambda hashes: {"b" * 40})
    monkeypatch.setattr(torbox, "add_magnet", lambda magnet, reason=None: None)
    monkeypatch.setattr(torbox, "wait_until_ready", lambda info_hash: {"id": "tb1"})
    monkeypatch.setattr(strm_generator, "create_strm_for_torrent", lambda *a, **k: True)
    monkeypatch.setattr(strm_generator, "_cache_cdn_url", lambda *a, **k: None)
    monkeypatch.setattr(jellyfin, "refresh_library", lambda *a, **k: None)

    upgraded = upgrader.run_auto_upgrade()

    assert upgraded == 1
    updated = db.get_request_by_imdb(imdb)
    assert updated["source"] == "BluRay"


def test_fixed_mode_auto_upgrade_stores_null_when_the_name_has_no_source_tag(monkeypatch):
    import jellyfin
    import settings
    import strm_generator
    import torbox
    import upgrader
    from streams import Stream

    imdb = "tt0113277"
    db.insert_request("Heat", imdb, "movie", tmdb_id=949)
    row = db.get_request_by_imdb(imdb)
    db.update_request(row["id"], "success", quality="1080p", info_hash="a" * 40)

    better = Stream(name="Heat.1995.2160p.DDP5.1.x264", title="Heat.1995.2160p",
                    info_hash="b" * 40, quality="2160p", seeders=10, size_gb=40.0,
                    is_season_pack=False, source="torrentio")
    monkeypatch.setattr(settings, "get", lambda k, d=None: {"AUTO_UPGRADE_ENABLED": True,
                                                             "CATBOX_MODE": False}.get(k, d))
    monkeypatch.setattr(upgrader, "_fetch_movie_candidates", lambda imdb: [better])
    monkeypatch.setattr(torbox, "check_cached", lambda hashes: {"b" * 40})
    monkeypatch.setattr(torbox, "add_magnet", lambda magnet, reason=None: None)
    monkeypatch.setattr(torbox, "wait_until_ready", lambda info_hash: {"id": "tb1"})
    monkeypatch.setattr(strm_generator, "create_strm_for_torrent", lambda *a, **k: True)
    monkeypatch.setattr(strm_generator, "_cache_cdn_url", lambda *a, **k: None)
    monkeypatch.setattr(jellyfin, "refresh_library", lambda *a, **k: None)

    upgraded = upgrader.run_auto_upgrade()

    assert upgraded == 1
    updated = db.get_request_by_imdb(imdb)
    assert updated["source"] is None


def test_health_reports_the_stub_mount(stubs_env, monkeypatch):
    import health
    monkeypatch.setattr(health, "_ping", lambda name, *a, **k: {"name": name, "status": "ok"})
    row = next(r for r in health.check_all() if r["name"] == "Arr stubs")
    assert row["status"] == "ok"
    stubs_env[0]["ARR_STUB_PATH"] = str(stubs_env[2] / "gone")
    row = next(r for r in health.check_all() if r["name"] == "Arr stubs")
    assert row["status"] == "down" and "not mounted" in row["note"]
    stubs_env[0]["ARR_STUBS_ENABLED"] = False
    row = next(r for r in health.check_all() if r["name"] == "Arr stubs")
    assert row["status"] == "disabled"
