"""Two health rows for the settings that quietly burn TorBox bandwidth and
the add budget: Jellyfin's per-library image extraction, and the number of
TorBox adds used this hour.
"""
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _drop_cached_conn():
    conn = getattr(db._tls, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        db._tls.conn = None


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    _drop_cached_conn()
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    _drop_cached_conn()
    db.init()
    yield
    _drop_cached_conn()


class FakeResp:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


LIBRARIES = [
    {"Name": "Movies", "Locations": ["/media/movies"], "CollectionType": "movies",
     "LibraryOptions": {"EnableTrickplayImageExtraction": True, "ExtractTrickplayImagesDuringLibraryScan": False,
                        "EnableChapterImageExtraction": True, "ExtractChapterImagesDuringLibraryScan": False}},
    {"Name": "Series", "Locations": ["/media/series"], "CollectionType": "tvshows",
     "LibraryOptions": {"EnableTrickplayImageExtraction": False, "ExtractTrickplayImagesDuringLibraryScan": False,
                        "EnableChapterImageExtraction": False, "ExtractChapterImagesDuringLibraryScan": False}},
    {"Name": "Home videos", "Locations": ["/data/home"], "CollectionType": "homevideos",
     "LibraryOptions": {"EnableTrickplayImageExtraction": True, "ExtractTrickplayImagesDuringLibraryScan": True,
                        "EnableChapterImageExtraction": True, "ExtractChapterImagesDuringLibraryScan": True}},
]


@pytest.fixture
def env(monkeypatch):
    import config
    import health
    import torbox
    values = {"JELLYFIN_URL": "http://jellyfin.test", "JELLYFIN_API_KEY": "k",
              "JELLYFIN_MEDIA_PATH": "", "TORBOX_API_KEY": "t", "TORBOX_BASE_URL": "http://torbox.test",
              "ZILEAN_ENABLED": False, "DEBRIDIO_ENABLED": False}
    monkeypatch.setattr(health.settings, "get", lambda k, d=None: values.get(k, d))
    monkeypatch.setattr(config, "MEDIA_PATH", "/media")
    state = {"libraries": LIBRARIES, "usage": {"count": 17, "limit": 60}}

    def fake_get(url, headers=None, timeout=None):
        if url.endswith("/Library/VirtualFolders"):
            return FakeResp(200, state["libraries"])
        return FakeResp(200, {})

    monkeypatch.setattr(health.requests, "get", fake_get)
    monkeypatch.setattr(torbox, "createtorrent_usage", lambda window_sec=3600: state["usage"])
    return values, state


def _row(name):
    import health
    return next((r for r in health.check_all() if r["name"] == name), None)


# -- Jellyfin library options ---------------------------------------------------

def test_libraries_on_the_mycelium_path_with_extraction_on_are_a_warning(env):
    row = _row("Jellyfin libraries")
    assert row["status"] == "warn"
    assert "Movies: trickplay, chapter images" in row["note"]
    assert "Home videos" not in row["note"], "libraries outside the Mycelium media path are not ours"


def test_libraries_with_extraction_off_are_ok(env):
    values, state = env
    state["libraries"] = [dict(LIBRARIES[1])]
    row = _row("Jellyfin libraries")
    assert row["status"] == "ok"
    assert row["note"] == "1 library, extraction off"


def test_library_paths_are_matched_through_jellyfin_media_path(env):
    """Jellyfin may mount the media elsewhere; JELLYFIN_MEDIA_PATH says where."""
    values, state = env
    values["JELLYFIN_MEDIA_PATH"] = "/data/library"
    state["libraries"] = [{**LIBRARIES[0], "Locations": ["/data/library/movies"]}]
    row = _row("Jellyfin libraries")
    assert row["status"] == "warn" and "Movies" in row["note"]


def test_no_library_points_at_mycelium(env):
    values, state = env
    state["libraries"] = [LIBRARIES[2]]
    row = _row("Jellyfin libraries")
    assert row["status"] == "warn"
    assert "no library points at /media" in row["note"]


def test_unreadable_library_options_add_no_row(env, monkeypatch):
    """The Jellyfin ping row already says whether Jellyfin is reachable."""
    import health

    def failing_get(url, headers=None, timeout=None):
        if url.endswith("/Library/VirtualFolders"):
            raise ConnectionError("down")
        return FakeResp(200, {})

    monkeypatch.setattr(health.requests, "get", failing_get)
    assert _row("Jellyfin libraries") is None


def test_no_jellyfin_no_row(env):
    values, state = env
    values["JELLYFIN_URL"] = ""
    assert _row("Jellyfin libraries") is None


# -- TorBox add budget ----------------------------------------------------------

def test_add_budget_row_is_ok_below_the_threshold(env):
    row = _row("TorBox adds this hour")
    assert row["status"] == "ok"
    assert row["note"] == "17/60 uncached"


def test_add_budget_row_shows_cached_adds_without_counting_them(env):
    values, state = env
    state["usage"] = {"count": 3, "cached_count": 58, "limit": 60}
    row = _row("TorBox adds this hour")
    assert row["status"] == "ok", "cached adds never trip the warning"
    assert row["note"] == "3/60 uncached, 58 cached (not limited)"


def test_add_budget_row_warns_from_45(env):
    values, state = env
    state["usage"] = {"count": 45, "limit": 60}
    row = _row("TorBox adds this hour")
    assert row["status"] == "warn"
    assert row["note"].startswith("45/60 uncached")
    assert "auto-requesters" in row["note"]


def test_add_budget_row_survives_a_counter_failure(env, monkeypatch):
    import torbox

    def boom(window_sec=3600):
        raise RuntimeError("db")

    monkeypatch.setattr(torbox, "createtorrent_usage", boom)
    assert _row("TorBox adds this hour") is None
