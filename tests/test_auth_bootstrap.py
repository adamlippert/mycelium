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


def test_gate_allows_setup_and_create_user_when_bricked_denies_others(monkeypatch):
    """Behavioral test: gate actually allows setup routes through when bricked,
    and denies them once a credential exists."""
    import flask

    # Build a bare Flask app with auth installed
    app = flask.Flask(__name__)
    app.secret_key = "test"
    auth.install_before_request(app)

    # Register trivial routes for each surface
    @app.get("/setup")
    def setup_route():
        return "ok"

    @app.post("/ui/api/users/create")
    def create_user_route():
        return "ok"

    @app.get("/ui/api/settings")
    def settings_route():
        return "ok"

    @app.get("/admin")
    def admin_route():
        return "ok"

    @app.get("/login")
    def login_view():
        return "login"

    # Monkeypatch settings.get to simulate AUTH_ENABLED=true, no password
    # The fixture _isolated_db ensures a fresh database with zero users
    def mock_settings_get(k, d=None):
        if k == "AUTH_ENABLED":
            return True
        if k == "AUTH_PASSWORD_HASH":
            return ""
        return d

    monkeypatch.setattr(auth.settings, "get", mock_settings_get)

    client = app.test_client()

    # Phase 1: bricked state (zero users, no password, no OIDC)
    # Setup surface should be reachable
    assert client.get("/setup").status_code == 200, "GET /setup should return 200 when bricked"
    assert client.post("/ui/api/users/create").status_code == 200, "POST /ui/api/users/create should return 200 when bricked"

    # Other authenticated routes should be gated
    assert client.get("/ui/api/settings").status_code == 401, "GET /ui/api/settings should return 401 when bricked"
    assert client.get("/admin").status_code == 302, "GET /admin should return 302 redirect when bricked"

    # Phase 2: add a credential (simulate bootstrap by creating a user)
    db.create_user("admin", "scrypt$x$y", role="admin")

    # Now setup surface should be gated (not bricked anymore)
    assert client.get("/setup").status_code == 302, "GET /setup should return 302 redirect after credential added"
    assert client.post("/ui/api/users/create").status_code == 401, "POST /ui/api/users/create should return 401 after credential added"

    # And authenticated routes still gated
    assert client.get("/ui/api/settings").status_code == 401, "GET /ui/api/settings should still return 401"
    assert client.get("/admin").status_code == 302, "GET /admin should still return 302"
