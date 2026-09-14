"""Item 5 of the 1.0 readiness blocker pass.

/ui/api/virtual-items (the list route) returned every catbox token with no
admin gate. Tokens are unauthenticated capability URLs (/stream/ and
/spore-stream/ are on auth's public path list), so any logged-in non-admin
could dump and redistribute the entire library as anonymous stream links.
"""
import os
import re
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from _routes import src_for_route


def test_the_list_route_is_admin_only():
    src = src_for_route("/ui/api/virtual-items")
    m = re.search(r'@bp\.get\("/ui/api/virtual-items"\)\n(.*?)(?=\n@(?:bp|app)\.|\Z)', src, re.S)
    assert m, "route not found"
    assert "auth.is_admin()" in m.group(1)
