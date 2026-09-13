"""A pack that turned out not to contain an episode is never tried for that
episode again (wanted_episodes.excluded_hashes), and registering an episode
marks its wanted row found."""
import sqlite3
from types import SimpleNamespace

import pytest

import db
import monitor
import strm_generator as sg

H_PACK = "7593cbc1" + "0" * 32
H_SINGLE = "abcdef12" + "0" * 32


def _db_modules():
    """test_catbox_cache_sweep.py imports catbox against a fresh db module
    object; strm_generator, monitor and catbox may therefore be bound to a
    different `db` than this file. Isolate every one of them."""
    import catbox
    mods = []
    for m in (db, sg.db, monitor.db, catbox.db):
        if not any(m is x for x in mods):
            mods.append(m)
    return mods


def _drop_cached_conn():
    for m in _db_modules():
        conn = getattr(m._tls, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
            m._tls.conn = None


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    _drop_cached_conn()
    for m in _db_modules():
        monkeypatch.setattr(m, "DB_PATH", str(tmp_path / "test.db"))
    _drop_cached_conn()
    db.init()
    yield
    _drop_cached_conn()


def _cand(h, pack=False):
    return SimpleNamespace(info_hash=h, magnet=f"magnet:?xt=urn:btih:{h}", is_season_pack=pack,
                           quality="1080p", name="Reacher.S04", size_gb=1.0)


def _wanted(ep=4, status="wanted"):
    db.upsert_wanted_episode("tt9288030", 108978, "Reacher", 4, ep, "2026-08-19")
    db.mark_episode_status("tt9288030", 4, ep, status)
    return db.get_wanted_episode("tt9288030", 4, ep)


# db helpers

def test_exclusions_are_per_episode_deduplicated_and_ignore_unknown_rows():
    _wanted(4)
    _wanted(5)
    db.exclude_episode_hash("tt9288030", 4, 4, H_PACK.upper())
    db.exclude_episode_hash("tt9288030", 4, 4, H_PACK)
    db.exclude_episode_hash("tt9288030", 4, 4, H_SINGLE)
    db.exclude_episode_hash("tt9288030", 4, 9, H_PACK)   # no such row: no-op
    db.exclude_episode_hash("tt9288030", 4, 5, "")
    assert db.excluded_hashes_for("tt9288030", 4, 4) == {H_PACK, H_SINGLE}
    assert db.excluded_hashes_for("tt9288030", 4, 5) == set()
    assert db.excluded_hashes_for("tt9288030", 4, 9) == set()
    assert db.get_wanted_episode("tt9288030", 4, 4)["excluded_hashes"] == f"{H_PACK},{H_SINGLE}"


def test_migration_adds_the_column_to_an_existing_table(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(str(path))
    conn.execute("""CREATE TABLE wanted_episodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, imdb_id TEXT NOT NULL, tmdb_id INTEGER,
        title TEXT NOT NULL, season INTEGER NOT NULL, episode INTEGER NOT NULL, air_date TEXT,
        status TEXT NOT NULL DEFAULT 'wanted', attempt_count INTEGER NOT NULL DEFAULT 0,
        first_attempted TEXT, last_attempted TEXT, UNIQUE(imdb_id, season, episode))""")
    conn.execute("INSERT INTO wanted_episodes (imdb_id, title, season, episode) VALUES ('tt1', 'X', 1, 1)")
    conn.execute("INSERT INTO wanted_episodes (imdb_id, title, season, episode) VALUES ('tt2', 'Reacher (2022) S04E04', 4, 4)")
    conn.execute("INSERT INTO wanted_episodes (imdb_id, title, season, episode) VALUES ('tt3', 'S04E04 Show', 4, 4)")
    conn.commit(); conn.close()
    _drop_cached_conn()
    for m in _db_modules():
        monkeypatch.setattr(m, "DB_PATH", str(path))
    db.init()
    assert db.excluded_hashes_for("tt1", 1, 1) == set()
    db.exclude_episode_hash("tt1", 1, 1, H_PACK)
    assert db.excluded_hashes_for("tt1", 1, 1) == {H_PACK}
    # Rows seeded by 0.25.2 with the item title are repaired once.
    assert db.get_wanted_episode("tt2", 4, 4)["title"] == "Reacher (2022)"
    assert db.get_wanted_episode("tt3", 4, 4)["title"] == "S04E04 Show", "only a trailing suffix is stripped"


def test_filter_for_episode_drops_only_excluded_hashes_and_needs_an_episode():
    import blacklist
    _wanted(4)
    db.exclude_episode_hash("tt9288030", 4, 4, H_PACK)
    cands = [_cand(H_PACK.upper(), pack=True), _cand(H_SINGLE)]
    assert [c.info_hash for c in blacklist.filter_for_episode(cands, "tt9288030", 4, 4)] == [H_SINGLE.upper() if False else H_SINGLE]
    assert blacklist.filter_for_episode(cands, "tt9288030", 4, 5) == cands
    assert blacklist.filter_for_episode(cands, None, 4, 4) == cands
    assert blacklist.filter_for_episode(cands, "tt9288030", None, None) == cands
    assert blacklist.filter_for_episode([], "tt9288030", 4, 4) == []


def test_strm_exists_episode_finds_the_zero_padded_season_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor, "MEDIA_PATH", str(tmp_path))
    padded = tmp_path / "series" / "Reacher" / "Season 04"
    padded.mkdir(parents=True)
    (padded / "Reacher S04E01.strm").write_text("x")
    plain = tmp_path / "series" / "Reacher" / "Season 5"
    plain.mkdir(parents=True)
    (plain / "Reacher S05E02.strm").write_text("x")
    assert monitor.strm_exists_episode("Reacher", 4, 1) is True
    assert monitor.strm_exists_episode("Reacher", 5, 2) is True
    assert monitor.strm_exists_episode("Reacher", 4, 2) is False


# monitor retry

@pytest.fixture
def retry_env(monkeypatch):
    written = []
    monkeypatch.setattr(monitor._settings, "get", lambda key, default=None: True if key == "CATBOX_MODE" else default)
    monkeypatch.setattr(monitor.scrapers, "fetch_candidates",
                        lambda *a, **k: [_cand(H_PACK, pack=True), _cand(H_SINGLE)])
    monkeypatch.setattr(monitor.torbox, "check_cached", lambda hashes: set(hashes))
    monkeypatch.setattr(sg, "create_lazy_episode_strm",
                        lambda **kw: written.append(kw["info_hash"]) or True)
    return written


def test_retry_skips_releases_known_not_to_contain_the_episode(retry_env):
    ep = _wanted(4)
    db.exclude_episode_hash("tt9288030", 4, 4, H_PACK)
    assert monitor._retry_episode(db.get_wanted_episode("tt9288030", 4, 4)) is True
    assert retry_env == [H_SINGLE], "the pack sorted first, but it does not contain E04"
    assert db.get_wanted_episode("tt9288030", 4, 4)["status"] == "found"
    assert ep["attempt_count"] == 0 and db.get_wanted_episode("tt9288030", 4, 4)["attempt_count"] == 1


def test_retry_without_exclusions_still_prefers_the_first_cached_candidate(retry_env):
    monitor._retry_episode(_wanted(4))
    assert retry_env == [H_PACK]


def test_retry_with_only_excluded_candidates_stays_wanted(retry_env):
    ep = _wanted(4)
    db.exclude_episode_hash("tt9288030", 4, 4, H_PACK)
    db.exclude_episode_hash("tt9288030", 4, 4, H_SINGLE)
    assert monitor._retry_episode(ep) is False
    assert retry_env == [] and db.get_wanted_episode("tt9288030", 4, 4)["status"] == "wanted"


# lazy strm writer

@pytest.fixture
def media(tmp_path, monkeypatch):
    monkeypatch.setattr(sg, "MEDIA_PATH", str(tmp_path))
    monkeypatch.setattr(sg, "_write_spore_stubs", lambda *a, **k: None)
    monkeypatch.setattr(sg, "_write_nfo", lambda *a, **k: None)
    monkeypatch.setattr(sg.settings, "get", lambda key, default=None: False if key == "CATBOX_PRELOAD" else default)
    import nfo_generator
    monkeypatch.setattr(nfo_generator, "fetch_images_for_folder", lambda *a, **k: None)
    return tmp_path


def test_lazy_strm_refuses_an_excluded_hash_for_that_episode_only(media):
    _wanted(4)
    _wanted(5)
    db.exclude_episode_hash("tt9288030", 4, 4, H_PACK)
    assert sg.create_lazy_episode_strm(H_PACK, "magnet:?x", "Reacher", 4, 4, imdb_id="tt9288030") is False
    assert db.get_virtual_item_by_episode("tt9288030", 4, 4) is None
    assert not (media / "series" / "Reacher" / "Season 04" / "Reacher S04E04.strm").exists()
    assert sg.create_lazy_episode_strm(H_PACK, "magnet:?x", "Reacher", 4, 5, imdb_id="tt9288030") is True
    assert sg.create_lazy_episode_strm(H_SINGLE, "magnet:?y", "Reacher", 4, 4, imdb_id="tt9288030") is True
    assert db.get_virtual_item_by_episode("tt9288030", 4, 4)["info_hash"] == H_SINGLE


def test_registering_an_episode_marks_its_wanted_row_found(media):
    _wanted(4)
    assert sg.create_lazy_episode_strm(H_PACK, "magnet:?x", "Reacher", 4, 4, imdb_id="tt9288030") is True
    assert db.get_wanted_episode("tt9288030", 4, 4)["status"] == "found"
    # No wanted row: nothing to mark, still written.
    assert sg.create_lazy_episode_strm(H_PACK, "magnet:?x", "Reacher", 4, 6, imdb_id="tt9288030") is True
    assert db.get_wanted_episode("tt9288030", 4, 6) is None
