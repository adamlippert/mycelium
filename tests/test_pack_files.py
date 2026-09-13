"""Season packs: matching episodes to files, never playing the wrong one,
and detaching episodes the pack does not contain (catbox._resolve_pack_files)."""
import os
import re

import pytest

import catbox
import strm_generator as sg

# test_catbox_cache_sweep.py imports catbox against a fresh db module object
# and then restores sys.modules; use the db object catbox itself is bound to,
# so the fixture's DB_PATH and the code under test agree.
db = catbox.db

_ROOT = os.path.join(os.path.dirname(__file__), "..")
H = "7593cbc1" + "0" * 32


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
    catbox.invalidate_url_cache()
    yield
    _drop_cached_conn()


def _f(fid, name, size=1000):
    return {"id": fid, "name": name, "size": size}


# -- name matching -------------------------------------------------------------

@pytest.mark.parametrize("name,season,episode,expected", [
    ("Show/S04E03 Title.mkv", 4, 3, True),
    ("Show.S4E3.mkv", 4, 3, True),
    ("Show.S04.E03.mkv", 4, 3, True),
    ("Show S04 E03.mkv", 4, 3, True),
    ("Show - 4x03 - Title.mkv", 4, 3, True),
    ("E03.mkv", 4, 3, True),
    ("Ep03 Title.mkv", 4, 3, True),
    ("Show Episode 3.mkv", 4, 3, True),
    ("03 - Title.mkv", 4, 3, True),
    ("03. Title.mkv", 4, 3, True),
    ("Show.S04E30.mkv", 4, 3, False),
    ("Show.S03E03.mkv", 4, 3, False),
    ("Season 4/Show.S03E03.mkv", 4, 3, False),
    ("1080p.mkv", 4, 1, False),
    ("Show.S04E01.mkv", 4, 10, False),
    ("Show.S04E10.mkv", 4, 1, False),
])
def test_episode_matches_the_common_naming_forms(name, season, episode, expected):
    assert sg.episode_matches(name, season, episode) is expected


def test_pick_episode_file_never_falls_back_to_the_largest_file():
    files = [_f(0, "Show.S04E01.mkv", 5), _f(1, "Show.S04E02.mkv", 9)]
    assert sg._pick_episode_file(files, 4, 2)["id"] == 1
    assert sg._pick_episode_file(files, 4, 5) is None
    assert sg._pick_episode_file([_f(0, "Show.S04E05.sample.mkv", 1)], 4, 5) is None, "samples are not episodes"


# -- reconciliation at first play -----------------------------------------------

def _seed_season(media, episodes, file_ids=None):
    rid = db.insert_request("Reacher", "tt9288030", "series", tmdb_id=108978)
    db.update_request(rid, "success")
    folder = media / "Reacher" / "Season 04"
    folder.mkdir(parents=True, exist_ok=True)
    tokens = {}
    with db._connect() as conn:
        for ep in episodes:
            strm = folder / f"Reacher - S04E{ep:02d}.strm"
            strm.write_text("http://x/stream/t")
            (folder / f"Reacher - S04E{ep:02d}.nfo").write_text("<episodedetails/>")
            tok = f"tok{ep}"
            tokens[ep] = tok
            conn.execute(
                "INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, strm_path, imdb_id, season, episode, torbox_id, file_id) "
                "VALUES (?, ?, ?, 'Reacher', 'series', ?, 'tt9288030', 4, ?, 87201715, ?)",
                (tok, H, f"magnet:?xt=urn:btih:{H}", str(strm), ep, (file_ids or {}).get(ep)))
        conn.commit()
    return tokens, folder


REACHER_FILES = [
    _f(0, "Reacher - S04 E01-08/S04E01 Reacher La Citta.mkv", 1694016661),
    _f(2, "Reacher - S04 E01-08/S04E02 Reacher Lotta.mkv", 1757267748),
    _f(1, "Reacher - S04 E01-08/S04E03 Reacher Un Piccolo Passo.mkv", 1604823551),
]


def test_a_partial_pack_keeps_its_episodes_and_detaches_the_rest(tmp_path, monkeypatch):
    noted = []
    import jellyfin
    monkeypatch.setattr(jellyfin, "note_change", lambda path, kind: noted.append((path, kind)))
    tokens, folder = _seed_season(tmp_path, range(1, 9), file_ids={1: 0, 2: 2, 3: 1, 4: 2, 5: 2, 6: 2, 7: 2, 8: 2})
    assert db.hash_has_duplicate_file_ids(H) is True

    item = db.get_virtual_item(tokens[5])
    out = catbox._resolve_pack_files(tokens[5], item, {"files": REACHER_FILES})

    assert out is None, "episode 5 is not in the pack, so nothing plays for it"
    assert {db.get_virtual_item(tokens[e])["file_id"] for e in (1, 2, 3)} == {0, 2, 1}
    for ep in range(4, 9):
        assert db.get_virtual_item(tokens[ep]) is None
        assert not (folder / f"Reacher - S04E{ep:02d}.strm").exists()
        assert not (folder / f"Reacher - S04E{ep:02d}.nfo").exists()
    for ep in range(1, 4):
        assert (folder / f"Reacher - S04E{ep:02d}.strm").exists()
    wanted = {(w["season"], w["episode"]): w["status"] for w in db.get_all_wanted_episodes() if w["imdb_id"] == "tt9288030"}
    assert wanted == {(4, e): "wanted" for e in range(4, 9)}
    assert sorted(k for _, k in noted) == ["Deleted"] * 5
    assert db.hash_has_duplicate_file_ids(H) is False


def test_the_playing_episode_gets_its_own_file(tmp_path, monkeypatch):
    import jellyfin
    monkeypatch.setattr(jellyfin, "note_change", lambda path, kind: None)
    tokens, _ = _seed_season(tmp_path, [1, 2, 3])
    item = db.get_virtual_item(tokens[2])
    assert catbox._resolve_pack_files(tokens[2], item, {"files": REACHER_FILES}) == 2
    assert db.get_virtual_item(tokens[2])["file_id"] == 2


def test_untagged_files_map_by_order_only_with_one_file_per_episode(tmp_path, monkeypatch):
    import jellyfin
    monkeypatch.setattr(jellyfin, "note_change", lambda path, kind: None)
    tokens, _ = _seed_season(tmp_path, [1, 2, 3])
    files = [_f(7, "Reacher/c-third.mkv"), _f(5, "Reacher/a-first.mkv"), _f(6, "Reacher/b-second.mkv")]
    item = db.get_virtual_item(tokens[3])
    assert catbox._resolve_pack_files(tokens[3], item, {"files": files}) == 7
    assert [db.get_virtual_item(tokens[e])["file_id"] for e in (1, 2, 3)] == [5, 6, 7]


def test_a_count_mismatch_without_tags_detaches_instead_of_guessing(tmp_path, monkeypatch):
    import jellyfin
    monkeypatch.setattr(jellyfin, "note_change", lambda path, kind: None)
    tokens, _ = _seed_season(tmp_path, [1, 2, 3])
    files = [_f(5, "Reacher/a.mkv"), _f(6, "Reacher/b.mkv")]
    item = db.get_virtual_item(tokens[1])
    assert catbox._resolve_pack_files(tokens[1], item, {"files": files}) is None
    assert all(db.get_virtual_item(tokens[e]) is None for e in (1, 2, 3))


def test_an_empty_file_list_changes_nothing(tmp_path, monkeypatch):
    import jellyfin
    monkeypatch.setattr(jellyfin, "note_change", lambda path, kind: (_ for _ in ()).throw(AssertionError("no change expected")))
    tokens, folder = _seed_season(tmp_path, [1, 2, 3])
    item = db.get_virtual_item(tokens[2])
    assert catbox._resolve_pack_files(tokens[2], item, {"files": []}) is None
    assert all(db.get_virtual_item(tokens[e]) is not None for e in (1, 2, 3))
    assert (folder / "Reacher - S04E02.strm").exists()


def test_materialize_reconciles_a_pack_with_colliding_files_and_movies_keep_their_rule():
    src = open(os.path.join(_ROOT, "catbox.py"), encoding="utf-8").read()
    body = src.split("def materialize(", 1)[1]
    assert "db.hash_has_duplicate_file_ids(item[\"info_hash\"])" in body
    assert "file_id = _resolve_pack_files(token, item, live)" in body
    assert "max(videos, key=lambda f: f.get(\"size\") or 0) if videos else None" in body, "non-episode series items keep the largest-file rule"
    episode_branch = body.split("elif is_episode:", 1)[1].split("else:", 1)[0]
    assert "max(videos" not in episode_branch
