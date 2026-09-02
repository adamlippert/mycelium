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


def test_config_carries_the_debridio_key_but_not_the_torbox_key(configured):
    """Service wrap: Debridio is queried as a plain scraper. The addon does
    not validate providerKey (verified live: identical 538 streams and 197
    cached flags with the key present, omitted, blank or nonsense) and
    Mycelium resolves every hash through its own TorBox client, so the key
    is not sent. provider stays, or the addon 500s."""
    token = debridio.build_config_token()
    cfg = _decode(token)
    assert cfg["api_key"] == "dk" * 16
    assert cfg["provider"] == "torbox"
    assert "providerKey" not in cfg
    assert "tb-uuid-value" not in base64.b64decode(token).decode()


def test_opt_in_restores_the_torbox_key(configured, monkeypatch):
    """Escape hatch for a future addon version that starts requiring it."""
    monkeypatch.setitem(configured, "DEBRIDIO_SEND_TORBOX_KEY", "true")
    cfg = _decode(debridio.build_config_token())
    assert cfg["providerKey"] == "tb-uuid-value"


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


def test_is_configured_needs_only_the_debridio_key(monkeypatch):
    """A TorBox key is no longer part of talking to Debridio."""
    monkeypatch.setattr(debridio._settings, "get",
                        lambda k, d=None: "x" if k == "DEBRIDIO_API_KEY" else d)
    monkeypatch.setattr(debridio.config, "TORBOX_API_KEY", "")
    assert debridio.is_configured() is True


def test_is_configured_requires_the_torbox_key_in_opt_in_mode(monkeypatch):
    values = {"DEBRIDIO_API_KEY": "x", "DEBRIDIO_SEND_TORBOX_KEY": "true"}
    monkeypatch.setattr(debridio._settings, "get",
                        lambda k, d=None: values.get(k, d))
    monkeypatch.setattr(debridio.config, "TORBOX_API_KEY", "")
    assert debridio.is_configured() is False


def test_redact_keeps_the_diagnostic_url_tail():
    """A greedy base64 pattern used to swallow "/stream/series/tt2861424"
    after the token ("/" and alphanumerics are all valid base64), logging
    ".../<config>:2:1.json" - an error line with the media type and id
    destroyed, which cost real diagnosis time during a live incident."""
    url = ("https://addon.debridio.com/eyJhcGlfa2V5IjoiZmFrZWZha2VmYWtl"
           "/stream/series/tt2861424:2:1.json")
    out = debridio.redact(url)
    assert out == "https://addon.debridio.com/<config>/stream/series/tt2861424:2:1.json"


def test_redact_still_collapses_a_bare_trailing_token():
    """The bounded pattern only fires before known segments; a token in any
    other position must still be scrubbed by the greedy backstop."""
    out = debridio.redact("giving up on https://addon.debridio.com/eyJhcGlfa2V5IjoiZmFrZWZha2VmYWtl")
    assert "eyJhcGlfa2V5" not in out
    assert "/<config>" in out


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


def test_http_error_propagates_when_raise_on_error(configured, monkeypatch):
    # scrapers.py sets this so its outage guard can see this scraper fail
    # instead of the failure disappearing into an empty list.
    monkeypatch.setattr(debridio.requests, "get", lambda *a, **k: _Resp({}, status=500))
    with pytest.raises(Exception):
        debridio.fetch("movie", "tt1", raise_on_error=True)


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


def test_is_up_false_when_disabled(monkeypatch):
    import health_cache
    monkeypatch.setattr(health_cache._settings, "get",
                        lambda k, d=None: False if k == "DEBRIDIO_ENABLED" else d)
    health_cache._cache.clear()
    assert health_cache.is_up("debridio") is False


def test_is_up_false_when_unconfigured(monkeypatch):
    import health_cache
    monkeypatch.setattr(health_cache._settings, "get",
                        lambda k, d=None: True if k == "DEBRIDIO_ENABLED" else d)
    monkeypatch.setattr(debridio, "is_configured", lambda: False)
    health_cache._cache.clear()
    assert health_cache.is_up("debridio") is False


class _StatusResp:
    def __init__(self, status):
        self.status_code = status


@pytest.mark.parametrize("status", [401, 403, 404])
def test_auth_failure_marks_debridio_down_in_health_cache(monkeypatch, status):
    # A lapsed subscription answers 401/403 and a garbled config token 404.
    # All are < 500, so the generic predicate called them healthy and every
    # search kept paying a round trip to a dead addon.
    import health_cache
    monkeypatch.setattr(health_cache._settings, "get",
                        lambda k, d=None: True if k == "DEBRIDIO_ENABLED" else d)
    monkeypatch.setattr(debridio, "is_configured", lambda: True)
    monkeypatch.setattr(debridio, "build_config_token", lambda: "TOKEN")
    monkeypatch.setattr(health_cache.requests, "get",
                        lambda *a, **k: _StatusResp(status))
    health_cache._cache.clear()
    assert health_cache.is_up("debridio") is False


@pytest.mark.parametrize("status", [401, 403, 404])
def test_auth_failure_marks_debridio_down_on_the_health_card(monkeypatch, status):
    import health
    monkeypatch.setattr(health.settings, "get",
                        lambda k, d=None: {"DEBRIDIO_ENABLED": True}.get(k, d))
    monkeypatch.setattr(debridio, "is_configured", lambda: True)
    monkeypatch.setattr(debridio, "build_config_token", lambda: "TOKEN")
    monkeypatch.setattr(health.requests, "get", lambda *a, **k: _StatusResp(status))
    entry = [s for s in health.check_all() if s["name"] == "Debridio"][0]
    assert entry["status"] == "down"


def test_the_other_services_keep_the_plain_500_predicate(monkeypatch):
    # Only Debridio authenticates; a 404 from Torrentio's manifest is not an
    # auth failure and must not take it out of rotation.
    import health
    import health_cache
    monkeypatch.setattr(health.settings, "get", lambda k, d=None: d)
    monkeypatch.setattr(health.requests, "get", lambda *a, **k: _StatusResp(404))
    entry = [s for s in health.check_all() if s["name"] == "Torrentio"][0]
    assert entry["status"] == "ok"

    monkeypatch.setattr(health_cache.requests, "get", lambda *a, **k: _StatusResp(404))
    health_cache._cache.clear()
    assert health_cache.is_up("torrentio") is True


def test_health_error_is_redacted(monkeypatch):
    # requests embeds the URL in its exception messages, and health.py:23
    # returns str(exc)[:80] straight into an HTTP response.
    import health
    monkeypatch.setattr(health.settings, "get",
                        lambda k, d=None: {"DEBRIDIO_ENABLED": True}.get(k, d))
    monkeypatch.setattr(debridio, "is_configured", lambda: True)
    monkeypatch.setattr(debridio, "build_config_token", lambda: "eyJhcGlfa2V5SECRET")

    def _boom(*a, **k):
        raise RuntimeError("failed for url: https://addon.debridio.com/eyJhcGlfa2V5SECRET/manifest.json")

    monkeypatch.setattr(health.requests, "get", _boom)
    entry = [s for s in health.check_all() if s["name"] == "Debridio"][0]
    assert "SECRET" not in str(entry)


def test_health_error_truncation_does_not_leak_a_token_fragment(configured, monkeypatch):
    # The old ordering truncated str(exc) to 80 chars BEFORE redacting. A
    # long, realistic error message with the full config token embedded puts
    # the 80-char cut partway through the token: past the literal
    # "eyJhcGlfa2V5" prefix, but short of redact()'s 16-trailing-char regex
    # threshold, so the leftover fragment slipped through unredacted.
    # Redact must run before the slice, not after.
    import health
    # Compute the real token first, while only the `configured` fixture's
    # patch is in effect. build_config_token/is_configured are then pinned
    # directly (rather than re-patching settings.get) so this doesn't depend
    # on health.settings and debridio._settings being the same module object
    # -- a `settings` module identity that another test file's
    # sys.modules.pop("settings") can split apart depending on collection
    # order.
    token = debridio.build_config_token()
    assert len(token) > 80  # sanity: the token alone exceeds the truncation window
    monkeypatch.setattr(debridio, "build_config_token", lambda: token)
    monkeypatch.setattr(debridio, "is_configured", lambda: True)
    monkeypatch.setattr(health.settings, "get",
                        lambda k, d=None: {"DEBRIDIO_ENABLED": True}.get(k, d))

    def _boom(*a, **k):
        raise RuntimeError(
            "connection timed out while contacting https://addon.debridio.com/"
            f"{token}/manifest.json after 3 retries, giving up on this host entirely")

    monkeypatch.setattr(health.requests, "get", _boom)
    entry = [s for s in health.check_all() if s["name"] == "Debridio"][0]
    assert token not in entry["error"]
    assert "dk" * 16 not in entry["error"]
    assert "tb-uuid-value" not in entry["error"]
    assert "eyJhcGlfa2V5" not in entry["error"]


def test_a_real_request_at_debug_level_leaks_nothing(configured, monkeypatch, caplog):
    # The mocked test below never lets urllib3 run, so it cannot see the third
    # leak: urllib3.connectionpool logs the request line - method, host and the
    # full path, which for Debridio is the base64 config token holding BOTH the
    # Debridio key and the TorBox key - at DEBUG, underneath every redact()
    # call site. LOG_LEVEL=DEBUG then puts it in log_buffer and the admin Logs
    # tab. This one makes a genuine request (to a port nothing listens on, so
    # it fails fast) so urllib3 really fires.
    import logging

    import config

    monkeypatch.setitem(
        configured, "DEBRIDIO_BASE_URL", "http://127.0.0.1:1")
    token = debridio.build_config_token()
    assert token.startswith("ey")

    monkeypatch.setattr(config, "LOG_LEVEL", "DEBUG")
    urllib3_log = logging.getLogger("urllib3")
    monkeypatch.setattr(urllib3_log, "level", urllib3_log.level)
    config.configure_logging()
    assert urllib3_log.getEffectiveLevel() >= logging.WARNING

    with caplog.at_level("DEBUG"):
        assert debridio.fetch("movie", "tt1") == []

    assert [r.name for r in caplog.records if r.name.startswith("urllib3")] == []
    blob = " ".join(f"{r.name} {r.getMessage()}" for r in caplog.records)
    assert token not in blob
    assert "eyJhcGlfa2V5" not in blob
    assert "dk" * 16 not in blob
    assert "tb-uuid-value" not in blob


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


# ── DEBRIDIO_CONFIG_TOKEN must not bypass the key-privacy default ────────────

def _override_settings(monkeypatch, token, send_key=False):
    values = {"DEBRIDIO_CONFIG_TOKEN": token, "DEBRIDIO_API_KEY": "dk" * 16,
              "TORBOX_API_KEY": "tb-uuid-value"}
    if send_key:
        values["DEBRIDIO_SEND_TORBOX_KEY"] = "true"
    monkeypatch.setattr(debridio._settings, "get",
                        lambda k, d=None: values.get(k, d))
    return values


def _token_for(cfg):
    return base64.b64encode(json.dumps(cfg).encode()).decode()


def test_override_has_its_torbox_key_stripped(monkeypatch):
    """The override is returned verbatim, so it bypassed send_torbox_key():
    any blob built before that default changed carries a providerKey, which
    made the one escape-hatch setting silently re-enable key sharing."""
    _override_settings(monkeypatch, _token_for({
        "api_key": "theirs", "provider": "torbox", "providerKey": "tb-uuid-value",
        "maxReturnPerQuality": "250"}))

    out = _decode(debridio.build_config_token())

    assert "providerKey" not in out
    assert out["api_key"] == "theirs"
    # Everything else survives: tuning those fields is why the override exists.
    assert out["maxReturnPerQuality"] == "250"
    assert out["provider"] == "torbox"


def test_override_is_untouched_when_the_opt_in_is_set(monkeypatch):
    _override_settings(monkeypatch, _token_for({
        "api_key": "theirs", "providerKey": "tb-uuid-value"}), send_key=True)

    out = _decode(debridio.build_config_token())

    assert out["providerKey"] == "tb-uuid-value"


def test_override_without_a_provider_key_is_passed_through_unchanged(monkeypatch):
    token = _token_for({"api_key": "theirs", "provider": "torbox"})
    _override_settings(monkeypatch, token)

    assert debridio.build_config_token() == token


def test_undecodable_override_is_used_verbatim(monkeypatch):
    """The genuine 'Debridio changed something we do not understand' case:
    honour the hatch rather than guessing, and warn."""
    _override_settings(monkeypatch, "not-base64-json!!")

    assert debridio.build_config_token() == "not-base64-json!!"


def test_undecodable_override_warns_that_privacy_cannot_be_enforced(monkeypatch, caplog):
    _override_settings(monkeypatch, "not-base64-json!!")

    with caplog.at_level("WARNING"):
        debridio.build_config_token()

    assert any("verbatim" in r.message or "verbatim" in str(r.msg)
               for r in caplog.records), "no warning about the unparsed override"
