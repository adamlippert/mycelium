"""The legacy single-user login (AUTH_USERNAME/AUTH_PASSWORD) has no real
users-table row: auth.current_user_record() hands back a synthetic dict with
id=0, so db.update_user(0, ...) matches nothing and silently no-ops. The
0.8.3 region fix solved this for /ui/api/me/region via LEGACY_USER_REGION;
this covers the remaining two write paths of the same bug class,
/ui/api/me/preferences and /ui/api/me/plugin-fields, via a LEGACY_USER_PREFS
settings blob that the shim record overlays on read.

Route bodies are asserted on source text (app.py is never imported by tests);
the storage half is a real settings round trip on an isolated DB, same
approach as tests/test_region_persistence.py.
"""
import json
import os
import re
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

sys.modules.pop("settings", None)

import pytest

import auth
import db
import settings

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


# -- storage ------------------------------------------------------------------

def test_prefs_round_trip():
    auth.save_legacy_user_prefs({"library_click_jellyfin": 1})
    assert auth.legacy_user_prefs() == {"library_click_jellyfin": 1}


def test_saves_merge_instead_of_replacing():
    """Preferences and plugin fields write through the same blob; saving one
    must not wipe the other."""
    auth.save_legacy_user_prefs({"library_click_jellyfin": 1})
    auth.save_legacy_user_prefs({"webplayer_enabled": 0})

    assert auth.legacy_user_prefs() == {
        "library_click_jellyfin": 1, "webplayer_enabled": 0}


def test_unset_or_corrupt_blob_reads_as_empty():
    assert auth.legacy_user_prefs() == {}
    settings.set("LEGACY_USER_PREFS", "not json{")
    assert auth.legacy_user_prefs() == {}


# -- the shim record carries the prefs ----------------------------------------

def test_the_legacy_record_overlays_stored_prefs():
    """Every reader of current_user_record() - the session payload, plugin
    session_fields, webplayer checks - must see the saved values without
    knowing where they came from."""
    src = _src("auth.py")
    m = re.search(r"if legacy_role:(.*?)\n    # OIDC", src, re.S)
    assert m, "legacy branch not found"
    assert "legacy_user_prefs()" in m.group(1)


def test_overlay_can_override_the_shim_defaults():
    """The synthetic record defaults webplayer_enabled to 1; a saved 0 must
    win over that default."""
    auth.save_legacy_user_prefs({"webplayer_enabled": 0})
    rec = {"id": 0, "webplayer_enabled": 1}
    rec.update(auth.legacy_user_prefs())
    assert rec["webplayer_enabled"] == 0


# -- the write handlers -------------------------------------------------------

def _route_body(src, route):
    m = re.search(
        rf'@app\.post\(["\']{re.escape(route)}["\']\).*?\n(.*?)\n@app\.', src, re.S)
    assert m, route
    return m.group(1)


def test_preferences_route_persists_for_the_legacy_login():
    body = _route_body(_src("app.py"), "/ui/api/me/preferences")
    assert "save_legacy_user_prefs" in body


def test_plugin_fields_route_persists_for_the_legacy_login():
    body = _route_body(_src("app.py"), "/ui/api/me/plugin-fields")
    assert "save_legacy_user_prefs" in body


def test_real_users_still_write_to_their_row():
    """The settings blob is only for id=0; a real user row keeps the
    db.update_user path in both handlers."""
    src = _src("app.py")
    for route in ("/ui/api/me/preferences", "/ui/api/me/plugin-fields"):
        body = _route_body(src, route)
        assert 'db.update_user(rec["id"]' in body
        assert 'if not rec.get("id")' in body


def test_stored_blob_is_json():
    auth.save_legacy_user_prefs({"library_click_jellyfin": 1})
    raw = db.get_setting("LEGACY_USER_PREFS")
    assert json.loads(raw) == {"library_click_jellyfin": 1}
