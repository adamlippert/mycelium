"""A play uses the account that holds the torrent. An unhomed item adopts
the account whose library already has the hash, else the pool's choice;
a disabled home, an auth failure or a gone torrent re-homes; a 429 does
not."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
_prior = sys.modules.get("torbox")
sys.modules.pop("torbox", None)
import torbox  # noqa: E402
if _prior is not None:
    sys.modules["torbox"] = _prior
else:
    sys.modules.pop("torbox", None)

import catbox  # noqa: E402
import torbox_pool as pool  # noqa: E402

# catbox.py may already be cached (imported by an earlier test module) with
# its own `torbox` reference bound before this file's sys.modules dance ran;
# alias to that exact object so monkeypatching torbox.* here actually
# reaches the calls catbox.py makes.
torbox = catbox.torbox

db = catbox.db
H = "a" * 40


def _db_modules():
    """test_catbox_cache_sweep.py imports catbox against a fresh db module
    object; isolate every db object the code under test may be bound to."""
    mods = []
    for m in (db, catbox.db, pool.db):
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
    monkeypatch.setenv("TORBOX_API_KEY", "k1")
    _drop_cached_conn()
    db.init()
    db.insert_torbox_account("second", "k2")
    pool.invalidate()
    pool._health.clear()
    catbox.invalidate_url_cache()
    torbox.invalidate_mylist_cache()
    monkeypatch.setattr(catbox._settings, "get", lambda k, d=None: {"CATBOX_MODE": True}.get(k, d))
    yield
    _drop_cached_conn()


def _item(token="t", torbox_id=None, account=None, info_hash=H):
    with db._connect() as conn:
        conn.execute("INSERT INTO virtual_items (token, info_hash, magnet, title, media_type, torbox_id, torbox_account, file_id) "
                     "VALUES (?, ?, ?, 'Heat', 'movie', ?, ?, 0)", (token, info_hash, f"magnet:?xt=urn:btih:{info_hash}", torbox_id, account))
        conn.commit()
    return db.get_virtual_item(token)


READY = {"id": 5, "hash": H, "download_state": "cached", "download_finished": True, "files": [{"id": 0, "name": "Heat.mkv", "size": 10}]}


@pytest.fixture
def client(monkeypatch):
    """A fake TorBox: per-account libraries and a recorder of every call."""
    libs = {1: [], 2: []}
    calls = []
    monkeypatch.setattr(torbox, "find_by_id", lambda acct, tid, **k: (calls.append(("find_by_id", acct, tid)), next((t for t in libs[acct] if t["id"] == tid), None))[1])
    monkeypatch.setattr(torbox, "find_by_hash", lambda acct, h, **k: (calls.append(("find_by_hash", acct)), next((t for t in libs[acct] if t["hash"] == h), None))[1])
    monkeypatch.setattr(torbox, "list_torrents", lambda acct, **k: list(libs[acct]))
    def add(acct, magnet, **k):
        calls.append(("add", acct))
        t = dict(READY, id=len(libs[acct]) + 10)
        libs[acct].append(t)
        return t
    monkeypatch.setattr(torbox, "add_magnet", add)
    monkeypatch.setattr(torbox, "wait_until_ready", lambda acct, h, **k: next((t for t in libs[acct] if t["hash"] == h), None))
    monkeypatch.setattr(torbox, "request_download_link", lambda acct, tid, fid, **k: (calls.append(("link", acct, tid)), f"https://cdn/{acct}/{tid}")[1])
    monkeypatch.setattr(torbox, "_is_ready", lambda t: bool(t and t.get("download_finished")))
    return libs, calls


def test_a_homed_item_plays_from_its_home_and_nothing_else(client):
    libs, calls = client
    libs[2].append(dict(READY))
    _item(torbox_id=5, account=2)
    assert catbox.materialize("t") == "https://cdn/2/5"
    assert all(c[1] == 2 for c in calls) and ("add", 2) not in calls


def test_an_unhomed_item_adopts_the_account_that_already_has_the_hash(client):
    libs, calls = client
    libs[2].append(dict(READY))
    _item()
    assert catbox.materialize("t") == "https://cdn/2/5"
    it = db.get_virtual_item("t")
    assert (it["torbox_id"], it["torbox_account"]) == (5, 2)
    assert ("add", 1) not in calls and ("add", 2) not in calls


def test_an_unhomed_item_goes_to_the_pools_choice(client, monkeypatch):
    libs, calls = client
    monkeypatch.setattr(pool, "choose_for_add", lambda: pool.account(2))
    _item()
    assert catbox.materialize("t") == "https://cdn/2/10"
    it = db.get_virtual_item("t")
    assert (it["torbox_id"], it["torbox_account"]) == (10, 2)
    assert ("add", 2) in calls and ("add", 1) not in calls


def test_a_disabled_home_re_homes_on_the_next_play(client, monkeypatch):
    libs, calls = client
    libs[2].append(dict(READY))
    _item(torbox_id=5, account=2)
    db.update_torbox_account(2, enabled=False)
    pool.invalidate()
    monkeypatch.setattr(pool, "choose_for_add", lambda: pool.account(1))
    assert catbox.materialize("t") == "https://cdn/1/10"
    assert db.get_virtual_item("t")["torbox_account"] == 1


def test_an_auth_failure_from_the_home_re_homes(client, monkeypatch):
    libs, calls = client
    _item(torbox_id=5, account=2)
    def failing(acct, tid, **k):
        if acct == 2:
            raise torbox.AuthFailed("account 2: 403")
        return next((t for t in libs[acct] if t["id"] == tid), None)
    monkeypatch.setattr(torbox, "find_by_id", failing)
    monkeypatch.setattr(pool, "choose_for_add", lambda: pool.account(1))
    assert catbox.materialize("t") == "https://cdn/1/10"
    assert db.get_virtual_item("t")["torbox_account"] == 1


def test_a_gone_torrent_re_homes_but_a_429_does_not(client, monkeypatch):
    libs, calls = client
    _item(torbox_id=5, account=2)          # not in libs[2]: gone
    monkeypatch.setattr(pool, "choose_for_add", lambda: pool.account(1))
    assert catbox.materialize("t") == "https://cdn/1/10"
    assert db.get_virtual_item("t")["torbox_account"] == 1

    calls.clear()
    def limited(acct, magnet, **k):
        raise torbox.RateLimited()
    monkeypatch.setattr(torbox, "add_magnet", limited)
    # A distinct hash: "t"'s add just landed hash H in account 1's library,
    # so an item sharing H would legitimately adopt it for free instead of
    # hitting the (rate-limited) add path this asserts against.
    _item(token="u", info_hash="b" * 40)
    monkeypatch.setattr(pool, "choose_for_add", lambda: pool.account(2))
    assert catbox.materialize("u") is None
    assert db.get_virtual_item("u")["torbox_account"] is None, "no home recorded for a refused add"


def test_no_enabled_account_fails_the_play_instead_of_crashing(client):
    """choose_for_add() raises RuntimeError when every account is disabled;
    an unhomed item must degrade to a cooldown, never an unhandled 500."""
    db.update_torbox_account(1, enabled=False)
    db.update_torbox_account(2, enabled=False)
    pool.invalidate()
    _item()
    assert catbox.materialize("t") is None


def test_fixed_mode_adders_pass_one_account_through_an_operation():
    src = open(os.path.join(os.path.dirname(__file__), "..", "processor.py")).read()
    body = src.split("def _try_add_magnet(")[1].split("\ndef ")[0]
    assert "torbox_pool.choose_for_add()" in body
    assert "torbox.add_magnet(acct" in body and "torbox.wait_until_ready(acct" in body
