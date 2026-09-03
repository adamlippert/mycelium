"""TorBox's requestdl opens a returned link for three hours; after that a new
connection cannot be started against it. Caching a resolved URL for 23 hours
guaranteed a window in which every cached entry was already dead, which is
the failure the liveness check and re-resolve path were built to absorb.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import catbox

TORBOX_LINK_WINDOW_SEC = 3 * 3600


def test_url_cache_expires_inside_the_provider_window():
    assert catbox._URL_CACHE_TTL_SEC < TORBOX_LINK_WINDOW_SEC, (
        "a cached URL outlives TorBox's 3h link window and is dead on arrival")


def test_the_ttl_leaves_usable_headroom():
    """Too short and every playback pays a fresh resolve, spending the
    createtorrent budget the cache exists to protect."""
    assert catbox._URL_CACHE_TTL_SEC >= 2 * 3600
