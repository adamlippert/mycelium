"""Deletions made elsewhere in the stack (Maintainerr via Radarr/Sonarr, a
person in Jellyfin) must reach cleanup.purge_title, or the title's rows,
monitoring and dedup keys outlive its files and a re-request is swallowed.
"""
import os
import re
import sys

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


RADARR_DELETE = {
    "eventType": "MovieDelete", "instanceName": "Radarr", "deletedFiles": False,
    "movie": {"id": 3, "title": "Heat", "year": 1995, "tmdbId": 949, "imdbId": "tt0113277"},
}
SONARR_DELETE = {
    "eventType": "SeriesDelete", "instanceName": "Sonarr", "deletedFiles": False,
    "series": {"id": 5, "title": "Severance", "tvdbId": 371980, "imdbId": "tt11280740"},
}
JELLYFIN_DELETE = {
    "eventType": "ItemDeleted", "itemType": "Movie", "name": "Heat",
    "imdb": "tt0113277", "tmdb": "949",
}


def test_radarr_movie_delete_parses():
    import arr_webhook
    ev = arr_webhook.parse(RADARR_DELETE)
    assert (ev.source, ev.event, ev.media_type) == ("radarr", "MovieDelete", "movie")
    assert (ev.imdb_id, ev.tmdb_id) == ("tt0113277", 949)


def test_sonarr_series_delete_parses():
    import arr_webhook
    ev = arr_webhook.parse(SONARR_DELETE)
    assert (ev.source, ev.media_type) == ("sonarr", "series")
    assert (ev.imdb_id, ev.tvdb_id) == ("tt11280740", 371980)


def test_jellyfin_item_deleted_parses_movies_and_series():
    import arr_webhook
    ev = arr_webhook.parse(JELLYFIN_DELETE)
    assert (ev.source, ev.media_type, ev.imdb_id, ev.tmdb_id) == ("jellyfin", "movie", "tt0113277", 949)
    ev = arr_webhook.parse({**JELLYFIN_DELETE, "itemType": "Series", "tmdb": "95396"})
    assert ev.media_type == "series"


@pytest.mark.parametrize("payload", [
    {"eventType": "Test", "movie": {"imdbId": "tt0113277"}},
    {"eventType": "MovieFileDelete", "movie": {"imdbId": "tt0113277"}, "deleteReason": "manual"},
    {"eventType": "EpisodeFileDelete", "series": {"imdbId": "tt11280740"}},
    {"eventType": "Grab", "movie": {"imdbId": "tt0113277"}},
    {"eventType": "ItemDeleted", "itemType": "Episode", "imdb": "tt11280740"},
    {"eventType": "ItemDeleted", "itemType": "Season", "imdb": "tt11280740"},
    {},
])
def test_everything_else_is_ignored(payload):
    import arr_webhook
    assert arr_webhook.parse(payload) is None


def test_a_delete_without_any_id_is_an_error():
    import arr_webhook
    with pytest.raises(ValueError):
        arr_webhook.parse({"eventType": "MovieDelete", "movie": {"title": "Heat"}})


def test_jellyfin_unrendered_template_placeholders_count_as_missing():
    """The webhook plugin leaves {{Provider_imdb}} literal when the item has
    no such provider id; that must not become an imdb id."""
    import arr_webhook
    ev = arr_webhook.parse({**JELLYFIN_DELETE, "imdb": "{{Provider_imdb}}", "tmdb": "949"})
    assert ev.imdb_id is None and ev.tmdb_id == 949


def test_resolve_prefers_imdb_then_tmdb_then_tvdb(monkeypatch):
    import arr_webhook
    import tmdb
    monkeypatch.setattr(tmdb, "tmdb_to_imdb", lambda tmdb_id, media_type="movie": f"via-tmdb-{tmdb_id}-{media_type}")
    monkeypatch.setattr(tmdb, "imdb_from_tvdb", lambda tvdb_id: f"via-tvdb-{tvdb_id}")
    D = arr_webhook.DeleteEvent
    assert arr_webhook.resolve_imdb(D("tt1", 9, 8, "movie", "radarr", "MovieDelete")) == "tt1"
    assert arr_webhook.resolve_imdb(D(None, 9, 8, "series", "sonarr", "SeriesDelete")) == "via-tmdb-9-tv"
    assert arr_webhook.resolve_imdb(D(None, None, 8, "series", "sonarr", "SeriesDelete")) == "via-tvdb-8"
    assert arr_webhook.resolve_imdb(D(None, None, None, "movie", "radarr", "MovieDelete")) is None


def test_tmdb_imdb_from_tvdb_uses_the_find_endpoint(monkeypatch):
    import tmdb
    seen = {}

    def fake_get(path, params=None, timeout=10):
        seen["path"], seen["params"] = path, params
        if path.startswith("/find/"):
            return {"tv_results": [{"id": 95396}]}
        return {"imdb_id": "tt11280740"}

    monkeypatch.setattr(tmdb, "_get", fake_get)
    assert tmdb.imdb_from_tvdb(371980) == "tt11280740"
    assert seen["path"] == "/tv/95396/external_ids"


# -- the route -----------------------------------------------------------------

def _route_body():
    src = _src("app.py")
    m = re.search(r'@app\.post\("/webhook/arr"\)\s*\n\s*@_csrf\.exempt\s*\ndef arr_webhook_route\(\):\n(.*?)\n@app\.', src, re.S)
    assert m, "route /webhook/arr with @_csrf.exempt directly under @app.post not found"
    return m.group(1)


def test_route_is_a_machine_caller():
    body = _route_body()
    first_statements = "\n".join(body.splitlines()[:10])
    assert "_check_auth()" in first_statements, "the secret check must run before the payload is read"


def test_route_ignores_titles_mycelium_does_not_own():
    """Both loops (arr delete echo after mirror_remove, Jellyfin ItemDeleted
    after a purge) arrive here for a title that is already gone."""
    body = _route_body()
    assert "db.get_virtual_items_by_imdb(" in body
    assert "db.get_request_by_imdb(" in body
    assert '"unknown title"' in body


def test_route_purges_in_a_thread_and_returns_202():
    body = _route_body()
    assert "cleanup.purge_title" in body
    assert "threading.Thread(" in body
    assert "202" in body


def test_route_ignores_a_jellyfin_echo_when_files_still_present():
    """A targeted refresh reports a repair/upgrade's old path as Deleted;
    Jellyfin's ItemDeleted for that title must not purge it while a fresh
    .strm still exists on disk. Arr-sourced events keep purging unconditionally,
    since in this version the arrs hold no files of their own."""
    body = _route_body()
    assert '"files still present"' in body
    guarded = body.split('"files still present"', 1)[0]
    assert 'ev.source == "jellyfin"' in guarded
    assert "arr_webhook.files_still_present(" in guarded


def test_exemption_pin_includes_the_arr_webhook():
    src = _src("tests/test_tier1_residue.py")
    assert '"/webhook/arr"' in src


# -- files_still_present -------------------------------------------------------

def test_files_still_present_true_when_a_strm_path_exists(tmp_path):
    import arr_webhook
    existing = tmp_path / "Heat (1995).strm"
    existing.write_text("http://example.test/stream/token", encoding="utf-8")
    items = [
        {"strm_path": str(tmp_path / "gone.strm")},
        {"strm_path": str(existing)},
    ]
    assert arr_webhook.files_still_present(items) is True


def test_files_still_present_false_when_missing_or_absent(tmp_path):
    import arr_webhook
    items = [
        {"strm_path": str(tmp_path / "gone-1.strm")},
        {"strm_path": None},
        {},
    ]
    assert arr_webhook.files_still_present(items) is False
    assert arr_webhook.files_still_present([]) is False
