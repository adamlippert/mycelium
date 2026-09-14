"""Item 8 of the 1.0 readiness blocker pass.

/ui/api/discover/search did `page = int(request.args.get("page") or "1")`,
which raises ValueError (and a 500) for ?page=x, and passed an unclamped
huge value straight to TMDB. Every other pager in the codebase clamps with
admin_query.clamp_int.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import admin_query
from _routes import src_for_route


def test_the_route_uses_clamp_int_not_a_bare_int_call():
    src = src_for_route("/ui/api/discover/search")
    assert "admin_query.clamp_int(" in src
    assert 'page = int(request.args.get("page")' not in src


def test_clamp_int_handles_garbage_zero_and_oversized_values():
    assert admin_query.clamp_int("x", 1, 1, 500) == 1
    assert admin_query.clamp_int("0", 1, 1, 500) == 1
    assert admin_query.clamp_int("999", 1, 1, 500) == 500
    assert admin_query.clamp_int("7", 1, 1, 500) == 7
    assert admin_query.clamp_int(None, 1, 1, 500) == 1
