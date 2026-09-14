"""docs/COMPATIBILITY.md promises a token-bearing Prometheus scrape reaches
/metrics. With AUTH_ENABLED=true it did not: /metrics was in no public-path
carve-out, so the before_request gate answered 302 to /login and the route's
own token check never ran. Adding it to _PUBLIC_PATHS reaches nothing the
route does not guard itself (routes/integration.py: the METRICS_TOKEN header
or query parameter when one is set, an admin session otherwise).
"""
import os
import re
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import flask
import pytest

import auth
import db

_ROOT = os.path.join(os.path.dirname(__file__), "..")

from _helpers import _drop_cached_conn


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    _drop_cached_conn()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    _drop_cached_conn()
    db.init()
    yield
    _drop_cached_conn()


def test_the_public_path_list_names_metrics():
    src = open(os.path.join(_ROOT, "auth.py"), encoding="utf-8").read()
    m = re.search(r"_PUBLIC_PATHS = \((.*?)\n\)", src, re.S)
    assert m, "_PUBLIC_PATHS not found"
    assert '"/metrics"' in m.group(1)


def _app(monkeypatch):
    """A bare app with the real gate installed and a stand-in /metrics that
    applies the same check the real route does, so the test sees which of
    the two answered."""
    app = flask.Flask(__name__)
    app.secret_key = "test"
    auth.install_before_request(app)

    @app.get("/metrics")
    def metrics():
        token = flask.request.headers.get("X-Metrics-Token")
        if token != "scrape-me":
            flask.abort(401)
        return "mycelium_requests_total 42"

    @app.get("/ui/api/settings")
    def settings_route():
        return "ok"

    auth_bp = flask.Blueprint("auth", __name__)

    @auth_bp.get("/login")
    def login_view():
        return "login"

    app.register_blueprint(auth_bp)

    # AUTH_ENABLED with a credential in place: a real, locked-down install.
    monkeypatch.setattr(auth.settings, "get", lambda k, d=None: (
        True if k == "AUTH_ENABLED" else "scrypt$x$y" if k == "AUTH_PASSWORD_HASH" else d))
    db.create_user("admin", "scrypt$x$y", role="admin")
    return app


def test_a_token_bearing_scrape_reaches_the_route_with_auth_enabled(monkeypatch):
    client = _app(monkeypatch).test_client()

    resp = client.get("/metrics", headers={"X-Metrics-Token": "scrape-me"})

    assert resp.status_code == 200, "the gate answered instead of the route"
    assert b"mycelium_requests_total" in resp.data


def test_a_scrape_without_the_token_is_refused_by_the_route_not_the_gate(monkeypatch):
    """401 from the route, never a 302 to a login form: a scraper cannot
    follow one, and a redirect would read as a reachable endpoint."""
    client = _app(monkeypatch).test_client()

    resp = client.get("/metrics")

    assert resp.status_code == 401
    assert "Location" not in resp.headers


def test_the_carve_out_does_not_open_anything_else(monkeypatch):
    client = _app(monkeypatch).test_client()

    assert client.get("/ui/api/settings").status_code == 401
    # A path that merely starts with the same letters is not carved out:
    # the gate still turns an anonymous browser request into a login
    # redirect, so the carve-out is the exact path and nothing around it.
    resp = client.get("/metrics-internal")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
