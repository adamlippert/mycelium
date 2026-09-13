"""Season packs at request time: TorBox lists a cached pack's files, so the
processor registers only the episodes the pack contains, with their file
ids, and puts the rest on the wanted list with the pack excluded."""
import os
from types import SimpleNamespace

import pytest

import db
import processor
import strm_generator as sg
import torbox

_ROOT = os.path.join(os.path.dirname(__file__), "..")
H_PACK = "7593cbc1" + "0" * 32
H_E4 = "aaaa0004" + "0" * 32


def _db_modules():
    import catbox
    mods = []
    for m in (db, sg.db, processor.db, catbox.db):
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


def _f(fid, name, size=1000):
    return {"id": fid, "name": name, "size": size}


PACK_FILES = [
    _f(0, "Reacher - S04 E01-08/S04E01 Reacher La Citta.mkv", 1694016661),
    _f(2, "Reacher - S04 E01-08/S04E02 Reacher Lotta.mkv", 1757267748),
    _f(1, "Reacher - S04 E01-08/S04E03 Reacher Un Piccolo Passo.mkv", 1604823551),
    _f(3, "Reacher - S04 E01-08/Sample/sample.mkv", 5000),
]


def _stream(h, pack=True, name="Reacher.S04.1080p"):
    return SimpleNamespace(info_hash=h, magnet=f"magnet:?xt=urn:btih:{h}", is_season_pack=pack,
                           quality="1080p", name=name, size_gb=4.7)


# torbox client

def test_check_cached_files_asks_for_the_file_list_and_keeps_it(monkeypatch):
    seen = {}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"success": True, "data": {H_PACK.upper(): {"name": "Reacher", "size": 5, "files": PACK_FILES}}}

    def fake_get(url, headers=None, params=None, timeout=None):
        seen.update(params)
        return Resp()

    monkeypatch.setattr(torbox.requests, "get", fake_get)
    monkeypatch.setattr(torbox, "_headers", lambda: {})
    out = torbox.check_cached_files([H_PACK])
    assert seen["list_files"] == "true" and seen["format"] == "object" and seen["hash"] == H_PACK
    assert [f["id"] for f in out[H_PACK]["files"]] == [0, 2, 1, 3]


def test_check_cached_files_returns_nothing_on_failure(monkeypatch):
    def boom(*a, **k):
        raise torbox.requests.ConnectionError("down")
    monkeypatch.setattr(torbox.requests, "get", boom)
    monkeypatch.setattr(torbox, "_headers", lambda: {})
    assert torbox.check_cached_files([H_PACK]) == {}


# shared mapper

def test_map_episodes_to_files_by_name_then_by_order():
    videos = sg.pack_videos(PACK_FILES)
    assert [f["id"] for f in videos] == [0, 2, 1], "the sample is not a video candidate"
    assert sg.map_episodes_to_files(videos, 4, list(range(1, 9))) == {1: 0, 2: 2, 3: 1}
    untagged = [_f(7, "pack/b.mkv"), _f(5, "pack/a.mkv"), _f(9, "pack/c.mkv")]
    assert sg.map_episodes_to_files(untagged, 4, [1, 2, 3]) == {1: 5, 2: 7, 3: 9}
    assert sg.map_episodes_to_files(untagged, 4, [1, 2, 3, 4]) == {}, "count mismatch: never guess"
    assert sg.map_episodes_to_files([], 4, [1]) == {}


# processor: what the pack contains

def test_pack_contents_with_files_known_and_unknown(monkeypatch):
    pack = _stream(H_PACK)
    monkeypatch.setattr(processor.torbox, "check_cached_files",
                        lambda hashes, **k: {H_PACK: {"files": PACK_FILES}})
    present, missing, ids = processor._pack_contents(pack, 4, list(range(1, 9)), count_known=True)
    assert (present, missing, ids) == ([1, 2, 3], [4, 5, 6, 7, 8], {1: 0, 2: 2, 3: 1})

    present, missing, ids = processor._pack_contents(pack, 4, list(range(1, 25)), count_known=False)
    assert (present, missing) == ([1, 2, 3], []), "unknown episode count: only what the names prove, nothing missing"

    monkeypatch.setattr(processor.torbox, "check_cached_files", lambda hashes, **k: {})
    present, missing, ids = processor._pack_contents(pack, 4, [1, 2, 3], count_known=True)
    assert (present, missing, ids) == ([1, 2, 3], [], {}), "no file list: register everything as before"

    # Files listed but unreadable (no tags, count differs): not proven wrong,
    # so nothing is missing or excluded; the first play reconciles.
    untagged = [_f(1, "pack/a.mkv"), _f(2, "pack/b.mkv")]
    monkeypatch.setattr(processor.torbox, "check_cached_files", lambda hashes, **k: {H_PACK: {"files": untagged}})
    assert processor._pack_contents(pack, 4, list(range(1, 9)), count_known=True) == (list(range(1, 9)), [], {})
    assert processor._pack_contents(pack, 4, list(range(1, 25)), count_known=False) == (list(range(1, 25)), [], {})

    def boom(hashes, **k):
        raise RuntimeError("torbox down")
    monkeypatch.setattr(processor.torbox, "check_cached_files", boom)
    assert processor._pack_contents(pack, 4, [1, 2], count_known=True) == ([1, 2], [], {})


@pytest.fixture
def season_env(monkeypatch):
    """A cached partial pack (E1 to E3 of eight), TMDB knows eight episodes
    with E8 unaired, and a per-episode search finds a cached single for E4."""
    import blacklist
    import debrid
    written = []
    monkeypatch.setattr(blacklist, "filter_candidates", lambda c: list(c))
    monkeypatch.setattr(debrid, "check_cached_multi", lambda hashes: {"torbox": set(hashes)})
    monkeypatch.setattr(processor.torbox, "check_cached_files",
                        lambda hashes, **k: {H_PACK: {"files": PACK_FILES}})
    eps = [{"episode_number": n, "air_date": "2026-08-12"} for n in range(1, 8)] + [{"episode_number": 8, "air_date": "2999-01-01"}]
    monkeypatch.setattr(processor, "_get_season_episodes", lambda i, s: (108978, eps))

    def fetch(req, season, episode=1, prefer_season_pack=False):
        if prefer_season_pack:
            return [_stream(H_PACK)]
        return [_stream(H_PACK)] + ([_stream(H_E4, pack=False, name="Reacher.S04E04.1080p")] if episode == 4 else [])
    monkeypatch.setattr(processor, "_fetch_season_candidates", fetch)

    def fake_create(info_hash, magnet, title, season, episode, **kw):
        written.append((episode, info_hash[:8], kw.get("file_id")))
        db.mark_episode_status("tt9288030", season, episode, "found")
        return True
    monkeypatch.setattr(sg, "create_lazy_episode_strm", fake_create)
    return written


def _req():
    from webhook_parser import MediaRequest
    return MediaRequest(title="Reacher", media_type="series", imdb_id="tt9288030", seasons=[4], tmdb_id=108978)


def test_partial_pack_registers_its_episodes_with_file_ids_and_wants_the_rest(season_env):
    ok, winner = processor._lazy_register_season(_req(), 4)
    assert ok is True and winner.info_hash == H_PACK
    assert season_env[:3] == [(1, "7593cbc1", 0), (2, "7593cbc1", 2), (3, "7593cbc1", 1)]
    # E4 found right away as a single episode, from a candidate list where the pack came first.
    assert season_env[3:] == [(4, "aaaa0004", None)]
    rows = {w["episode"]: w for w in db.get_all_wanted_episodes() if w["imdb_id"] == "tt9288030"}
    assert {e: r["status"] for e, r in rows.items()} == {4: "found", 5: "wanted", 6: "wanted", 7: "wanted", 8: "not_aired"}
    assert all(db.excluded_hashes_for("tt9288030", 4, e) == {H_PACK} for e in range(4, 9))
    assert rows[8]["air_date"] == "2999-01-01" and rows[5]["title"] == "Reacher" and rows[5]["tmdb_id"] == 108978
    assert 1 not in rows and 2 not in rows and 3 not in rows, "present episodes need no wanted row"


def test_full_pack_registers_every_episode_without_wanted_rows(season_env, monkeypatch):
    full = [_f(i, f"pack/Reacher S04E{i + 1:02d}.mkv") for i in range(8)]
    monkeypatch.setattr(processor.torbox, "check_cached_files", lambda hashes, **k: {H_PACK: {"files": full}})
    ok, _ = processor._lazy_register_season(_req(), 4)
    assert ok is True
    assert [(e, fid) for e, _, fid in season_env] == [(e, e - 1) for e in range(1, 9)]
    assert not [w for w in db.get_all_wanted_episodes() if w["imdb_id"] == "tt9288030"]


def test_pack_with_unknown_contents_registers_all_without_file_ids(season_env, monkeypatch):
    monkeypatch.setattr(processor.torbox, "check_cached_files", lambda hashes, **k: {})
    ok, _ = processor._lazy_register_season(_req(), 4)
    assert ok is True
    assert [(e, fid) for e, _, fid in season_env] == [(e, None) for e in range(1, 9)]
    assert not [w for w in db.get_all_wanted_episodes() if w["imdb_id"] == "tt9288030"]


def test_a_failing_single_episode_search_leaves_the_episode_wanted(season_env, monkeypatch):
    def fetch(req, season, episode=1, prefer_season_pack=False):
        if prefer_season_pack:
            return [_stream(H_PACK)]
        raise RuntimeError("scrapers down")
    monkeypatch.setattr(processor, "_fetch_season_candidates", fetch)
    ok, _ = processor._lazy_register_season(_req(), 4)
    assert ok is True and len(season_env) == 3
    rows = {w["episode"]: w["status"] for w in db.get_all_wanted_episodes() if w["imdb_id"] == "tt9288030"}
    assert rows == {4: "wanted", 5: "wanted", 6: "wanted", 7: "wanted", 8: "not_aired"}


def test_the_per_episode_fallback_honours_exclusions():
    src = open(os.path.join(_ROOT, "processor.py")).read()
    body = src.split("# --- Fall back to per-episode cached registration ---")[1]
    assert "blacklist.filter_for_episode(ep_cands_raw, req.imdb_id, season, episode)" in body


# lazy strm writer

def test_file_id_reaches_the_virtual_item(tmp_path, monkeypatch):
    monkeypatch.setattr(sg, "MEDIA_PATH", str(tmp_path))
    monkeypatch.setattr(sg, "_write_spore_stubs", lambda *a, **k: None)
    monkeypatch.setattr(sg, "_write_nfo", lambda *a, **k: None)
    monkeypatch.setattr(sg.settings, "get", lambda key, default=None: False if key == "CATBOX_PRELOAD" else default)
    import nfo_generator
    monkeypatch.setattr(nfo_generator, "fetch_images_for_folder", lambda *a, **k: None)
    assert sg.create_lazy_episode_strm(H_PACK, "magnet:?x", "Reacher", 4, 2, imdb_id="tt9288030", file_id=2) is True
    assert sg.create_lazy_episode_strm(H_PACK, "magnet:?x", "Reacher", 4, 3, imdb_id="tt9288030") is True
    assert db.get_virtual_item_by_episode("tt9288030", 4, 2)["file_id"] == 2
    assert db.get_virtual_item_by_episode("tt9288030", 4, 3)["file_id"] is None


def test_unreadable_pack_registers_every_episode_and_excludes_nothing(season_env, monkeypatch):
    untagged = [_f(1, "pack/a.mkv"), _f(2, "pack/b.mkv")]
    monkeypatch.setattr(processor.torbox, "check_cached_files", lambda hashes, **k: {H_PACK: {"files": untagged}})
    ok, _ = processor._lazy_register_season(_req(), 4)
    assert ok is True and [(e, fid) for e, _, fid in season_env] == [(e, None) for e in range(1, 9)]
    assert not [w for w in db.get_all_wanted_episodes() if w["imdb_id"] == "tt9288030"]


def test_immediate_searches_are_capped_and_the_rest_wait_for_the_monitor(season_env, monkeypatch):
    fetched = []

    def fetch(req, season, episode=1, prefer_season_pack=False):
        if prefer_season_pack:
            return [_stream(H_PACK)]
        fetched.append(episode)
        return [_stream(H_PACK)]
    monkeypatch.setattr(processor, "_fetch_season_candidates", fetch)
    monkeypatch.setattr(processor, "_IMMEDIATE_SEARCH_CAP", 2)
    ok, _ = processor._lazy_register_season(_req(), 4)
    assert ok is True and fetched == [4, 5]
    rows = {w["episode"]: w["status"] for w in db.get_all_wanted_episodes() if w["imdb_id"] == "tt9288030"}
    assert rows == {4: "wanted", 5: "wanted", 6: "wanted", 7: "wanted", 8: "not_aired"}
    assert all(db.excluded_hashes_for("tt9288030", 4, e) == {H_PACK} for e in (6, 7)), "excluded even when not searched now"


def test_an_episode_already_in_the_library_is_neither_wanted_nor_excluded(season_env, monkeypatch):
    monkeypatch.setattr(processor, "_already_registered", lambda imdb, s, e: e == 5)
    processor._lazy_register_season(_req(), 4)
    rows = {w["episode"] for w in db.get_all_wanted_episodes() if w["imdb_id"] == "tt9288030"}
    assert 5 not in rows and db.excluded_hashes_for("tt9288030", 4, 5) == set()


def test_materialize_treats_a_preset_file_id_of_zero_as_known():
    """TorBox file ids start at 0. `if not file_id` sent the first episode of
    every pack through the listing again on each play, and failed it when
    the single-item endpoint omitted the files list."""
    src = open(os.path.join(_ROOT, "catbox.py")).read()
    body = src.split("def materialize(")[1]
    assert "    if file_id is None:\n        live = torbox.find_by_id(torbox_id)" in body
    assert 'if file_id is not None and is_episode and db.hash_has_duplicate_file_ids(item["info_hash"]):' in body
    assert "    if not file_id:\n        live = torbox.find_by_id" not in body
