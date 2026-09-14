"""Item 7 of the 1.0 readiness blocker pass.

_check_enabled() aborted 403 whenever auth.current_user_record() was None,
which is also what happens in single-user no-auth mode (auth.is_enabled()
false) - the same mode auth.is_admin() treats as full access everywhere
else. That made the entire Web Player unreachable on a no-auth install.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import flask
import pytest
import werkzeug.exceptions

import plugins.webplayer.routes as webplayer_routes


def test_disabled_auth_allows_the_request_even_with_no_user_record(monkeypatch):
    monkeypatch.setattr(webplayer_routes.auth, "is_enabled", lambda: False)
    monkeypatch.setattr(webplayer_routes.auth, "current_user_record", lambda: None)

    app = flask.Flask(__name__)
    with app.test_request_context("/anything"):
        webplayer_routes._check_enabled()  # must not raise/abort


def test_enabled_auth_with_no_record_still_aborts_403(monkeypatch):
    monkeypatch.setattr(webplayer_routes.auth, "is_enabled", lambda: True)
    monkeypatch.setattr(webplayer_routes.auth, "current_user_record", lambda: None)

    app = flask.Flask(__name__)
    with app.test_request_context("/anything"):
        with pytest.raises(werkzeug.exceptions.Forbidden):
            webplayer_routes._check_enabled()
