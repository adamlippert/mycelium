"""Misc /ui/api endpoints added alongside the native admin Overview tab.

Follows the no-import-app pattern from tests/test_quota.py: app.py imports a
lot of runtime state at module load (DB init, scheduler, etc.), so these
assertions read the source text instead of importing the Flask app.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from _routes import src_for_route


def _app_source() -> str:
    return src_for_route("/ui/api/releases")


def test_releases_endpoint_is_registered():
    src = _app_source()
    assert '@bp.get("/ui/api/releases")' in src
    assert "RELEASES" in src


def test_releases_endpoint_returns_the_releases_list():
    src = _app_source()
    assert "jsonify(releases=RELEASES)" in src
