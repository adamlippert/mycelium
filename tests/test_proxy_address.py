"""Item 1/2 of the 1.0 readiness blocker pass.

Behind the Go streaming front (spore-stream/main.go) gunicorn only ever
sees loopback as the peer, so request.remote_addr is useless both for the
trusted-proxy header check (auth._ip_in_trusted) and for keying the login
rate limiter. auth.peer_address() and auth.client_address() recover the
real address from the front's X-Forwarded-For chain, guarded by the
front's own X-Stream-Front marker so a caller cannot spoof the chain by
talking to gunicorn directly (gunicorn only listens on loopback, so that
caller would have to already be local - and a local caller is trusted
anyway).
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import flask

import auth
from _helpers import _src


def _ctx(remote_addr, headers=None):
    app = flask.Flask(__name__)
    return app.test_request_context(
        "/anything",
        environ_base={"REMOTE_ADDR": remote_addr},
        headers=headers or {},
    )


# ── peer_address() ──────────────────────────────────────────────────────────

def test_peer_address_behind_the_front_is_the_appended_chain_entry():
    with _ctx("127.0.0.1", {"X-Forwarded-For": "203.0.113.9, 10.0.0.5", "X-Stream-Front": "1"}):
        assert auth.peer_address() == "10.0.0.5"


def test_peer_address_without_the_front_marker_is_the_loopback_socket():
    with _ctx("127.0.0.1", {"X-Forwarded-For": "203.0.113.9, 10.0.0.5"}):
        assert auth.peer_address() == "127.0.0.1"


def test_peer_address_with_no_front_is_the_remote_socket():
    with _ctx("10.0.0.5"):
        assert auth.peer_address() == "10.0.0.5"


# ── _proxy_user(): the trusted-proxy hole ───────────────────────────────────

def test_proxy_user_default_networks_reject_the_spoofed_client_behind_the_front(monkeypatch):
    values = {"TRUSTED_PROXY_AUTH": True}
    monkeypatch.setattr(auth.settings, "get", lambda k, d=None: values.get(k, d))
    headers = {
        "X-Forwarded-For": "203.0.113.9, 10.0.0.5",
        "X-Stream-Front": "1",
        "X-Forwarded-User": "admin",
    }
    with _ctx("127.0.0.1", headers):
        # Default TRUSTED_PROXY_NETWORKS is 127.0.0.1/32; the real client
        # (10.0.0.5) is not in it, so the header must not be trusted.
        assert auth._proxy_user() is None


def test_proxy_user_trusts_the_real_client_when_its_network_is_configured(monkeypatch):
    values = {"TRUSTED_PROXY_AUTH": True, "TRUSTED_PROXY_NETWORKS": "10.0.0.0/8"}
    monkeypatch.setattr(auth.settings, "get", lambda k, d=None: values.get(k, d))
    headers = {
        "X-Forwarded-For": "203.0.113.9, 10.0.0.5",
        "X-Stream-Front": "1",
        "X-Forwarded-User": "admin",
    }
    with _ctx("127.0.0.1", headers):
        assert auth._proxy_user() == "admin"


# ── client_address(): the rate limiter key ──────────────────────────────────

def test_client_address_behind_the_front_with_the_proxy_trusted_is_the_client(monkeypatch):
    values = {"TRUSTED_PROXY_NETWORKS": "10.0.0.0/8"}
    monkeypatch.setattr(auth.settings, "get", lambda k, d=None: values.get(k, d))
    headers = {"X-Forwarded-For": "203.0.113.9, 10.0.0.5", "X-Stream-Front": "1"}
    with _ctx("127.0.0.1", headers):
        assert auth.client_address() == "203.0.113.9"


def test_client_address_behind_the_front_with_default_networks_is_the_peer(monkeypatch):
    monkeypatch.setattr(auth.settings, "get", lambda k, d=None: d)
    headers = {"X-Forwarded-For": "203.0.113.9, 10.0.0.5", "X-Stream-Front": "1"}
    with _ctx("127.0.0.1", headers):
        # 10.0.0.5 is not inside the default 127.0.0.1/32 trust list, so it
        # is treated as the client itself, not as a trusted proxy to see
        # through.
        assert auth.client_address() == "10.0.0.5"


def test_client_address_without_the_front_behind_a_trusted_proxy(monkeypatch):
    values = {"TRUSTED_PROXY_NETWORKS": "10.0.0.0/8"}
    monkeypatch.setattr(auth.settings, "get", lambda k, d=None: values.get(k, d))
    headers = {"X-Forwarded-For": "203.0.113.9"}
    with _ctx("10.0.0.5", headers):
        assert auth.client_address() == "203.0.113.9"


# ── the limiter key_func no longer keys every caller into one bucket ───────

def test_the_limiter_no_longer_uses_get_remote_address():
    src = _src("appcore.py")
    import re
    m = re.search(r"key_func\s*=\s*([\w.]+)", src)
    assert m, "no key_func= assignment found in appcore.py"
    assert m.group(1) == "auth.client_address"
