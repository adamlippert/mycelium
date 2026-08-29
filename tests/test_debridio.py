import base64
import json
import os
import sys

os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import debridio


@pytest.fixture
def configured(monkeypatch):
    values = {"DEBRIDIO_API_KEY": "dk" * 16, "TORBOX_API_KEY": "tb-uuid-value",
              "DEBRIDIO_BASE_URL": "https://addon.debridio.com",
              "DEBRIDIO_MAX_RESULTS": 100, "DEBRIDIO_CONFIG_TOKEN": "",
              "DEBRIDIO_ENABLED": True}
    monkeypatch.setattr(debridio._settings, "get",
                        lambda k, d=None: values.get(k, d))
    return values


def _decode(token):
    return json.loads(base64.b64decode(token))


def test_config_contains_both_credentials(configured):
    cfg = _decode(debridio.build_config_token())
    assert cfg["api_key"] == "dk" * 16
    assert cfg["providerKey"] == "tb-uuid-value"
    assert cfg["provider"] == "torbox"


def test_config_is_permissive(configured):
    # Mycelium's filters are soft and Debridio's are hard. Pushing ours down
    # would stop the "only remux available; allowing them" fallback firing.
    cfg = _decode(debridio.build_config_token())
    assert cfg["excludedQualities"] == []
    assert cfg["preferredLang"] == []
    assert cfg["maxSize"] == ""
    assert cfg["disableUncached"] is False
    assert "unknown" in cfg["resolutions"]
    for res in ("8k", "4k", "1440p", "1080p", "720p", "480p", "360p"):
        assert res in cfg["resolutions"]


def test_config_token_override_is_used_verbatim(monkeypatch):
    monkeypatch.setattr(debridio._settings, "get",
                        lambda k, d=None: "PREBUILT" if k == "DEBRIDIO_CONFIG_TOKEN" else d)
    assert debridio.build_config_token() == "PREBUILT"


def test_unconfigured_returns_empty_token(monkeypatch):
    monkeypatch.setattr(debridio._settings, "get", lambda k, d=None: d)
    assert debridio.build_config_token() == ""
    assert debridio.is_configured() is False


def test_is_configured_requires_both_keys(monkeypatch):
    monkeypatch.setattr(debridio._settings, "get",
                        lambda k, d=None: "x" if k == "DEBRIDIO_API_KEY" else d)
    monkeypatch.setattr(debridio.config, "TORBOX_API_KEY", "")
    assert debridio.is_configured() is False


def test_redact_removes_the_config_segment():
    url = "https://addon.debridio.com/eyJhcGlfa2V5IjoiEXAMPLE/stream/movie/tt1.json"
    out = debridio.redact(url)
    assert "eyJhcGlfa2V5" not in out
    assert "addon.debridio.com" in out


def test_redact_removes_credentials_from_a_play_url():
    url = ("https://addon.debridio.com/play/movie/torbox/"
           + "d" * 32 + "/tb-uuid-value/" + "a" * 40 + "/File.mkv")
    out = debridio.redact(url)
    assert "d" * 32 not in out
    assert "tb-uuid-value" not in out


def test_redact_handles_none_and_empty():
    assert debridio.redact("") == ""
    assert debridio.redact(None) == ""


def test_redact_scrubs_the_live_credential_values(configured):
    msg = "Error for url: https://x/" + "dk" * 16 + "/y and key tb-uuid-value"
    out = debridio.redact(msg)
    assert "dk" * 16 not in out
    assert "tb-uuid-value" not in out


import streams as streams_mod

_PAYLOAD = {"streams": [
    {"name": "[TB ⚡] \nDebridio 4k DV|HDR REMUX",
     "title": "Dune.Part.Two.2024.2160p.BluRay.Remux.mkv\n⚡ 📺 4k 💾 85.37 GB\n👤 12",
     "url": "https://addon.debridio.com/play/movie/torbox/k/p/" + "a" * 40 + "/F.mkv",
     "behaviorHints": {"bingeGroup": "debridio-" + "a" * 40,
                       "filename": "Dune.Part.Two.2024.2160p.BluRay.Remux.mkv"}},
    {"name": "Debridio 1080p",
     "title": "Show.S01E01.1080p.WEB-DL.mkv\n💾 2.10 GB",
     "url": "https://addon.debridio.com/play/series/torbox/k/p/" + "b" * 40 + "/G.mkv",
     "behaviorHints": {"filename": "Show.S01E01.1080p.WEB-DL.mkv"}},
]}


class _Resp:
    def __init__(self, payload, status=200):
        self._p, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            # requests puts the full URL in its exception message. Shape this
            # like a real one: a base64 config segment starting "ey".
            raise RuntimeError(
                f"{self.status_code} Server Error for url: https://addon.debridio.com/"
                "eyJhcGlfa2V5IjoiZGtka2RrZGtka2RrZGsi/stream/movie/tt1.json")

    def json(self):
        return self._p


def test_hash_comes_from_binge_group(configured, monkeypatch):
    monkeypatch.setattr(debridio.requests, "get", lambda *a, **k: _Resp(_PAYLOAD))
    out = debridio.fetch("movie", "tt15239678")
    assert out[0].info_hash == "a" * 40


def test_hash_falls_back_to_the_url_path(configured, monkeypatch):
    monkeypatch.setattr(debridio.requests, "get", lambda *a, **k: _Resp(_PAYLOAD))
    out = debridio.fetch("series", "tt0903747", season=1, episode=1)
    assert out[1].info_hash == "b" * 40


def test_source_is_always_debridio(configured, monkeypatch):
    # Stream.source defaults to "torrentio"; forgetting this misattributes
    # every Debridio win in the Source Win Rate metric instead of erroring.
    monkeypatch.setattr(debridio.requests, "get", lambda *a, **k: _Resp(_PAYLOAD))
    assert all(s.source == "debridio" for s in debridio.fetch("movie", "tt1"))


def test_cached_flag_from_lightning_marker(configured, monkeypatch):
    monkeypatch.setattr(debridio.requests, "get", lambda *a, **k: _Resp(_PAYLOAD))
    out = debridio.fetch("movie", "tt1")
    assert out[0].cached is True
    assert out[1].cached is False


def test_quality_and_size_and_seeders_parsed(configured, monkeypatch):
    monkeypatch.setattr(debridio.requests, "get", lambda *a, **k: _Resp(_PAYLOAD))
    out = debridio.fetch("movie", "tt1")
    assert out[0].quality == "2160p"
    assert out[0].size_gb == 85.37
    assert out[0].seeders == 12
    assert out[1].quality == "1080p"


def test_streams_without_a_hash_are_skipped(configured, monkeypatch):
    payload = {"streams": [{"name": "x", "title": "y", "url": "https://x/play/a/b/c/d/e.mkv",
                            "behaviorHints": {}}]}
    monkeypatch.setattr(debridio.requests, "get", lambda *a, **k: _Resp(payload))
    assert debridio.fetch("movie", "tt1") == []


def test_series_id_is_colon_delimited(configured, monkeypatch):
    seen = {}

    def _get(url, **kw):
        seen["url"] = url
        return _Resp({"streams": []})

    monkeypatch.setattr(debridio.requests, "get", _get)
    debridio.fetch("series", "tt0903747", season=2, episode=5)
    assert "/stream/series/tt0903747:2:5.json" in seen["url"]


def test_http_error_returns_empty_and_never_raises(configured, monkeypatch):
    monkeypatch.setattr(debridio.requests, "get", lambda *a, **k: _Resp({}, status=500))
    assert debridio.fetch("movie", "tt1") == []


def test_unconfigured_returns_empty_without_calling_out(monkeypatch):
    monkeypatch.setattr(debridio._settings, "get", lambda k, d=None: d)

    def _boom(*a, **k):
        raise AssertionError("must not make a request when unconfigured")

    monkeypatch.setattr(debridio.requests, "get", _boom)
    assert debridio.fetch("movie", "tt1") == []


def test_results_are_capped(configured, monkeypatch):
    many = {"streams": [
        {"name": "n", "title": f"T.1080p.mkv\n💾 {i}.00 GB",
         "url": "https://x/play/movie/torbox/k/p/" + f"{i:040x}" + "/f.mkv",
         "behaviorHints": {"bingeGroup": "debridio-" + f"{i:040x}"}}
        for i in range(1, 60)]}
    monkeypatch.setattr(debridio.requests, "get", lambda *a, **k: _Resp(many))
    monkeypatch.setattr(debridio, "_max_results", lambda: 10)
    assert len(debridio.fetch("movie", "tt1")) == 10


def test_malformed_stream_item_is_skipped(configured, monkeypatch):
    # A None entry has no .get(); must be counted and skipped, not raised.
    monkeypatch.setattr(debridio.requests, "get", lambda *a, **k: _Resp({"streams": [None]}))
    assert debridio.fetch("movie", "tt1") == []


def test_non_list_streams_value_is_treated_as_empty(configured, monkeypatch):
    monkeypatch.setattr(debridio.requests, "get",
                        lambda *a, **k: _Resp({"streams": "notalist"}))
    assert debridio.fetch("movie", "tt1") == []


def test_one_malformed_item_does_not_discard_the_rest(configured, monkeypatch):
    # A single bad element in a ~700-item real response must not cost every
    # other stream in the payload.
    payload = {"streams": [None, _PAYLOAD["streams"][0]]}
    monkeypatch.setattr(debridio.requests, "get", lambda *a, **k: _Resp(payload))
    out = debridio.fetch("movie", "tt1")
    assert len(out) == 1
    assert out[0].info_hash == "a" * 40


def test_url_never_reaches_the_logs(configured, monkeypatch, caplog):
    class _LeakyResp:
        status_code = 500

        def raise_for_status(self):
            # requests puts the full URL in its exception message; shape this
            # like a real one, embedding BOTH credential values the
            # `configured` fixture sets so the assertions below are not
            # tautological (they must actually depend on redact() working).
            raise RuntimeError(
                "500 Server Error for url: https://addon.debridio.com/"
                "eyJhcGlfa2V5IjoiZGtka2RrZGtka2RrZGsi/stream/movie/tt1.json "
                "(from play url https://addon.debridio.com/play/movie/torbox/"
                + "dk" * 16 + "/tb-uuid-value/" + "a" * 40 + "/File.mkv)")

        def json(self):
            return {}

    monkeypatch.setattr(debridio.requests, "get", lambda *a, **k: _LeakyResp())
    with caplog.at_level("DEBUG"):
        debridio.fetch("movie", "tt1")
    blob = " ".join(r.getMessage() for r in caplog.records)
    assert "dkdk" not in blob
    assert "tb-uuid-value" not in blob
    assert "eyJhcGlfa2V5" not in blob
