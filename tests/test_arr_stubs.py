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
        "ARR_STUBS_ENABLED": True, "ARR_SYNC_ENABLED": True,
        "ARR_STUB_PATH": str(stubs),
        "RADARR_ROOT_FOLDER": "/mnt/arr/movies", "SONARR_ROOT_FOLDER": "/mnt/arr/series",
    }
    monkeypatch.setattr(settings, "get", lambda k, d=None: values.get(k, d))
    monkeypatch.setattr(tmdb, "get_movie_runtime_sec", lambda imdb: 5400)
    monkeypatch.setattr(tmdb, "get_episode_runtime_sec", lambda imdb, s, e: 2700)
    return values, media, stubs


def _movie(media, imdb="tt0113277", quality="1080p", dn="Heat.1995.1080p.WEB-DL.x264"):
    folder = media / "movies" / "Heat (1995)"
    folder.mkdir(parents=True, exist_ok=True)
    strm = folder / "Heat (1995).strm"
    strm.write_text("http://x/stream/abc")
    db.insert_request("Heat", imdb, "movie", tmdb_id=949)
    db.update_request(db.get_request_by_imdb(imdb)["id"], "success", quality=quality)
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, strm_path, imdb_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("tok1", "h" * 40, f"magnet:?xt=urn:btih:{'h' * 40}&dn={dn}", "Heat", "movie", str(strm), imdb),
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


def test_write_title_is_idempotent(stubs_env):
    import arr_stubs
    values, media, stubs = stubs_env
    _movie(media)
    arr_stubs.write_title("tt0113277", "movie", "/mnt/arr/movies/Heat (1995)")
    mkv = stubs / "movies" / "Heat (1995)" / "Heat (1995) - WEBDL-1080p.mkv"
    before = mkv.stat().st_mtime_ns
    assert arr_stubs.write_title("tt0113277", "movie", "/mnt/arr/movies/Heat (1995)") == 0
    assert mkv.stat().st_mtime_ns == before


def test_write_title_places_episodes_in_their_season_folders(stubs_env):
    import arr_stubs
    values, media, stubs = stubs_env
    _series(media)
    assert arr_stubs.write_title("tt11280740", "series", "/mnt/arr/series/Severance") == 2
    season = stubs / "series" / "Severance" / "Season 01"
    assert sorted(p.name for p in season.glob("*.mkv")) == [
        "Severance - S01E01 - WEBDL-2160p.mkv", "Severance - S01E02 - WEBDL-2160p.mkv"]
    assert (stubs / "series" / "Severance" / ".mycelium").read_text().strip() == "tt11280740"


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
