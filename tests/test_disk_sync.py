"""On-disk deletion check: a title whose .strm files are all gone was
deleted in Jellyfin. Runs without Radarr, Sonarr or the mirror.
"""
import os
import re
import shutil
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


def _add_movie(media, imdb, tmdb, title, on_disk=True):
    folder = media / "movies" / f"{title} (1)"
    folder.mkdir(parents=True, exist_ok=True)
    strm = folder / f"{title} (1).strm"
    if on_disk:
        strm.write_text("http://x/stream/t")
    rid = db.insert_request(title, imdb, "movie", tmdb_id=tmdb)
    db.update_request(rid, "success")
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, strm_path, imdb_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"tok-{imdb}", "h" * 40, "magnet:?x", title, "movie", str(strm), imdb))
        conn.execute("UPDATE requests SET updated_at = datetime('now', '-1 day')")
        conn.commit()
    return strm


@pytest.fixture
def library(tmp_path, monkeypatch):
    """Two successful movies on disk, Catbox on, no arrs configured at all."""
    import config
    import settings
    media = tmp_path / "media"
    monkeypatch.setattr(config, "MEDIA_PATH", str(media))
    monkeypatch.setattr(config, "CATBOX_MODE", True)
    values = {}
    monkeypatch.setattr(settings, "get", lambda k, d=None: values.get(k, d))
    strms = {imdb: _add_movie(media, imdb, tmdb, title)
             for imdb, tmdb, title in (("tt0113277", 949, "Heat"), ("tt0078748", 348, "Alien"))}
    purged = []
    import cleanup
    monkeypatch.setattr(cleanup, "purge_title", lambda imdb, row_id=None: purged.append(imdb) or {})
    return media, strms, purged, values


def test_a_title_whose_strm_was_deleted_on_disk_is_purged(library):
    """Jellyfin deletes the file when it deletes an item, so a missing .strm
    is a deletion made in Jellyfin whose webhook never arrived."""
    import disk_sync
    media, strms, purged, _ = library
    strms["tt0078748"].unlink()
    out = disk_sync.reconcile()
    assert purged == ["tt0078748"]
    assert out["purged"] == 1 and out["checked"] == 2


def test_it_needs_no_arr_and_no_mirror(library, monkeypatch):
    import arr_sync
    import disk_sync
    media, strms, purged, _ = library
    monkeypatch.setattr(arr_sync, "reconcile", lambda: (_ for _ in ()).throw(AssertionError("arr sync ran")))
    strms["tt0078748"].unlink()
    disk_sync.reconcile()
    assert purged == ["tt0078748"]
    assert not arr_sync.is_enabled()


def test_a_title_still_being_processed_is_not_purged(library):
    import disk_sync
    media, strms, purged, _ = library
    strms["tt0078748"].unlink()
    with db._connect() as conn:
        conn.execute("UPDATE requests SET updated_at = datetime('now') WHERE imdb_id = 'tt0078748'")
        conn.commit()
    disk_sync.reconcile()
    assert purged == []


def test_refuses_when_the_media_tree_is_gone(library, caplog):
    """The RECOVERY.md incident: a wrong mount makes every file 'missing'."""
    import disk_sync
    media, strms, purged, _ = library
    shutil.rmtree(media)
    with caplog.at_level("WARNING"):
        out = disk_sync.reconcile()
    assert purged == [] and out["refused"] == 2
    assert any("refusing to purge" in r.message for r in caplog.records)


def test_refuses_when_most_titles_lost_their_files(library, caplog):
    import disk_sync
    media, strms, purged, _ = library
    for i in range(3):
        _add_movie(media, f"tt000000{i}", 100 + i, f"X{i}", on_disk=(i == 2))
    strms["tt0113277"].unlink()
    with caplog.at_level("WARNING"):
        out = disk_sync.reconcile()
    assert purged == [] and out["refused"] == 3, "3 of 5 titles lost files at once"
    assert any("refusing to purge" in r.message for r in caplog.records)


def test_below_the_threshold_a_lost_file_is_still_a_deletion(library):
    import disk_sync
    media, strms, purged, _ = library
    strms["tt0113277"].unlink()
    strms["tt0078748"].unlink()
    # Both gone, but the tree still holds someone else's .strm, so the mount is fine.
    other = media / "movies" / "Other (1)" / "Other (1).strm"
    other.parent.mkdir(parents=True)
    other.write_text("x")
    disk_sync.reconcile()
    assert sorted(purged) == ["tt0078748", "tt0113277"]


def test_can_be_switched_off(library):
    import disk_sync
    media, strms, purged, values = library
    values["DISK_SYNC_ENABLED"] = False
    strms["tt0078748"].unlink()
    assert disk_sync.reconcile() == {"checked": 0, "missing": 0, "purged": 0, "refused": 0}
    assert purged == []


def test_does_nothing_outside_catbox_mode(library, monkeypatch):
    import config
    import disk_sync
    media, strms, purged, _ = library
    monkeypatch.setattr(config, "CATBOX_MODE", False)
    strms["tt0078748"].unlink()
    disk_sync.reconcile()
    assert purged == []


def test_a_purge_leaves_an_activity_row_with_the_reason(library):
    import disk_sync
    media, strms, purged, _ = library
    strms["tt0078748"].unlink()
    disk_sync.reconcile()
    rows = [r for r in db.get_activity(20) if r["event"] == "purged"]
    assert rows and "gone from disk" in rows[0]["message"]


def test_a_purge_failure_never_raises(library, monkeypatch):
    import cleanup
    import disk_sync
    media, strms, purged, _ = library
    monkeypatch.setattr(cleanup, "purge_title", lambda imdb, row_id=None: (_ for _ in ()).throw(OSError("disk")))
    strms["tt0078748"].unlink()
    out = disk_sync.reconcile()
    assert out["purged"] == 0 and out["missing"] == 1


def test_the_job_is_scheduled_in_catbox_mode_and_the_arr_sync_shares_its_guards():
    src = _src("app.py")
    assert re.search(r'if CATBOX_MODE and DISK_SYNC_INTERVAL_MINUTES > 0:\s*scheduler\.add_job\(\s*disk_sync\.reconcile,[^)]*id="disk_sync"', src)
    arr = _src("arr_sync.py")
    assert "from disk_sync import older_than_grace" in arr and "from disk_sync import purge_rows" in arr
    settings_src = _src("settings.py")
    assert '"DISK_SYNC_ENABLED"' in settings_src.split("_BOOL_KEYS = {", 1)[1].split("}", 1)[0]
    assert "\nDISK_SYNC_ENABLED=" in _src(".env.example") and "\nDISK_SYNC_INTERVAL_MINUTES=" in _src(".env.example")
