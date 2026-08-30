"""Re-requesting something that was deleted must work, and must not be
reported as a failure when the media is already in the library.

Both bugs came from the same place: deleting a request only deleted the
request row, so the webhook dedup key and the registered episodes survived
and then poisoned the next request for the same title.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db
import processor
import streams as streams_mod
from webhook_parser import MediaRequest


def _drop_cached_conn():
    """db caches one sqlite connection per thread for the thread's lifetime, so
    repointing db.DB_PATH is only honoured once that cached handle is gone."""
    conn = getattr(db._tls, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        db._tls.conn = None


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    _drop_cached_conn()
    db.init()
    yield
    _drop_cached_conn()


def _stream(info_hash, is_pack=True):
    return streams_mod.Stream(
        name="x", title="The.Rookie.S05.1080p.WEB-DL", info_hash=info_hash,
        quality="1080p", seeders=10, size_gb=5.0,
        is_season_pack=is_pack, source="torrentio",
    )


def _req(seasons=(5,)):
    return MediaRequest(title="The Rookie (2018)", media_type="series",
                        imdb_id="tt7587890", seasons=list(seasons))


@pytest.fixture
def lazy_series(monkeypatch):
    """Wire _lazy_register_season so one cached season pack is always found."""
    import blacklist
    import debrid
    monkeypatch.setattr(processor, "_fetch_season_candidates",
                        lambda *a, **k: [_stream("a" * 40)])
    monkeypatch.setattr(blacklist, "filter_candidates", lambda c: list(c))
    monkeypatch.setattr(debrid, "check_cached_multi",
                        lambda hashes: {"torbox": set(hashes)})
    monkeypatch.setattr(processor, "_get_season_episode_count", lambda i, s: 3)


def test_season_pack_already_registered_is_success(lazy_series, monkeypatch):
    """Every episode already has a .strm: the season is present, not failed."""
    import strm_generator
    monkeypatch.setattr(strm_generator, "create_lazy_episode_strm",
                        lambda *a, **k: False)
    monkeypatch.setattr(db, "get_virtual_item_by_episode",
                        lambda imdb, s, e: {"token": f"tok{s}{e}"})

    ok, winner = processor._lazy_register_season(_req(), 5)

    assert ok is True
    assert winner is not None
    assert processor._WANTED.get("tt7587890") is None


def test_season_pack_write_failure_is_still_a_failure(lazy_series, monkeypatch):
    """No .strm written AND nothing registered means the season really failed.

    This is the case a naive "written == 0 means success" fix would break:
    a disk error must not be reported as a healthy library.
    """
    import strm_generator
    monkeypatch.setattr(strm_generator, "create_lazy_episode_strm",
                        lambda *a, **k: False)
    monkeypatch.setattr(db, "get_virtual_item_by_episode",
                        lambda imdb, s, e: None)

    ok, winner = processor._lazy_register_season(_req(), 5)

    assert ok is False


def test_per_episode_already_registered_is_success(monkeypatch):
    """The per-episode fallback must not mark a fully-present season wanted."""
    import blacklist
    import debrid
    import strm_generator
    monkeypatch.setattr(processor, "_fetch_season_candidates",
                        lambda *a, **k: [_stream("b" * 40, is_pack=False)])
    monkeypatch.setattr(blacklist, "filter_candidates", lambda c: list(c))
    monkeypatch.setattr(debrid, "check_cached_multi",
                        lambda hashes: {"torbox": set(hashes)})
    monkeypatch.setattr(strm_generator, "create_lazy_episode_strm",
                        lambda *a, **k: False)
    monkeypatch.setattr(db, "get_virtual_item_by_episode",
                        lambda imdb, s, e: {"token": "tok"} if e == 1 else None)
    processor._WANTED.pop("tt7587890", None)

    ok, winner = processor._lazy_register_season(_req(), 5)

    assert ok is True
    assert "tt7587890" not in processor._WANTED


def test_deleting_a_request_clears_its_webhook_dedup_key():
    """Otherwise the re-request is swallowed as a duplicate for up to 24h."""
    key = "tt1234567:series:1,2,3"
    assert db.webhook_seen(key) is False
    row_id = db.insert_request("Show", "tt1234567", "series", [1, 2, 3])

    db.delete_request(row_id)

    assert db.webhook_seen(key) is False, "re-request must not be seen as duplicate"


def test_clearing_dedup_keys_is_scoped_to_one_imdb_id():
    db.webhook_seen("tt7000001:series:1")
    db.webhook_seen("tt7000002:series:1")

    db.clear_webhook_events("tt7000001")

    assert db.webhook_seen("tt7000001:series:1") is False
    assert db.webhook_seen("tt7000002:series:1") is True


# ── purge (Remove from library) ───────────────────────────────────────────────

def test_purge_removes_strms_db_rows_and_dedup_keys(tmp_path, monkeypatch):
    """'Remove from library' must leave nothing behind that would poison a
    later re-request: files, virtual_items, monitoring rows and dedup keys."""
    import cleanup
    monkeypatch.setattr(cleanup, "MEDIA_PATH", str(tmp_path))
    monkeypatch.setattr(cleanup.jellyfin, "refresh_library", lambda: None)

    imdb = "tt5550001"
    season_dir = tmp_path / "series" / "Purge Me (2020)" / "Season 01"
    season_dir.mkdir(parents=True)
    kept = tmp_path / "series" / "Keep Me (2020)" / "Season 01"
    kept.mkdir(parents=True)
    kept_strm = kept / "Keep Me S01E01.strm"
    kept_strm.write_text("http://keep")
    db.insert_virtual_item("tokkeep", "d" * 40, "magnet:?y", "Keep Me S01E01",
                           "series", strm_path=str(kept_strm), imdb_id="tt5559999",
                           season=1, episode=1)

    for ep in (1, 2):
        strm = season_dir / f"Purge Me S01E{ep:02d}.strm"
        strm.write_text("http://x")
        strm.with_suffix(".nfo").write_text("<nfo/>")
        db.insert_virtual_item(f"tokpurge{ep}", "c" * 40, "magnet:?x", f"Purge Me S01E{ep:02d}",
                               "series", strm_path=str(strm), imdb_id=imdb,
                               season=1, episode=ep)

    row_id = db.insert_request("Purge Me (2020)", imdb, "series", [1])
    db.upsert_monitored_series(imdb, None, "Purge Me (2020)", [1])
    db.upsert_wanted_episode(imdb, None, "Purge Me (2020)", 1, 3, None)
    db.webhook_seen(f"{imdb}:series:1")

    result = cleanup.purge_title(imdb, row_id=row_id)

    assert result["strms"] == 2
    assert db.get_virtual_items_by_imdb(imdb) == []
    assert not (tmp_path / "series" / "Purge Me (2020)").exists()
    assert kept_strm.exists(), "must not touch other titles"
    assert len(db.get_virtual_items_by_imdb("tt5559999")) == 1, "must not touch other titles"
    assert [r for r in db.get_recent(50) if r["id"] == row_id] == []
    assert not any(s["imdb_id"] == imdb for s in db.get_all_monitored_series())
    assert not any(e["imdb_id"] == imdb for e in db.get_all_wanted_episodes())
    assert db.webhook_seen(f"{imdb}:series:1") is False


def test_purge_is_safe_when_the_title_has_no_media():
    """Purging a request that never produced anything must not raise."""
    import cleanup
    imdb = "tt5550002"
    row_id = db.insert_request("Nothing Here", imdb, "movie", [])

    result = cleanup.purge_title(imdb, row_id=row_id)

    assert result["strms"] == 0
    assert [r for r in db.get_recent(50) if r["id"] == row_id] == []


def test_purge_clears_dedup_keys_even_without_a_request_row(tmp_path, monkeypatch):
    """Purging a library title that has no request row must still free the
    dedup key, or re-requesting it is swallowed for the next 24h."""
    import cleanup
    monkeypatch.setattr(cleanup, "MEDIA_PATH", str(tmp_path))
    monkeypatch.setattr(cleanup.jellyfin, "refresh_library", lambda: None)

    imdb = "tt5550003"
    db.webhook_seen(f"{imdb}:movie:")

    cleanup.purge_title(imdb, row_id=None)

    assert db.webhook_seen(f"{imdb}:movie:") is False


# ── queued retries must not resurrect a removed title ─────────────────────────

def test_delete_cancels_a_queued_retry():
    """A failed request queues a retry. If the row is deleted but the retry is
    not, the request reappears at the next backoff interval."""
    imdb = "tt5550004"
    row_id = db.insert_request("Comes Back", imdb, "series", [1])
    db.enqueue_retry(imdb, "Comes Back", "series", [1], 1, 0)
    assert any(r["imdb_id"] == imdb for r in db.get_due_retries())

    db.delete_request(row_id)

    assert not any(r["imdb_id"] == imdb for r in db.get_due_retries())


def test_purge_cancels_a_queued_retry(tmp_path, monkeypatch):
    """Otherwise the retry re-downloads what was just removed from the library."""
    import cleanup
    monkeypatch.setattr(cleanup, "MEDIA_PATH", str(tmp_path))
    monkeypatch.setattr(cleanup.jellyfin, "refresh_library", lambda: None)
    imdb = "tt5550005"
    db.enqueue_retry(imdb, "Comes Back Too", "series", [1], 1, 0)

    cleanup.purge_title(imdb, row_id=None)

    assert not any(r["imdb_id"] == imdb for r in db.get_due_retries())


def test_cancelling_retries_is_scoped_to_one_imdb_id():
    db.enqueue_retry("tt5550006", "A", "movie", None, 1, 0)
    db.enqueue_retry("tt5550007", "B", "movie", None, 1, 0)

    db.clear_retries("tt5550006")

    remaining = {r["imdb_id"] for r in db.get_due_retries()}
    assert "tt5550006" not in remaining
    assert "tt5550007" in remaining


# ── purge must leave no trace Jellyfin can still show ─────────────────────────

def _series_layout(root, title, imdb, episodes=2):
    """Build what Mycelium actually writes for a series: strms plus the nfo and
    artwork sidecars from nfo_generator."""
    series = root / "series" / title
    season = series / "Season 01"
    season.mkdir(parents=True)
    (series / "tvshow.nfo").write_text("<tvshow/>")
    (series / "poster.jpg").write_bytes(b"x")
    (series / "fanart.jpg").write_bytes(b"x")
    (season / "poster.jpg").write_bytes(b"x")
    for ep in range(1, episodes + 1):
        strm = season / f"{title} S01E{ep:02d}.strm"
        strm.write_text("http://x")
        strm.with_suffix(".nfo").write_text("<episodedetails/>")
        strm.with_name(f"{strm.stem}-thumb.jpg").write_bytes(b"x")
        db.insert_virtual_item(f"tok{imdb}{ep}", "e" * 40, "magnet:?z", strm.stem,
                               "series", strm_path=str(strm), imdb_id=imdb,
                               season=1, episode=ep)
    return series


def test_purge_removes_artwork_and_show_metadata(tmp_path, monkeypatch):
    """Leaving tvshow.nfo and posters behind keeps the show visible in Jellyfin
    even though every .strm is gone - which is the whole point of the button."""
    import cleanup
    monkeypatch.setattr(cleanup, "MEDIA_PATH", str(tmp_path))
    monkeypatch.setattr(cleanup.jellyfin, "refresh_library", lambda **k: None)
    imdb = "tt5551001"
    series = _series_layout(tmp_path, "Ghosted (2024)", imdb)

    cleanup.purge_title(imdb, row_id=None)

    assert not series.exists(), f"series folder survived: {sorted(p.name for p in series.rglob('*'))}"


def test_purge_leaves_unrelated_files_and_their_folder_alone(tmp_path, monkeypatch):
    """We only remove what Mycelium wrote. Anything else keeps its folder."""
    import cleanup
    monkeypatch.setattr(cleanup, "MEDIA_PATH", str(tmp_path))
    monkeypatch.setattr(cleanup.jellyfin, "refresh_library", lambda **k: None)
    imdb = "tt5551002"
    series = _series_layout(tmp_path, "Kept (2024)", imdb)
    stray = series / "Season 01" / "my-notes.txt"
    stray.write_text("do not delete me")

    cleanup.purge_title(imdb, row_id=None)

    assert stray.exists(), "a file Mycelium did not write must survive"
    assert not (series / "tvshow.nfo").exists()
    assert not (series / "poster.jpg").exists()
    assert list(series.rglob("*.strm")) == []


def test_purge_does_not_touch_a_sibling_title(tmp_path, monkeypatch):
    import cleanup
    monkeypatch.setattr(cleanup, "MEDIA_PATH", str(tmp_path))
    monkeypatch.setattr(cleanup.jellyfin, "refresh_library", lambda **k: None)
    target = _series_layout(tmp_path, "Target (2024)", "tt5551003")
    other = _series_layout(tmp_path, "Other (2024)", "tt5551004")

    cleanup.purge_title("tt5551003", row_id=None)

    assert not target.exists()
    assert (other / "tvshow.nfo").exists()
    assert len(list(other.rglob("*.strm"))) == 2


def test_purge_forces_the_jellyfin_refresh(tmp_path, monkeypatch):
    """The 60s debounce exists for bulk strm generation. A human clicking
    Remove must not be swallowed by it."""
    import cleanup
    monkeypatch.setattr(cleanup, "MEDIA_PATH", str(tmp_path))
    calls = {}
    monkeypatch.setattr(cleanup.jellyfin, "refresh_library",
                        lambda **kw: calls.update(kw) or True)

    cleanup.purge_title("tt5551005", row_id=None)

    assert calls.get("force") is True, "purge must bypass the refresh debounce"


def test_purge_cleans_its_own_episodes_from_a_folder_it_must_keep(tmp_path, monkeypatch):
    """A folder that still holds another title's .strm survives, and keeps its
    artwork - but our purged episodes must not leave their stills behind."""
    import cleanup
    monkeypatch.setattr(cleanup, "MEDIA_PATH", str(tmp_path))
    monkeypatch.setattr(cleanup.jellyfin, "refresh_library", lambda **k: None)
    imdb = "tt5551006"
    series = _series_layout(tmp_path, "Shared (2024)", imdb)
    season = series / "Season 01"
    foreign = season / "Someone Else S01E09.strm"
    foreign.write_text("http://other")

    cleanup.purge_title(imdb, row_id=None)

    assert foreign.exists(), "another title's strm must survive"
    assert (season / "poster.jpg").exists(), "artwork stays while media remains"
    assert list(season.glob("*-thumb.jpg")) == [], "our episode stills must go"
    assert list(season.glob("Shared*.strm")) == []
