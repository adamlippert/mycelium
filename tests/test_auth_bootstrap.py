"""AUTH_ENABLED=true with no users, no password hash and no OIDC is a bricked
install: /setup is gated behind a login that cannot succeed, and the
bootstrap carve-out inside /ui/api/users/create never runs because the
request gate rejects it first. The setup surface must stay reachable while
no credential exists, and close again the moment one does.
"""
import os
import re
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import auth
import db

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
    yield
    _drop_cached_conn()


def test_no_credentials_when_nothing_is_configured(monkeypatch):
    monkeypatch.setattr(auth.settings, "get", lambda k, d=None: d)

    assert auth.no_credentials_exist() is True


def test_a_password_hash_counts_as_a_credential(monkeypatch):
    monkeypatch.setattr(auth.settings, "get",
                        lambda k, d=None: "scrypt$x$y" if k == "AUTH_PASSWORD_HASH" else d)

    assert auth.no_credentials_exist() is False


def test_a_user_row_counts_as_a_credential(monkeypatch):
    monkeypatch.setattr(auth.settings, "get", lambda k, d=None: d)
    db.create_user("admin", "scrypt$x$y", role="admin")

    assert auth.no_credentials_exist() is False


def test_the_gate_lets_the_setup_surface_through_while_bricked():
    src = open(os.path.join(_ROOT, "auth.py"), encoding="utf-8").read()
    m = re.search(r"def _enforce\(\):(.*?)\n\ndef |def _enforce\(\):(.*)$", src, re.S)
    assert m, "_enforce not found"
    body = m.group(1) or m.group(2)
    assert "no_credentials_exist()" in body, "the gate never consults the bootstrap state"
    assert "/setup" in body, "the setup surface is not carved out"
