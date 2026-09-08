"""Webhook secret rotation with a grace window (webhook_secret.py)."""
import os
import re

import pytest

import config as cfg
import db
import webhook_secret as ws

_ROOT = os.path.join(os.path.dirname(__file__), "..")


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
    monkeypatch.setattr(cfg, "WEBHOOK_SECRET", "")
    monkeypatch.setattr(ws, "_now", lambda: 1_000_000.0)
    yield
    _drop_cached_conn()


def _src(name):
    return open(os.path.join(_ROOT, name), encoding="utf-8").read()


def test_rotate_issues_a_new_secret_and_keeps_the_old_one_for_the_grace_window(monkeypatch):
    import settings
    settings.set(ws.KEY_AUTO, "old-secret")
    out = ws.rotate()
    assert out["source"] == "auto"
    assert out["secret"] != "old-secret" and len(out["secret"]) >= 32
    assert out["previous_valid_until"] == "1970-01-13T13:46:40Z"  # 1_000_000 s + 24 h, UTC
    assert ws.effective() == out["secret"]
    assert ws.accepts(out["secret"]) == "current"
    assert ws.accepts("old-secret") == "previous"
    assert ws.accepts("nonsense") is None
    assert ws.accepts("") is None
    # One second before the window closes the old value still passes; after it, not.
    monkeypatch.setattr(ws, "_now", lambda: 1_000_000.0 + ws.GRACE_SEC - 1)
    assert ws.accepts("old-secret") == "previous"
    monkeypatch.setattr(ws, "_now", lambda: 1_000_000.0 + ws.GRACE_SEC)
    assert ws.accepts("old-secret") is None
    assert ws.status()["previous_valid_until"] is None
    assert settings.get(ws.KEY_PREVIOUS, "") in ("", None), "an expired previous value is cleared"


def test_the_new_secret_itself_never_expires(monkeypatch):
    import settings
    settings.set(ws.KEY_AUTO, "old-secret")
    new = ws.rotate()["secret"]
    monkeypatch.setattr(ws, "_now", lambda: 1_000_000.0 + 400 * 24 * 3600)
    assert ws.accepts(new) == "current"


def test_a_second_rotation_replaces_the_previous_value():
    import settings
    settings.set(ws.KEY_AUTO, "first")
    second = ws.rotate()["secret"]
    third = ws.rotate()["secret"]
    assert ws.accepts(third) == "current"
    assert ws.accepts(second) == "previous"
    assert ws.accepts("first") is None, "only one previous value is kept"


def test_rotate_refuses_when_the_secret_comes_from_the_environment(monkeypatch):
    monkeypatch.setattr(cfg, "WEBHOOK_SECRET", "env-secret")
    assert ws.status() == {"secret": "env-secret", "source": "env", "previous_valid_until": None}
    with pytest.raises(RuntimeError):
        ws.rotate()
    assert ws.accepts("env-secret") == "current"


def test_rotate_without_an_existing_secret_has_no_grace_window():
    out = ws.rotate()
    assert out["previous_valid_until"] is None
    assert ws.accepts(out["secret"]) == "current"


def test_routes_and_the_check_go_through_the_module():
    src = _src("app.py")
    m = re.search(r'@app\.post\("/ui/api/webhook-secret/rotate"\)(.{0,600})', src, re.S)
    assert m, "no rotate route"
    body = m.group(1)
    assert "auth.is_admin()" in body and "webhook_secret.rotate()" in body and "409" in body
    check = src.split("def _check_auth() -> None:", 1)[1].split("\n\n\n", 1)[0]
    assert "webhook_secret.accepts(provided)" in check
    assert 'matched == "previous"' in check, "a previous-secret use is logged by sender"
    assert "hmac.compare_digest" not in check, "the comparison lives in webhook_secret"
    show = src.split('@app.get("/ui/api/webhook-secret")', 1)[1].split("\n\n\n", 1)[0]
    assert "webhook_secret.status()" in show
