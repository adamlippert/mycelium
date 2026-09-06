"""Jellyfin was asked for a full library scan after every add and purge.
/Library/Media/Updated refreshes only the paths named, which is what makes
Autopulse redundant for a Mycelium library.
"""
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import db

_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _src(name):
    with open(os.path.join(_ROOT, name), encoding="utf-8") as f:
        return f.read()


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
    def __init__(self, status):
        self.status_code = status
        self.text = ""


@pytest.fixture
def jf(monkeypatch):
    import jellyfin
    # Patch jellyfin's own `settings` reference, not a fresh `import settings`:
    # other test modules pop "settings" from sys.modules and re-import it,
    # which leaves already-imported modules (jellyfin included) bound to the
    # old module object. Patching a freshly imported `settings` here would
    # silently miss jellyfin's real one when this file runs after those.
    values = {"JELLYFIN_URL": "http://jellyfin.test", "JELLYFIN_API_KEY": "k", "JELLYFIN_MEDIA_PATH": ""}
    monkeypatch.setattr(jellyfin.settings, "get", lambda k, d=None: values.get(k, d))
    monkeypatch.setattr(jellyfin, "is_scanning", lambda timeout=10: False)
    jellyfin._last_refresh_ts = None
    with jellyfin._pending_lock:
        jellyfin._pending.clear()
    posts = []

    def fake_post(url, headers=None, json=None, timeout=None):
        posts.append((url, json))
        return FakeResp(204)

    monkeypatch.setattr(jellyfin.requests, "post", fake_post)
    return values, posts


def test_pending_paths_go_to_media_updated_not_a_full_scan(jf):
    import jellyfin
    jellyfin.note_change("/media/movies/Heat (1995)/Heat (1995).strm", "Created")
    assert jellyfin.refresh_library() is True
    values, posts = jf
    assert len(posts) == 1
    url, body = posts[0]
    assert url == "http://jellyfin.test/Library/Media/Updated"
    assert body == {"Updates": [{"Path": "/media/movies/Heat (1995)/Heat (1995).strm", "UpdateType": "Created"}]}
    assert jellyfin.pending_count() == 0


def test_the_first_scan_after_boot_is_not_debounced(jf, monkeypatch):
    """CI runners and freshly started containers have a monotonic clock
    under 60 seconds. A 0.0 sentinel read as "a scan ran moments ago" and
    the very first refresh was skipped; that is how this test file failed
    on CI while passing on a long-running laptop."""
    import jellyfin
    # The fixture resets the module state, so the production default is
    # pinned by source; the guard that reads it is pinned by behaviour.
    assert "_last_refresh_ts: float | None = None" in _src("jellyfin.py")
    monkeypatch.setattr(jellyfin.time, "monotonic", lambda: 5.0)
    assert jellyfin._last_refresh_ts is None
    assert jellyfin.refresh_library() is True
    assert jf[1][0][0] == "http://jellyfin.test/Library/Refresh"


def test_no_pending_paths_means_the_old_full_scan(jf):
    import jellyfin
    assert jellyfin.refresh_library() is True
    assert jf[1][0][0] == "http://jellyfin.test/Library/Refresh"


def test_full_true_drains_pending_and_runs_a_full_scan(jf):
    import jellyfin
    jellyfin.note_change("/media/movies/x.strm", "Deleted")
    assert jellyfin.refresh_library(full=True) is True
    assert [u for u, _ in jf[1]] == ["http://jellyfin.test/Library/Refresh"]
    assert jellyfin.pending_count() == 0


def test_targeted_refresh_ignores_the_debounce(jf):
    import jellyfin
    jellyfin._last_refresh_ts = time.monotonic()
    jellyfin.note_change("/media/movies/x.strm", "Created")
    assert jellyfin.refresh_library() is True
    assert jf[1][0][0].endswith("/Library/Media/Updated")


def test_same_path_same_type_is_sent_once(jf):
    import jellyfin
    for _ in range(3):
        jellyfin.note_change(Path("/media/movies/x.strm"), "Created")
    jellyfin.refresh_library()
    assert len(jf[1][0][1]["Updates"]) == 1


def test_paths_are_translated_to_jellyfins_mount(jf, monkeypatch):
    import jellyfin
    import config
    monkeypatch.setattr(config, "MEDIA_PATH", "/media")
    jf[0]["JELLYFIN_MEDIA_PATH"] = "/data/library"
    jellyfin.note_change("/media/series/Show/Season 01/S01E01.strm", "Created")
    jellyfin.refresh_library()
    assert jf[1][0][1]["Updates"][0]["Path"] == "/data/library/series/Show/Season 01/S01E01.strm"


def test_a_failed_targeted_post_falls_back_to_a_full_scan(jf, monkeypatch):
    import jellyfin
    calls = []

    def flaky(url, headers=None, json=None, timeout=None):
        calls.append(url)
        return FakeResp(500 if url.endswith("/Media/Updated") else 204)

    monkeypatch.setattr(jellyfin.requests, "post", flaky)
    # Put the debounce in play: without force=True on the fallback, this
    # would swallow the full-scan fallback and the assertion below would fail.
    jellyfin._last_refresh_ts = time.monotonic()
    jellyfin.note_change("/media/movies/x.strm", "Created")
    assert jellyfin.refresh_library() is True
    assert calls == ["http://jellyfin.test/Library/Media/Updated", "http://jellyfin.test/Library/Refresh"]
    assert jellyfin.pending_count() == 0


def test_large_batches_are_chunked(jf):
    import jellyfin
    for i in range(450):
        jellyfin.note_change(f"/media/movies/m{i}/m{i}.strm", "Created")
    jellyfin.refresh_library()
    sizes = [len(body["Updates"]) for _, body in jf[1]]
    assert sizes == [200, 200, 50]


# -- wiring ------------------------------------------------------------------

def test_strm_writes_are_noted_as_created():
    src = _src("strm_generator.py")
    body = src.split("def _write_strm(", 1)[1].split("\ndef ", 1)[0]
    assert 'jellyfin.note_change(path, "Created")' in body


def test_purge_notes_each_deleted_strm():
    src = _src("cleanup.py")
    body = src.split("def purge_title(", 1)[1]
    assert 'jellyfin.note_change(path, "Deleted")' in body


def test_cleanup_deletions_are_noted():
    src = _src("cleanup.py")
    assert src.count('jellyfin.note_change(') >= 6, "every unlink of a .strm in cleanup notes Deleted"


def test_upgrader_and_generator_deletions_are_noted():
    """Season-pack consolidation, repair's requeue and the duplicate-strm
    cleanup all unlink a .strm directly; each must note the deletion, or
    Jellyfin never learns those paths went away."""
    upgrader_src = _src("upgrader.py")
    pack_body = upgrader_src.split("def run_pack_consolidation(", 1)[1].split("\ndef ", 1)[0]
    assert '"Deleted")' in pack_body

    generator_src = _src("strm_generator.py")
    requeue_body = generator_src.split("def _requeue(", 1)[1].split("\n    def ", 1)[0]
    assert '"Deleted")' in requeue_body
    # The unlink lives in the locked worker, not the lock-acquiring wrapper.
    dup_body = generator_src.split("def _cleanup_duplicate_strms_locked(", 1)[1].split("\ndef ", 1)[0]
    assert '"Deleted")' in dup_body


def test_the_cleanup_run_asks_for_a_full_scan():
    """Cleanup renames and merges folders it cannot itemise."""
    src = _src("cleanup.py")
    body = src.split("def _run_cleanup_locked(", 1)[1].split("\ndef ", 1)[0]
    assert "jellyfin.refresh_library(full=True)" in body


def test_setting_is_registered():
    src = _src("settings.py")
    assert '"JELLYFIN_MEDIA_PATH"' in src.split("HOT_RELOAD = {", 1)[1].split("}", 1)[0]
    assert "\nJELLYFIN_MEDIA_PATH=" in _src(".env.example")
