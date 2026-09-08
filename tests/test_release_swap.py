"""release_swap: the candidate list behind "Pick another release" and the
swap that puts a different hash behind an existing token."""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db
import release_swap as rs
from streams import Stream

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


def _stream(name, h, quality="1080p", seeders=10, size=4.0, langs=("en",), src="torrentio", pack=False):
    return Stream(name=name, title=name, info_hash=h, quality=quality, seeders=seeders, size_gb=size,
                  is_season_pack=pack, languages=langs, source=src)


H1, H2, H3, H4 = "a" * 40, "b" * 40, "c" * 40, "d" * 40


def _item(imdb, token, info_hash, season=None, episode=None, quality="1080p", source=None):
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, strm_path, imdb_id, season, episode, quality, source) "
            "VALUES (?, ?, ?, 'Heat', ?, ?, ?, ?, ?, ?, ?)",
            (token, info_hash, f"magnet:?xt=urn:btih:{info_hash}", "movie" if season is None else "series",
             f"/media/{token}.strm", imdb, season, episode, quality, source))
        conn.commit()


@pytest.fixture
def scrapers_fake(monkeypatch):
    """Four candidates: a good WEB-DL (cached), a cam that the rules drop,
    a REMUX (uncached), and the current release."""
    streams = [
        _stream("Heat.1995.1080p.WEB-DL.x264", H1),
        _stream("Heat.1995.CAM.x264", H2, quality="720p"),
        _stream("Heat.1995.2160p.REMUX", H3, quality="2160p", size=60.0, src="zilean"),
        _stream("Heat.1995.1080p.BluRay.x264", H4),
    ]
    import scrapers
    import streams as streams_mod
    import debrid
    import filter_rules
    monkeypatch.setattr(scrapers, "merge_candidates", lambda *a, **k: list(streams))

    def fake_rank(items, prefer_season_pack=False, override=None):
        verdicts = [filter_rules.Verdict(kept=s.info_hash != H2, rule=None if s.info_hash != H2 else "SOURCE_EXCLUDED",
                                         value=None if s.info_hash != H2 else "cam") for s in items]
        kept = [s for s, v in zip(items, verdicts) if v.kept]
        kept.sort(key=lambda s: s.info_hash != H1)   # H1 first, as the processor would rank it
        return kept, verdicts
    monkeypatch.setattr(streams_mod, "rank_streams_explained", fake_rank)
    monkeypatch.setattr(debrid, "check_cached_multi", lambda hashes: {"torbox": {H1, H4}})
    return streams


def test_candidates_are_kept_first_then_dropped_with_badges(scrapers_fake):
    db.insert_request("Heat", "tt1", "movie")
    _item("tt1", "tok", H4, source="torrentio")
    out = rs.candidates("tt1", "movie")
    assert out["current"] == {"info_hash": H4, "quality": "1080p", "source": "BluRay"}
    rows = out["candidates"]
    assert [r["info_hash"] for r in rows] == [H1, H3, H4, H2], "kept in rank order, dropped last"
    by = {r["info_hash"]: r for r in rows}
    assert by[H1]["cached"] is True and by[H3]["cached"] is False
    assert by[H4]["current"] is True and by[H1]["current"] is False
    assert by[H2]["kept"] is False and by[H2]["rule"] == "SOURCE_EXCLUDED" and by[H2]["value"] == "cam"
    assert by[H1]["kept"] is True and by[H1]["rule"] is None
    assert by[H1]["source"] == "WEB-DL" and by[H3]["scrapers"] == ["zilean"]
    assert by[H1]["languages"] == ["en"] and by[H3]["size_gb"] == 60.0
    assert set(rows[0]) == {"info_hash", "name", "quality", "source", "size_gb", "seeders", "languages",
                            "cached", "scrapers", "kept", "rule", "value", "current"}


def test_current_source_is_null_when_current_hash_not_in_candidates(scrapers_fake):
    db.insert_request("Heat", "tt1", "movie")
    _item("tt1", "tok", "e" * 40, source="torrentio")
    out = rs.candidates("tt1", "movie")
    assert out["current"]["source"] is None


def test_duplicate_hash_case_insensitive_is_deduped(monkeypatch, scrapers_fake):
    import scrapers
    dup = _stream("Heat.1995.1080p.WEB-DL.x264", H1.upper())
    streams_with_dup = [scrapers_fake[0], dup, scrapers_fake[1], scrapers_fake[2], scrapers_fake[3]]
    monkeypatch.setattr(scrapers, "merge_candidates", lambda *a, **k: list(streams_with_dup))
    db.insert_request("Heat", "tt1", "movie")
    rows = rs.candidates("tt1", "movie")["candidates"]
    matches = [r for r in rows if r["info_hash"] == H1]
    assert len(matches) == 1
    assert matches[0]["kept"] is True and matches[0]["rule"] is None


def test_blacklisted_hashes_are_excluded(scrapers_fake):
    db.insert_request("Heat", "tt1", "movie")
    db.blacklist_hash(H3, "bad")
    rows = rs.candidates("tt1", "movie")["candidates"]
    assert H3 not in [r["info_hash"] for r in rows]


def test_episode_candidates_pass_season_and_episode(monkeypatch, scrapers_fake):
    import scrapers
    seen = {}
    monkeypatch.setattr(scrapers, "merge_candidates",
                        lambda mt, imdb, season=None, episode=None, **k: seen.update(mt=mt, s=season, e=episode) or list(scrapers_fake))
    db.insert_request("Loki", "tt4", "series")
    _item("tt4", "e3", H4, season=2, episode=3)
    out = rs.candidates("tt4", "series", season=2, episode=3)
    assert seen == {"mt": "series", "s": 2, "e": 3}
    assert out["current"]["info_hash"] == H4


def test_scraper_failure_raises_and_cache_failure_degrades(monkeypatch, scrapers_fake):
    import scrapers
    import debrid
    db.insert_request("Heat", "tt1", "movie")

    def boom(*a, **k):
        raise scrapers.ScrapersUnavailable("torrentio down")
    monkeypatch.setattr(scrapers, "merge_candidates", boom)
    with pytest.raises(rs.CandidatesUnavailable):
        rs.candidates("tt1", "movie")
    monkeypatch.setattr(scrapers, "merge_candidates", lambda *a, **k: list(scrapers_fake))

    def cache_boom(hashes):
        raise RuntimeError("429")
    monkeypatch.setattr(debrid, "check_cached_multi", cache_boom)
    rows = rs.candidates("tt1", "movie")["candidates"]
    assert rows and all(r["cached"] is False for r in rows), "a failed cache check means no badges, not no list"


def test_find_item_movie_and_episode():
    _item("tt1", "tok", H4)
    _item("tt4", "e3", H1, season=2, episode=3)
    assert rs.find_item("tt1")["token"] == "tok"
    assert rs.find_item("tt4", 2, 3)["token"] == "e3"
    assert rs.find_item("tt4", 2, 4) is None and rs.find_item("tt9") is None


def test_candidates_route_exists_and_is_admin_only():
    src = _src("app.py")
    route = '@app.get("/ui/api/library/<imdb_id>/candidates")'
    assert route in src
    body = src.split(route, 1)[1].split("\n\n\n", 1)[0]
    assert "auth.is_admin()" in body and "release_swap" in body and "502" in body


def _candidate(h, quality="2160p", source="REMUX", name="Heat.1995.2160p.REMUX"):
    return {"info_hash": h, "name": name, "quality": quality, "source": source, "size_gb": 60.0, "seeders": 5,
            "languages": ["en"], "cached": False, "scrapers": ["zilean"], "kept": True, "rule": None, "value": None, "current": False}


def test_swap_movie_replaces_the_release_behind_the_token(monkeypatch):
    import catbox
    rid = db.insert_request("Heat", "tt1", "movie")
    db.update_request(rid, "success", quality="1080p", source="WEB-DL", info_hash=H4)
    _item("tt1", "tok", H4)
    db.update_virtual_torbox_id("tok", 77)
    db.update_playability_fail("tt1", "cdn 404")
    invalidated = []
    monkeypatch.setattr(catbox, "invalidate_url_cache", lambda token=None: invalidated.append(token))
    out = rs.swap(rs.find_item("tt1"), _candidate(H3), blacklist_old=True)
    assert out["ok"] is True and "2160p" in out["message"]
    item = db.get_virtual_item("tok")
    assert item["info_hash"] == H3 and item["magnet"].endswith(H3) and item["quality"] == "2160p"
    assert item["torbox_id"] is None and item["file_id"] is None
    assert invalidated == ["tok"]
    assert db.get_playability_state("tt1")["status"] == "unknown"
    row = db.get_request(rid)
    assert row["status"] == "success" and row["info_hash"] == H3 and row["quality"] == "2160p" and row["source"] == "REMUX"
    assert H4 in db.get_blacklisted_hashes()
    act = db.get_activity_for_title("tt1", "Heat")[0]
    assert act["event"] == "swapped" and "1080p" in act["message"] and "2160p" in act["message"]


def test_swap_clears_the_realdebrid_id_but_keeps_the_provider(monkeypatch):
    import catbox
    rid = db.insert_request("Heat", "tt1", "movie")
    db.update_request(rid, "success", quality="1080p", source="WEB-DL", info_hash=H4)
    _item("tt1", "tok", H4)
    db.update_virtual_rd_id("tok", "RD123")
    db.update_virtual_debrid_provider("tok", "realdebrid")
    monkeypatch.setattr(catbox, "invalidate_url_cache", lambda token=None: None)
    out = rs.swap(rs.find_item("tt1"), _candidate(H3))
    assert out["ok"] is True
    item = db.get_virtual_item("tok")
    assert item["rd_id"] is None
    assert item["debrid_provider"] == "realdebrid"


def test_swap_drops_the_faststart_cache_file(monkeypatch, tmp_path):
    import catbox
    import mp4_faststart
    monkeypatch.setattr(mp4_faststart, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(catbox, "invalidate_url_cache", lambda token=None: None)
    rid = db.insert_request("Heat", "tt1", "movie")
    db.update_request(rid, "success", quality="1080p", source="WEB-DL", info_hash=H4)
    _item("tt1", "tok", H4)
    cache_file = tmp_path / "tok.fsh"
    cache_file.write_bytes(b"stale")
    out = rs.swap(rs.find_item("tt1"), _candidate(H3))
    assert out["ok"] is True
    assert not cache_file.exists()


def test_swap_with_no_faststart_cache_dir_is_quiet(monkeypatch):
    import catbox
    import mp4_faststart
    monkeypatch.setattr(mp4_faststart, "_CACHE_DIR", None)
    monkeypatch.setattr(catbox, "invalidate_url_cache", lambda token=None: None)
    rid = db.insert_request("Heat", "tt1", "movie")
    db.update_request(rid, "success", quality="1080p", source="WEB-DL", info_hash=H4)
    _item("tt1", "tok", H4)
    out = rs.swap(rs.find_item("tt1"), _candidate(H3))
    assert out["ok"] is True


def test_swap_warns_when_the_faststart_cache_file_cannot_be_dropped(monkeypatch, tmp_path, caplog):
    import catbox
    import mp4_faststart
    from pathlib import Path
    monkeypatch.setattr(mp4_faststart, "_CACHE_DIR", tmp_path)
    monkeypatch.setattr(catbox, "invalidate_url_cache", lambda token=None: None)
    cache_file = tmp_path / "tok.fsh"
    cache_file.write_bytes(b"stale")

    real_unlink = Path.unlink

    def _boom(self, *a, **k):
        if self == cache_file:
            raise OSError("permission denied")
        return real_unlink(self, *a, **k)
    monkeypatch.setattr(Path, "unlink", _boom)

    rid = db.insert_request("Heat", "tt1", "movie")
    db.update_request(rid, "success", quality="1080p", source="WEB-DL", info_hash=H4)
    _item("tt1", "tok", H4)
    with caplog.at_level("WARNING"):
        out = rs.swap(rs.find_item("tt1"), _candidate(H3))
    assert out["ok"] is True
    assert any(r.levelname == "WARNING" and "tok" in r.message for r in caplog.records)


def test_swap_episode_leaves_the_request_row_alone(monkeypatch):
    import catbox
    monkeypatch.setattr(catbox, "invalidate_url_cache", lambda token=None: None)
    rid = db.insert_request("Loki", "tt4", "series")
    db.update_request(rid, "success", quality="1080p", source="WEB-DL", info_hash=H1)
    _item("tt4", "e3", H4, season=2, episode=3)
    db.update_playability_fail("tt4:S02E03", "timeout")
    out = rs.swap(rs.find_item("tt4", 2, 3), _candidate(H3))
    assert out["ok"] is True
    assert db.get_virtual_item("e3")["info_hash"] == H3
    assert db.get_playability_state("tt4:S02E03")["status"] == "unknown"
    row = db.get_request(rid)
    assert row["info_hash"] == H1 and row["quality"] == "1080p", "the series row keeps its own release"
    assert H4 not in db.get_blacklisted_hashes()


def test_swap_by_hash_validates(monkeypatch, scrapers_fake):
    import catbox
    monkeypatch.setattr(catbox, "invalidate_url_cache", lambda token=None: None)
    db.insert_request("Heat", "tt1", "movie")
    _item("tt1", "tok", H4)
    assert rs.swap_by_hash("tt1", "short") == {"ok": False, "message": "not a valid info hash"}
    assert rs.swap_by_hash("tt9", H1)["message"] == "unknown title"
    assert rs.swap_by_hash("tt1", H4)["message"] == "that is already the current release"
    assert rs.swap_by_hash("tt1", "e" * 40)["message"] == "that hash is not in the candidate list"
    assert rs.swap_by_hash("tt1", H1, season=1, episode=1)["message"] == "no file for that episode"
    out = rs.swap_by_hash("tt1", H1)
    assert out["ok"] is True and db.get_virtual_item("tok")["info_hash"] == H1


def test_set_request_release_keeps_status_and_error():
    rid = db.insert_request("Heat", "tt1", "movie")
    db.update_request(rid, "failed", error="old error")
    db.set_request_release(rid, "2160p", "REMUX", H3)
    row = db.get_request(rid)
    assert row["status"] == "failed" and row["error"] == "old error" and row["info_hash"] == H3


def test_swap_route_exists_and_delegates():
    src = _src("app.py")
    route = '@app.post("/ui/api/library/<imdb_id>/swap")'
    assert route in src
    body = src.split(route, 1)[1].split("\n\n\n", 1)[0]
    assert "auth.is_admin()" in body and "release_swap.swap_by_hash(" in body and "blacklist_old" in body
    assert "season and episode must be whole numbers" in body


@pytest.mark.parametrize("season, episode, expected", [
    ("2", 3, (2, 3)),
    (None, None, (None, None)),
    ([1], 2, None),
    (True, 1, None),
    (2, None, None),
])
def test_parse_episode_ref(season, episode, expected):
    assert rs.parse_episode_ref(season, episode) == expected


def test_swap_holds_the_token_lock_around_the_write(monkeypatch):
    import catbox

    class _RecordingLock:
        def __init__(self, token, log):
            self._token = token
            self._log = log

        def __enter__(self):
            self._log.append(f"enter:{self._token}")

        def __exit__(self, *exc):
            self._log.append(f"exit:{self._token}")

    events = []
    monkeypatch.setattr(catbox, "_token_lock", lambda token: _RecordingLock(token, events))
    monkeypatch.setattr(catbox, "invalidate_url_cache", lambda token=None: None)

    real_upgrade = db.update_virtual_item_upgrade

    def _recording_upgrade(*a, **k):
        events.append("update")
        return real_upgrade(*a, **k)
    monkeypatch.setattr(db, "update_virtual_item_upgrade", _recording_upgrade)

    rid = db.insert_request("Heat", "tt1", "movie")
    db.update_request(rid, "success", quality="1080p", source="WEB-DL", info_hash=H4)
    _item("tt1", "tok", H4)
    out = rs.swap(rs.find_item("tt1"), _candidate(H3))
    assert out["ok"] is True
    assert events == ["enter:tok", "update", "exit:tok"]
