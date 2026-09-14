"""/spore-nfs/tree and /spore-nfs/size/<token> exist for the NFS and SMB
share helpers running beside gunicorn in the same container, and auth.py
carves the whole family out of the login gate. Before 1.0 that meant any
caller on the internet could list every playable token (unauthenticated
capability links, one per library item) and ask the size of each. Both
handlers now refuse anything that did not arrive over loopback, the same
rule the two /internal/ endpoints already applied.
"""
import os
import re
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from _routes import src_for_route

_ROOT = os.path.join(os.path.dirname(__file__), "..")

LOOPBACK_ONLY = ["/spore-nfs/tree", "/spore-nfs/size/<token>"]


def _handler_body(src: str, path: str) -> str:
    m = re.search(r'@bp\.get\(\s*"' + re.escape(path) + r'"\s*\)\n'
                  r"def \w+\([^)]*\):\n(.*?)(?=\n@|\Z)", src, re.S)
    assert m, f"handler for {path} not found"
    return m.group(1)


def test_the_helper_only_routes_refuse_a_non_loopback_caller():
    for path in LOOPBACK_ONLY:
        body = _handler_body(src_for_route(path), path)
        assert "_from_loopback()" in body, f"{path} never checks the peer address"
        assert "abort(404)" in body, f"{path} does not refuse a non-loopback caller with 404"


def test_the_loopback_helper_reads_the_peer_address_and_not_a_header():
    """A forwarded header is caller-controlled, so the check has to sit on
    request.remote_addr, which is the socket peer gunicorn actually saw."""
    src = src_for_route("/spore-nfs/tree")
    m = re.search(r"def _from_loopback\(\).*?return ([^\n]+)", src, re.S)
    assert m, "_from_loopback not found"
    assert "request.remote_addr" in m.group(1)
    assert "X-Forwarded" not in m.group(1)


def test_the_internal_endpoints_share_the_same_helper():
    """The two /internal/ handlers had this check inline; they now use the
    same predicate, so a future change to what counts as loopback cannot
    move only one of the two families."""
    src = src_for_route("/internal/stream-resolve/<token>")
    assert src.count("_from_loopback()") >= 4


def test_the_auth_gate_still_carves_the_family_out():
    """The routes stay outside the login gate on purpose (the helpers have
    no session); the handlers' own check is what makes that safe, so the
    two must not drift apart silently."""
    src = open(os.path.join(_ROOT, "auth.py"), encoding="utf-8").read()
    assert "/spore-nfs/" in src
