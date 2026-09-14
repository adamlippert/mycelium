"""The blueprint split moves routes; it never changes them. The fixture was
generated from app.py before the split and is refreshed only by a commit
that deliberately adds or removes a route."""
import json
import os
import sys

_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(_ROOT, "scripts"))
import route_table  # noqa: E402


def test_registered_routes_equal_the_frozen_table():
    stored = json.load(open(os.path.join(_ROOT, "tests", "fixtures", "route_table.json")))
    assert route_table.parse(route_table.sources()) == stored
