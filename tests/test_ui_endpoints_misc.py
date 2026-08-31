"""Misc /ui/api endpoints added alongside the native admin Overview tab.

Follows the no-import-app pattern from tests/test_quota.py: app.py imports a
lot of runtime state at module load (DB init, scheduler, etc.), so these
assertions read the source text instead of importing the Flask app.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _app_source() -> str:
    with open(os.path.join(os.path.dirname(__file__), "..", "app.py"), encoding="utf-8") as f:
        return f.read()


def test_releases_endpoint_is_registered():
    src = _app_source()
    assert '@app.get("/ui/api/releases")' in src
    assert "RELEASES" in src


def test_releases_endpoint_returns_the_releases_list():
    src = _app_source()
    assert "jsonify(releases=RELEASES)" in src
