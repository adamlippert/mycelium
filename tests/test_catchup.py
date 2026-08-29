import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import catchup


def _seerr_request(media_type="movie", **media):
    """A Seerr /api/v1/request item. Note Seerr's Media entity has no title
    column, so a real response never carries one."""
    return {
        "id": 412,
        "media": {"mediaType": media_type, "tmdbId": 1233413,
                   "imdbId": None, "status": 3, **media},
        "seasons": [],
    }


def test_title_resolves_through_tmdb_when_seerr_has_none(monkeypatch):
    monkeypatch.setattr(catchup.tmdb, "tmdb_to_imdb",
                         lambda tmdb_id, media_type="movie": "tt31193180")
    monkeypatch.setattr(catchup.tmdb, "display_title",
                         lambda imdb_id, media_type: "Sinners (2025)")

    req = catchup._build_request(_seerr_request())
    assert req.imdb_id == "tt31193180"
    assert req.title == "Sinners (2025)"


def test_series_title_uses_series_media_type(monkeypatch):
    seen = {}

    def _display(imdb_id, media_type):
        seen["media_type"] = media_type
        return "Dan Da Dan (2024)"

    monkeypatch.setattr(catchup.tmdb, "tmdb_to_imdb",
                         lambda tmdb_id, media_type="movie": "tt31193180")
    monkeypatch.setattr(catchup.tmdb, "display_title", _display)

    item = _seerr_request(media_type="tv")
    item["seasons"] = [{"seasonNumber": 2}]
    req = catchup._build_request(item)
    assert req.title == "Dan Da Dan (2024)"
    assert req.seasons == [2]
    assert seen["media_type"] == "series"


def test_falls_back_to_imdb_id_when_tmdb_has_no_title(monkeypatch):
    monkeypatch.setattr(catchup.tmdb, "tmdb_to_imdb",
                         lambda tmdb_id, media_type="movie": "tt31193180")
    monkeypatch.setattr(catchup.tmdb, "display_title", lambda imdb_id, media_type: None)

    assert catchup._build_request(_seerr_request()).title == "tt31193180"


def test_seerr_supplied_title_wins_without_a_tmdb_call(monkeypatch):
    def _fail(*args, **kwargs):
        raise AssertionError("display_title should not be called when Seerr gave a title")
    monkeypatch.setattr(catchup.tmdb, "display_title", _fail)

    item = _seerr_request(imdbId="tt31193180", title="Sinners (2025)")
    assert catchup._build_request(item).title == "Sinners (2025)"
