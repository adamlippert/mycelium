"""release_swap: the candidate list behind "Pick another release" and the
swap that puts a different hash behind an existing token."""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from _routes import src_for_route

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


@pytest.fixture(autouse=True)
def _clear_candidates_cache():
    """The candidates() cache is module-level so swap_by_hash can reuse it
    across the route/function boundary; clear it around every test so one
    test's cached entry can never change another test's scrape-call count."""
    rs._candidates_cache.clear()
    yield
    rs._candidates_cache.clear()


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


def test_current_source_falls_back_to_the_stored_label_when_not_in_candidates(scrapers_fake):
    """When the current hash isn't among the freshly-scraped candidates,
    current.source must come from the stored virtual_items.source (now a
    release-type label like the candidate rows use), not be dropped to
    None."""
    db.insert_request("Heat", "tt1", "movie")
    _item("tt1", "tok", "e" * 40, source="REMUX")
    out = rs.candidates("tt1", "movie")
    assert out["current"]["source"] == "REMUX"


def test_current_source_is_null_when_current_hash_not_in_candidates_and_nothing_stored(scrapers_fake):
    db.insert_request("Heat", "tt1", "movie")
    _item("tt1", "tok", "e" * 40, source=None)
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
    src = src_for_route("/ui/api/library/<imdb_id>/candidates")
    route = '@bp.get("/ui/api/library/<imdb_id>/candidates")'
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


def test_swap_gives_up_on_a_held_token_lock_without_side_effects(monkeypatch):
    """catbox.materialize can hold the token lock for up to ten minutes; a
    bounded wait returns the busy result and changes nothing."""
    import catbox
    rid = db.insert_request("Heat", "tt1", "movie")
    db.update_request(rid, "success", quality="1080p", source="WEB-DL", info_hash=H4)
    _item("tt1", "tok", H4)
    invalidated = []
    monkeypatch.setattr(catbox, "invalidate_url_cache", lambda token=None: invalidated.append(token))
    lock = catbox._token_lock("tok")
    assert lock.acquire(timeout=1)
    try:
        out = rs.swap(rs.find_item("tt1"), _candidate(H3), blacklist_old=True, lock_timeout=0.05)
    finally:
        lock.release()
    assert out == {"ok": False, "message": rs.BUSY_MESSAGE}
    assert db.get_virtual_item("tok")["info_hash"] == H4
    assert invalidated == []
    assert db.get_request(rid)["info_hash"] == H4
    assert H4 not in db.get_blacklisted_hashes()
    assert db.get_activity_for_title("tt1", "Heat") == []
    # Released again: the same call goes through.
    assert rs.swap(rs.find_item("tt1"), _candidate(H3), lock_timeout=0.05)["ok"] is True


def test_swap_by_hash_bounds_the_admin_wait():
    src = open(os.path.join(_ROOT, "release_swap.py"), encoding="utf-8").read()
    body = src.split("def swap_by_hash(", 1)[1]
    assert "lock_timeout=ADMIN_LOCK_TIMEOUT_SEC" in body


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


def test_swap_by_hash_reuses_a_fresh_candidates_cache(monkeypatch, scrapers_fake):
    import scrapers
    calls = []
    monkeypatch.setattr(scrapers, "merge_candidates", lambda *a, **k: calls.append(1) or list(scrapers_fake))
    monkeypatch.setattr(rs.time, "monotonic", lambda: 1000.0)
    db.insert_request("Heat", "tt1", "movie")
    _item("tt1", "tok", H4)
    rs.candidates("tt1", "movie")
    assert len(calls) == 1
    out = rs.swap_by_hash("tt1", H1)
    assert out["ok"] is True
    assert len(calls) == 1, "swap_by_hash should reuse the cached candidates() result, not scrape again"


def test_swap_by_hash_rescrapes_once_the_cache_entry_is_stale(monkeypatch, scrapers_fake):
    import scrapers
    calls = []
    monkeypatch.setattr(scrapers, "merge_candidates", lambda *a, **k: calls.append(1) or list(scrapers_fake))
    clock = [1000.0]
    monkeypatch.setattr(rs.time, "monotonic", lambda: clock[0])
    db.insert_request("Heat", "tt1", "movie")
    _item("tt1", "tok", H4)
    rs.candidates("tt1", "movie")
    assert len(calls) == 1
    clock[0] += rs._CANDIDATES_CACHE_TTL_SEC + 1
    out = rs.swap_by_hash("tt1", H1)
    assert out["ok"] is True
    assert len(calls) == 2, "a stale cache entry must not be reused"


def test_swap_by_hash_scrapes_when_nothing_was_cached_yet(monkeypatch, scrapers_fake):
    import scrapers
    calls = []
    monkeypatch.setattr(scrapers, "merge_candidates", lambda *a, **k: calls.append(1) or list(scrapers_fake))
    db.insert_request("Heat", "tt1", "movie")
    _item("tt1", "tok", H4)
    out = rs.swap_by_hash("tt1", H1)
    assert out["ok"] is True
    assert len(calls) == 1


def test_candidates_function_always_scrapes_even_with_a_fresh_cache_entry(monkeypatch, scrapers_fake):
    """candidates() is what the route and the drawer panel call; neither may
    ever be served a stale list, so the function itself must never read its
    own cache back, only populate it for swap_by_hash to use."""
    import scrapers
    db.insert_request("Heat", "tt1", "movie")
    _item("tt1", "tok", H4)
    monkeypatch.setattr(scrapers, "merge_candidates", lambda *a, **k: list(scrapers_fake))
    first = rs.candidates("tt1", "movie")
    assert ("f" * 40) not in [r["info_hash"] for r in first["candidates"]]
    extra = _stream("Heat.1995.2160p.BluRay.x264", "f" * 40, quality="2160p")
    monkeypatch.setattr(scrapers, "merge_candidates", lambda *a, **k: list(scrapers_fake) + [extra])
    second = rs.candidates("tt1", "movie")
    assert ("f" * 40) in [r["info_hash"] for r in second["candidates"]]


def test_candidates_cache_prunes_stale_entries_on_insert(monkeypatch, scrapers_fake):
    import scrapers
    monkeypatch.setattr(scrapers, "merge_candidates", lambda *a, **k: list(scrapers_fake))
    clock = [1000.0]
    monkeypatch.setattr(rs.time, "monotonic", lambda: clock[0])
    db.insert_request("Heat", "tt1", "movie")
    _item("tt1", "tok", H4)
    rs.candidates("tt1", "movie")
    assert ("tt1", None, None) in rs._candidates_cache
    clock[0] += rs._CANDIDATES_CACHE_TTL_SEC + 1
    db.insert_request("Loki", "tt4", "series")
    rs.candidates("tt4", "series", season=1, episode=1)
    assert ("tt1", None, None) not in rs._candidates_cache, "a stale entry must be pruned by the next insert"
    assert ("tt4", 1, 1) in rs._candidates_cache


def test_set_request_release_keeps_status_and_error():
    rid = db.insert_request("Heat", "tt1", "movie")
    db.update_request(rid, "failed", error="old error")
    db.set_request_release(rid, "2160p", "REMUX", H3)
    row = db.get_request(rid)
    assert row["status"] == "failed" and row["error"] == "old error" and row["info_hash"] == H3


def test_swap_route_exists_and_delegates():
    src = src_for_route("/ui/api/library/<imdb_id>/swap")
    route = '@bp.post("/ui/api/library/<imdb_id>/swap")'
    assert route in src
    body = src.split(route, 1)[1].split("\n\n\n", 1)[0]
    assert "auth.is_admin()" in body and "release_swap.swap_by_hash(" in body and "blacklist_old" in body
    assert "season and episode must be whole numbers" in body


def test_candidates_route_rejects_a_negative_season_or_episode_like_swap_does():
    """The candidates route used to pass season/episode straight through to
    a live scrape without validating them; a negative value now gets the
    same {ok: false, message} rejection the swap route already used for an
    invalid ref, via the same parse_episode_ref helper."""
    src = src_for_route("/ui/api/library/<imdb_id>/candidates")
    route = '@bp.get("/ui/api/library/<imdb_id>/candidates")'
    assert route in src
    body = src.split(route, 1)[1].split("\n\n\n", 1)[0]
    assert "release_swap.parse_episode_ref(" in body
    assert "season and episode must be whole numbers" in body
    assert body.index("release_swap.parse_episode_ref(") < body.index("release_swap.candidates(")


@pytest.mark.parametrize("season, episode, expected", [
    ("2", 3, (2, 3)),
    (None, None, (None, None)),
    ([1], 2, None),
    (True, 1, None),
    (2, None, (2, None)),   # a season without an episode is the whole season
    (0, 0, (0, 0)),
    (-1, 1, None),
    (1, -1, None),
    ("-1", 1, None),
    (-1, -1, None),
    ("x", 1, None),
    ("--3", 1, None),
])
def test_parse_episode_ref(season, episode, expected):
    assert rs.parse_episode_ref(season, episode) == expected


def test_swap_holds_the_token_lock_around_the_write(monkeypatch):
    import catbox

    class _RecordingLock:
        def __init__(self, token, log):
            self._token = token
            self._log = log

        def acquire(self, timeout=-1):
            self._log.append(f"enter:{self._token}")
            return True

        def release(self):
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


# whole-season swap

HP = "e" * 40   # the new pack
HQ = "f" * 40   # a single-episode release (not a pack)
PACK_FILES = [{"id": i, "name": f"Show/Heat S02E{n:02d}.mkv", "size": 1000 + n} for i, n in enumerate((1, 2, 3))]


@pytest.fixture
def season_fake(monkeypatch):
    """Season 2 of Heat: E1 and E2 present on H1, E3 wanted, E4 wanted. The
    scrapers offer pack HP (cached, E1 to E3) and single HQ; TorBox lists
    the pack's files."""
    import scrapers
    import streams as streams_mod
    import debrid
    import filter_rules
    import torbox
    db.insert_request("Heat", "tt2", "series")
    _item("tt2", "t21", H1, season=2, episode=1)
    _item("tt2", "t22", H1, season=2, episode=2)
    db.upsert_wanted_episode("tt2", 9, "Heat", 2, 3, "2024-01-01")
    db.upsert_wanted_episode("tt2", 9, "Heat", 2, 4, "2024-01-01")
    found = [_stream("Heat.S02.1080p.WEB-DL", HP, pack=True), _stream("Heat.S02E01.1080p", HQ),
             _stream("Heat.S02.720p.HDTV", H1, quality="720p", pack=True)]
    calls = {}
    def merge(media_type, imdb, season=None, episode=None, **kw):
        calls["merge"] = (media_type, imdb, season, episode)
        return list(found)
    monkeypatch.setattr(scrapers, "merge_candidates", merge)
    def fake_rank(items, prefer_season_pack=False, override=None):
        calls["rank"] = prefer_season_pack
        return list(items), [filter_rules.Verdict(kept=True, rule=None, value=None) for _ in items]
    monkeypatch.setattr(streams_mod, "rank_streams_explained", fake_rank)
    monkeypatch.setattr(debrid, "check_cached_multi", lambda hashes: {"torbox": {HP, H1}})
    files = {"files": PACK_FILES}
    monkeypatch.setattr(torbox, "check_cached_files", lambda hashes, **k: {h: files for h in hashes if h == HP})
    written = []
    import strm_generator
    def fake_create(info_hash, magnet, title, season, episode, **kw):
        written.append((episode, info_hash, kw.get("file_id")))
        _item("tt2", f"new{episode}", info_hash, season=season, episode=episode)
        db.mark_episode_status("tt2", season, episode, "found")
        return True
    monkeypatch.setattr(strm_generator, "create_lazy_episode_strm", fake_create)
    return calls, written


def test_season_candidates_keep_packs_only_with_coverage_and_current_flags(season_fake):
    calls, _ = season_fake
    out = rs.candidates("tt2", "series", 2, None)
    assert calls["merge"] == ("series", "tt2", 2, 1) and calls["rank"] is True
    assert out["current"] is None
    rows = {r["info_hash"]: r for r in out["candidates"]}
    assert set(rows) == {HP, H1}, "single-episode releases cannot serve a season"
    assert rows[HP]["episodes"] == [1, 2, 3] and rows[HP]["current"] is False and rows[HP]["cached"] is True
    assert rows[H1]["episodes"] is None and rows[H1]["current"] is True, "no file list for it: coverage unknown"


def test_season_swap_swaps_present_registers_wanted_and_skips_the_rest(season_fake):
    _, written = season_fake
    out = rs.swap_by_hash("tt2", HP, 2, None, blacklist_old=True)
    assert out["ok"] is True
    assert (out["swapped"], out["registered"], out["kept"], out["skipped"], out["busy"]) == ([1, 2], [3], [], [4], [])
    assert "2 swapped, 1 registered, 1 not in the pack, still wanted (E04)" in out["message"]
    for tok, fid in (("t21", 0), ("t22", 1)):
        it = db.get_virtual_item(tok)
        assert it["info_hash"] == HP and it["file_id"] == fid and it["torbox_id"] is None
    assert written == [(3, HP, 2)]
    assert db.excluded_hashes_for("tt2", 2, 4) == {HP}, "E4 stays wanted and never tries this pack"
    assert H1 in db.get_blacklisted_hashes(db._blacklist_threshold())
    assert any(a.get("message", "").startswith("S02 to 1080p") for a in db.get_activity(5))


def test_season_swap_without_a_file_list_swaps_present_only(season_fake, monkeypatch):
    import torbox
    _, written = season_fake
    monkeypatch.setattr(torbox, "check_cached_files", lambda hashes, **k: {})
    out = rs.swap_by_hash("tt2", HP, 2, None)
    assert out["ok"] is True and out["swapped"] == [1, 2] and out["registered"] == [] and out["skipped"] == []
    assert db.get_virtual_item("t21")["file_id"] is None, "the first play reconciles"
    assert written == [] and db.excluded_hashes_for("tt2", 2, 4) == set()


def test_season_swap_skips_a_busy_token_and_reports_it(season_fake, monkeypatch):
    import catbox
    monkeypatch.setattr(rs, "ADMIN_LOCK_TIMEOUT_SEC", 0.01)
    lock = catbox._token_lock("t22")
    lock.acquire()
    try:
        out = rs.swap_by_hash("tt2", HP, 2, None)
    finally:
        lock.release()
    assert out["ok"] is True and out["swapped"] == [1] and out["busy"] == [2]
    assert db.get_virtual_item("t22")["info_hash"] == H1
    assert "busy, try again later (E02)" in out["message"]


def test_season_swap_keeps_a_present_episode_the_pack_lacks_and_spares_its_hash(season_fake, monkeypatch):
    _item("tt2", "t24", H3, season=2, episode=4)   # E4 present on H3, and the pack has E1 to E3
    with db._connect() as conn:
        conn.execute("DELETE FROM wanted_episodes WHERE imdb_id='tt2' AND episode=4"); conn.commit()
    out = rs.swap_by_hash("tt2", HP, 2, None, blacklist_old=True)
    assert out["ok"] is True and out["swapped"] == [1, 2] and out["kept"] == [4] and out["skipped"] == []
    assert "1 not in the pack, kept their release (E04)" in out["message"]
    assert db.get_virtual_item("t24")["info_hash"] == H3
    blacklisted = db.get_blacklisted_hashes(db._blacklist_threshold())
    assert H1 in blacklisted and H3 not in blacklisted, "E4 still plays from H3"


def test_season_swap_does_not_blacklist_a_hash_a_busy_episode_still_uses(season_fake, monkeypatch):
    import catbox
    monkeypatch.setattr(rs, "ADMIN_LOCK_TIMEOUT_SEC", 0.01)
    lock = catbox._token_lock("t22")
    lock.acquire()
    try:
        out = rs.swap_by_hash("tt2", HP, 2, None, blacklist_old=True)
    finally:
        lock.release()
    assert out["swapped"] == [1] and out["busy"] == [2]
    assert H1 not in db.get_blacklisted_hashes(db._blacklist_threshold())


def test_season_swap_reports_an_episode_it_could_not_register(season_fake, monkeypatch):
    import strm_generator
    monkeypatch.setattr(strm_generator, "create_lazy_episode_strm", lambda *a, **k: False)
    out = rs.swap_by_hash("tt2", HP, 2, None)
    assert out["ok"] is True and out["failed"] == [3] and "could not be registered (E03)" in out["message"]


def test_season_swap_refreshes_jellyfin_only_when_it_registered_something(season_fake, monkeypatch):
    import jellyfin
    calls = []
    monkeypatch.setattr(jellyfin, "refresh_library", lambda *a, **k: calls.append(1))
    rs.swap_by_hash("tt2", HP, 2, None)
    assert calls == [1]
    calls.clear()
    rs.swap_by_hash("tt2", HP, 2, None)   # everything already on the pack now
    assert calls == []


def test_season_swap_when_every_episode_is_already_on_the_pack_is_ok(season_fake):
    rs.swap_by_hash("tt2", HP, 2, None)
    out = rs.swap_by_hash("tt2", HP, 2, None)
    assert out["ok"] is True and out["swapped"] == [] and out["skipped"] == [4]
    with db._connect() as conn:
        conn.execute("DELETE FROM wanted_episodes WHERE imdb_id='tt2' AND episode=4"); conn.commit()
    out = rs.swap_by_hash("tt2", HP, 2, None)
    assert out["ok"] is True and "already on this pack" in out["message"]


def test_season_swap_holds_the_new_pack_lock_around_the_loop():
    src = open(os.path.join(_ROOT, "release_swap.py")).read()
    body = src.split("def swap_season(")[1].split("\ndef ")[0]
    assert 'with catbox._pack_lock(info_hash):' in body


def test_season_swap_validates(season_fake, monkeypatch):
    import torbox
    assert rs.swap_by_hash("tt2", "nope", 2, None)["ok"] is False
    assert rs.swap_by_hash("tt9", HP, 2, None)["message"] == "unknown title"
    assert rs.swap_by_hash("tt2", HP, 7, None)["message"] == "nothing known about that season"
    assert rs.swap_by_hash("tt2", HQ, 2, None)["message"] == "that hash is not in the candidate list"
    unmatched = {"files": [{"id": 0, "name": "x/a.mkv", "size": 1}, {"id": 1, "name": "x/b.mkv", "size": 1}]}
    monkeypatch.setattr(torbox, "check_cached_files", lambda hashes, **k: {HP: unmatched})
    out = rs.swap_by_hash("tt2", HP, 2, None)
    assert out["ok"] is False and "no episode this season matches" in out["message"]
    assert db.get_virtual_item("t21")["info_hash"] == H1, "nothing changed"


def test_season_swap_onto_the_current_pack_only_fills_in_file_ids(season_fake):
    db.update_virtual_item_upgrade("t21", HP, "m", "1080p", None)
    out = rs.swap_by_hash("tt2", HP, 2, None)
    assert out["swapped"] == [2] and db.get_virtual_item("t21")["file_id"] == 0


def test_swap_route_accepts_a_season_without_an_episode():
    src = src_for_route("/ui/api/library/<imdb_id>/swap")
    body = src.split("def ui_api_library_swap(")[1].split("\ndef ")[0]
    assert "release_swap.parse_episode_ref(p.get(\"season\"), p.get(\"episode\"))" in body
    assert "swap_by_hash(" in body
