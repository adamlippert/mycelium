import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import webhook_parser
from webhook_parser import IgnoreEvent, WebhookError, parse


def test_parse_movie_with_imdb():
    payload = {
        "notification_type": "MEDIA_AUTO_APPROVED",
        "subject": "Dune (2024)",
        "media": {"media_type": "movie", "imdbId": "tt15239678"},
    }
    req = parse(payload)
    assert req.is_movie
    assert req.imdb_id == "tt15239678"
    assert req.title == "Dune (2024)"


def test_parse_series_seasons():
    payload = {
        "notification_type": "MEDIA_APPROVED",
        "subject": "Foundation",
        "media": {"media_type": "tv", "imdbId": "tt0804484"},
        "extra": [{"name": "Requested Seasons", "value": "1, 2"}],
    }
    req = parse(payload)
    assert req.media_type == "series"
    assert req.seasons == [1, 2]


def test_imdb_in_extras():
    payload = {
        "notification_type": "MEDIA_AUTO_APPROVED",
        "media": {"media_type": "movie"},
        "extra": [{"name": "IMDb ID", "value": "tt0111161"}],
    }
    assert parse(payload).imdb_id == "tt0111161"


def test_test_notification_ignored():
    with pytest.raises(IgnoreEvent):
        parse({"notification_type": "TEST_NOTIFICATION"})


def test_missing_imdb():
    with pytest.raises(WebhookError):
        parse({"notification_type": "MEDIA_APPROVED", "media": {"media_type": "movie"}})


def test_series_defaults_to_season_1():
    payload = {
        "notification_type": "MEDIA_APPROVED",
        "media": {"media_type": "tv", "imdbId": "tt0903747"},
    }
    req = parse(payload)
    assert req.seasons == [1]


def test_parse_resolves_raw_imdb_subject_to_display_title(monkeypatch):
    monkeypatch.setattr(webhook_parser.tmdb, "display_title",
                         lambda imdb_id, media_type: "Dune: Part Two (2024)")
    payload = {
        "notification_type": "MEDIA_AUTO_APPROVED",
        "subject": "tt15239678",
        "media": {"media_type": "movie", "imdbId": "tt15239678"},
    }
    req = parse(payload)
    assert req.title == "Dune: Part Two (2024)"


def test_parse_keeps_real_title_without_tmdb_lookup(monkeypatch):
    def _fail(*args, **kwargs):
        raise AssertionError("display_title should not be called when a real title is present")
    monkeypatch.setattr(webhook_parser.tmdb, "display_title", _fail)
    payload = {
        "notification_type": "MEDIA_AUTO_APPROVED",
        "subject": "Dune (2024)",
        "media": {"media_type": "movie", "imdbId": "tt15239678"},
    }
    req = parse(payload)
    assert req.title == "Dune (2024)"


# ── Seerr's default webhook template carries tmdbId but never imdbId, and Seerr's
# own Media row has imdbId=NULL for freshly-requested titles. The tmdbId in the
# payload must therefore resolve on its own, without a working Seerr round-trip.

def _seerr_default_payload(media_type="movie", **media):
    return {
        "notification_type": "MEDIA_AUTO_APPROVED",
        "subject": "Sinners (2025)",
        "media": {"media_type": media_type, "tmdbId": "1233413",
                   "status": "PENDING", "status4k": "UNKNOWN", **media},
        "request": {"request_id": "412"},
        "extra": [],
    }


@pytest.mark.parametrize("seerr_error", [
    RuntimeError("SEERR_URL is not configured"),
    Exception("404 Client Error: Not Found"),
    Exception("401 Client Error: Unauthorized"),
    Exception("ConnectionError: [Errno 111] Connection refused"),
])
def test_payload_tmdb_id_resolves_when_seerr_lookup_fails(monkeypatch, seerr_error):
    def _boom(*args, **kwargs):
        raise seerr_error
    monkeypatch.setattr(webhook_parser.seerr, "get_request", _boom)
    monkeypatch.setattr(webhook_parser.tmdb, "tmdb_to_imdb",
                         lambda tmdb_id, media_type="movie": "tt31193180")
    monkeypatch.setattr(webhook_parser.tmdb, "display_title", lambda i, m: None)

    req = parse(_seerr_default_payload())
    assert req.imdb_id == "tt31193180"
    assert req.tmdb_id == 1233413


def test_payload_tmdb_id_resolves_when_payload_has_no_request_id(monkeypatch):
    def _fail(*args, **kwargs):
        raise AssertionError("Seerr must not be called when there is no request id")
    monkeypatch.setattr(webhook_parser.seerr, "get_request", _fail)
    monkeypatch.setattr(webhook_parser.tmdb, "tmdb_to_imdb",
                         lambda tmdb_id, media_type="movie": "tt31193180")
    monkeypatch.setattr(webhook_parser.tmdb, "display_title", lambda i, m: None)

    payload = _seerr_default_payload()
    del payload["request"]
    assert parse(payload).imdb_id == "tt31193180"


def test_series_payload_tmdb_id_resolves_with_tv_media_type(monkeypatch):
    seen = {}

    def _capture(tmdb_id, media_type="movie"):
        seen["media_type"] = media_type
        return "tt31193180"

    monkeypatch.setattr(webhook_parser.seerr, "get_request",
                         lambda *a, **k: (_ for _ in ()).throw(Exception("boom")))
    monkeypatch.setattr(webhook_parser.tmdb, "tmdb_to_imdb", _capture)
    monkeypatch.setattr(webhook_parser.tmdb, "display_title", lambda i, m: None)

    payload = _seerr_default_payload(media_type="tv")
    payload["extra"] = [{"name": "Requested Seasons", "value": "2"}]
    req = parse(payload)
    assert req.imdb_id == "tt31193180"
    assert req.seasons == [2]
    # TMDB's external_ids endpoint is /tv/... for series, not /movie/...
    assert seen["media_type"] == "tv"


def test_error_message_names_the_tmdb_id_it_could_not_resolve(monkeypatch):
    monkeypatch.setattr(webhook_parser.seerr, "get_request",
                         lambda *a, **k: (_ for _ in ()).throw(Exception("boom")))
    monkeypatch.setattr(webhook_parser.tmdb, "tmdb_to_imdb",
                         lambda tmdb_id, media_type="movie": None)

    with pytest.raises(WebhookError) as exc:
        parse(_seerr_default_payload())
    assert "1233413" in str(exc.value)
