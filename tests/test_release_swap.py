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


def _item(imdb, token, info_hash, season=None, episode=None, quality="1080p"):
    with db._connect() as conn:
        conn.execute(
            "INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, strm_path, imdb_id, season, episode, quality) "
            "VALUES (?, ?, ?, 'Heat', ?, ?, ?, ?, ?, ?)",
            (token, info_hash, f"magnet:?xt=urn:btih:{info_hash}", "movie" if season is None else "series",
             f"/media/{token}.strm", imdb, season, episode, quality))
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
    _item("tt1", "tok", H4)
    out = rs.candidates("tt1", "movie")
    assert out["current"] == {"info_hash": H4, "quality": "1080p", "source": None}
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
