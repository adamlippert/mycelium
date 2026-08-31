"""F3 fix round 1: the legacy single-user login (AUTH_USERNAME/AUTH_PASSWORD)
has no real users-table row - auth.current_user_record() hands back a
synthetic dict with id=0 (auth.py:170) - so it cannot persist a region via
db.update_user(rec["id"], ...) the way a real user account does. That login
is single-user by definition, so its region is instead a runtime setting,
LEGACY_USER_REGION, written by POST /ui/api/me/region and read back by
GET /ui/api/session.

app.py is not imported here (heavy Flask/APScheduler module-level setup,
no established test pattern does); route bodies are asserted on the source
text instead, same approach as tests/test_ui_v2_cutover.py. The settings
half is a real, isolated-DB settings.get/set round trip.
"""
import os
import re
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

sys.modules.pop("settings", None)

import pytest

import db
import settings

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _src(name):
    with open(os.path.join(_ROOT, name), encoding="utf-8") as f:
        return f.read()


def _func_body(src: str, name: str) -> str:
    m = re.search(rf"def {name}\(.*?\n(?=@app\.|\ndef )", src, re.S)
    assert m, name
    return m.group(0)


def _drop_cached_conn():
    # db._connect() caches one sqlite3 connection per thread for the process
    # lifetime (db.py's _tls); monkeypatching db.DB_PATH alone leaves that
    # cached handle pointed at the previous test's tmp file. Same pattern as
    # tests/test_quota.py's _isolated_db.
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


# ── settings-layer: LEGACY_USER_REGION is a plain, unregistered string key ──

def test_legacy_user_region_round_trips_through_settings():
    settings.set("LEGACY_USER_REGION", "DE")
    assert settings.get("LEGACY_USER_REGION", "US") == "DE"


def test_legacy_user_region_defaults_to_us_when_never_set():
    # Not in config.py either, so settings.get() has nothing to fall back to
    # except the explicit default passed in - this is what a fresh install
    # (no LEGACY_USER_REGION row yet) reads.
    assert settings.get("LEGACY_USER_REGION", "US") == "US"


# ── app.py source: POST /ui/api/me/region persists the shim to settings ──

def test_id_zero_save_writes_legacy_user_region_instead_of_failing():
    body = _func_body(_src("app.py"), "ui_api_me_region")
    assert "LEGACY_USER_REGION" in body
    assert '_settings.set("LEGACY_USER_REGION", region)' in body
    # Round 0 shipped a 409 for this case; round 1 replaces it with a
    # genuine save, so the shim must return ok, not fail.
    assert "409" not in body
    assert re.search(r'if not rec\.get\("id"\):.*?jsonify\(ok=True, region=region\)', body, re.S)


def test_real_user_save_still_goes_through_db_update_user():
    body = _func_body(_src("app.py"), "ui_api_me_region")
    assert 'db.update_user(rec["id"], region=region)' in body


# ── app.py source: GET /ui/api/session's default chain ──

def test_session_region_prefers_row_value_then_legacy_setting_then_us():
    body = _func_body(_src("app.py"), "ui_api_session")
    # Real users (id truthy): row value, else "US" - never the old "NL".
    assert 'region = rec.get("region") or "US"' in body
    # Legacy shim (id falsy / 0): row value (never present) falls through to
    # the LEGACY_USER_REGION setting, else "US".
    assert 'region = rec.get("region") or _settings.get("LEGACY_USER_REGION", "US")' in body
    # The round-0 bug: baked "NL" in unconditionally before any frontend
    # fallback could ever run.
    assert 'rec.get("region", "NL")' not in body
