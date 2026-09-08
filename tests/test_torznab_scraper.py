"""Torznab adapter shared by the Comet and MediaFusion scrapers."""
import logging

import pytest

import torznab_scraper as tz

H1 = "001810dae4e445e788fe54376055463e984da27e"
H2 = "0296899930dc2258cf460ea2b9971a44061c029f"

# Trimmed from the MediaFusion public feed captured on 2026-09-08. The
# first item has seeders, the second has none, the third has no hash.
FEED = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:torznab="http://torznab.com/schemas/2015/feed">
  <channel>
    <title>MediaFusion | ElfHosted</title>
    <item>
      <title>Heat.1995.REMASTERED.1080p.BluRay.REMUX.AVC.DTS-HD.MA.5.1-FGT</title>
      <guid isPermaLink="false">{H1}</guid>
      <link>magnet:?xt=urn:btih:{H1}</link>
      <size>47008801577</size>
      <torznab:attr name="category" value="2040"/>
      <torznab:attr name="size" value="47008801577"/>
      <torznab:attr name="infohash" value="{H1}"/>
      <torznab:attr name="magneturl" value="magnet:?xt=urn:btih:{H1}"/>
      <torznab:attr name="seeders" value="11"/>
      <torznab:attr name="imdb" value="0113277"/>
    </item>
    <item>
      <title>Severance.S01.COMPLETE.2160p.WEB-DL.Rus.Eng.HEVC</title>
      <guid isPermaLink="false">{H2}</guid>
      <link>magnet:?xt=urn:btih:{H2}</link>
      <size>35639076343</size>
      <torznab:attr name="category" value="5030"/>
      <torznab:attr name="size" value="35639076343"/>
      <torznab:attr name="infohash" value="{H2}"/>
      <torznab:attr name="magneturl" value="magnet:?xt=urn:btih:{H2}"/>
    </item>
    <item>
      <title>Broken item without a hash</title>
      <guid isPermaLink="false">not-a-hash</guid>
      <size>1</size>
    </item>
  </channel>
</rss>
"""


class _Resp:
    def __init__(self, text="", status=200):
        self.text = text
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_build_url_for_a_movie_and_an_episode():
    url, params = tz.build_url("https://mf.test/", "/torznab", "movie", "tt0113277", None, None, "")
    assert url == "https://mf.test/torznab"
    assert params == {"t": "movie", "imdbid": "tt0113277", "limit": 100}
    url, params = tz.build_url("http://comet:8000", "/torznab/api", "series", "tt11280740", 1, 2, "")
    assert url == "http://comet:8000/torznab/api"
    assert params == {"t": "tvsearch", "imdbid": "tt11280740", "season": 1, "ep": 2, "limit": 100}


def test_apikey_is_sent_only_when_set():
    _, params = tz.build_url("https://mf.test", "/torznab", "movie", "tt1", None, None, "")
    assert "apikey" not in params
    _, params = tz.build_url("https://mf.test", "/torznab", "movie", "tt1", None, None, "pw")
    assert params["apikey"] == "pw"


def test_parse_feed_maps_items_to_streams(caplog):
    with caplog.at_level(logging.WARNING):
        streams, skipped = tz.parse_feed("mediafusion", FEED, season=1)
    assert skipped == 1
    assert "1/3" in caplog.text and "mediafusion" in caplog.text
    assert [s.info_hash for s in streams] == [H1, H2]
    heat, sev = streams
    assert heat.source == "mediafusion" and heat.cached is False
    assert heat.name == heat.title == "Heat.1995.REMASTERED.1080p.BluRay.REMUX.AVC.DTS-HD.MA.5.1-FGT"
    assert heat.quality == "1080p" and heat.seeders == 11
    assert round(heat.size_gb, 1) == 43.8
    assert heat.is_season_pack is False
    assert sev.quality == "2160p" and sev.seeders == 0
    assert sev.is_season_pack is True
    assert "en" in sev.languages and "ru" in sev.languages


def test_parse_feed_dedupes_a_repeated_hash():
    doubled = FEED.replace("</channel>", FEED.split("<channel>", 1)[1].split("</channel>", 1)[0] + "</channel>", 1)
    streams, _ = tz.parse_feed("comet", doubled, season=None)
    assert [s.info_hash for s in streams] == [H1, H2]


def test_fetch_uses_the_built_url_and_parses(monkeypatch):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params, timeout))
        return _Resp(FEED)

    monkeypatch.setattr(tz.requests, "get", fake_get)
    out = tz.fetch("mediafusion", "https://mf.test", "/torznab", "movie", "tt0113277", api_key="k", timeout=7)
    assert [s.info_hash for s in out] == [H1, H2]
    assert calls == [("https://mf.test/torznab", {"t": "movie", "imdbid": "tt0113277", "limit": 100, "apikey": "k"}, 7)]


def test_fetch_returns_empty_on_failure_unless_asked_to_raise(monkeypatch):
    def boom(url, params=None, timeout=None):
        raise RuntimeError("down")

    monkeypatch.setattr(tz.requests, "get", boom)
    assert tz.fetch("comet", "http://c", "/torznab/api", "movie", "tt1") == []
    with pytest.raises(RuntimeError):
        tz.fetch("comet", "http://c", "/torznab/api", "movie", "tt1", raise_on_error=True)


def test_fetch_treats_bad_xml_as_a_failure(monkeypatch):
    monkeypatch.setattr(tz.requests, "get", lambda url, params=None, timeout=None: _Resp("Forbidden", 403))
    assert tz.fetch("comet", "http://c", "/torznab/api", "movie", "tt1") == []
    monkeypatch.setattr(tz.requests, "get", lambda url, params=None, timeout=None: _Resp("<not xml", 200))
    assert tz.fetch("comet", "http://c", "/torznab/api", "movie", "tt1") == []
    # M14: pytest.raises(Exception) passed for literally anything, including
    # a bug in the test's own lambda; pin the real failure shape instead.
    with pytest.raises(tz.ET.ParseError):
        tz.fetch("comet", "http://c", "/torznab/api", "movie", "tt1", raise_on_error=True)


def test_fetch_with_an_empty_base_url_returns_nothing_without_a_request(monkeypatch):
    monkeypatch.setattr(tz.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no request expected")))
    assert tz.fetch("comet", "", "/torznab/api", "movie", "tt1") == []


def test_fetch_redacts_the_api_key_from_a_logged_failure(monkeypatch, caplog):
    # C1: the configured key is read from settings (not merely the apikey=
    # query backstop), so it is scrubbed even where the literal replace
    # would miss a differently-encoded key.
    monkeypatch.setattr(tz._settings, "get",
                        lambda k, d=None: "secretpw" if k == "MEDIAFUSION_API_KEY" else d)

    def boom(url, params=None, timeout=None):
        raise tz.requests.exceptions.HTTPError(
            "403 Client Error for url: https://mf.test/torznab?t=movie&imdbid=tt1&limit=100&apikey=secretpw"
        )

    monkeypatch.setattr(tz.requests, "get", boom)
    with caplog.at_level(logging.WARNING):
        out = tz.fetch("mediafusion", "https://mf.test", "/torznab", "movie", "tt1", api_key="secretpw")
    assert out == []
    assert "secretpw" not in caplog.text
    assert "mediafusion" in caplog.text and "tt1" in caplog.text


def test_fetch_redacts_a_comet_access_token_from_the_url_path(monkeypatch, caplog):
    # I2: a protected Comet instance carries its token in the URL PATH
    # (/s/<token>/), which the apikey= query rule cannot see.
    def boom(url, params=None, timeout=None):
        raise tz.requests.exceptions.HTTPError(
            "403 Client Error for url: https://comet.test/s/tok123abc/torznab/api?t=movie&imdbid=tt1"
        )

    monkeypatch.setattr(tz.requests, "get", boom)
    with caplog.at_level(logging.WARNING):
        out = tz.fetch("comet", "https://comet.test/s/tok123abc", "/torznab/api", "movie", "tt1")
    assert out == []
    assert "tok123abc" not in caplog.text
    assert "comet" in caplog.text and "tt1" in caplog.text


def test_redact_skips_a_secret_shorter_than_the_minimum_length(monkeypatch):
    # M8: a one- or two-character configured key must not wipe every
    # matching substring out of unrelated log text.
    monkeypatch.setattr(tz._settings, "get", lambda k, d=None: "ab" if k == "MEDIAFUSION_API_KEY" else d)
    out = tz.redact("mediafusion request failed for tt1: Invalid URL 'ab://torznab': No scheme supplied.")
    assert "ab://torznab" in out


def test_redact_masks_a_secret_at_the_minimum_length(monkeypatch):
    monkeypatch.setattr(tz._settings, "get", lambda k, d=None: "abcd" if k == "MEDIAFUSION_API_KEY" else d)
    out = tz.redact("request failed: config value was abcd, rejected")
    assert "abcd" not in out


def test_torznab_paths_are_owned_here():
    # M6: the two paths live once and everything else imports them.
    assert tz.COMET_PATH == "/torznab/api"
    assert tz.MEDIAFUSION_PATH == "/torznab"


# -- Comet's own language and resolution attributes ----------------------------

def _item(title, **attrs):
    body = "".join(f'<torznab:attr name="{k}" value="{v}"/>' for k, v in attrs.items())
    return (f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<rss version="2.0" xmlns:torznab="http://torznab.com/schemas/2015/feed"><channel>'
            f'<item><title>{title}</title><guid isPermaLink="false">{H1}</guid>'
            f'<torznab:attr name="infohash" value="{H1}"/>{body}</item></channel></rss>')


def test_comet_attributes_win_over_the_title():
    streams, _ = tz.parse_feed("comet", _item("Some.Release.x264", resolution="2160p", language="en,ru"), season=None)
    assert streams[0].quality == "2160p"
    assert streams[0].languages == ("en", "ru")


def test_attribute_languages_merge_with_the_title_and_drop_unknown_codes():
    streams, _ = tz.parse_feed("comet", _item("Some.Release.Dutch.x264", language="en,la,xx"), season=None)
    assert streams[0].languages == ("en", "nl")


def test_a_resolution_outside_our_buckets_falls_back_to_the_title():
    streams, _ = tz.parse_feed("comet", _item("Some.Release.1080p.x264", resolution="1440p"), season=None)
    assert streams[0].quality == "1080p"


def test_without_attributes_the_title_decides():
    streams, _ = tz.parse_feed("mediafusion", _item("Some.Release.720p.English.x264"), season=None)
    assert streams[0].quality == "720p" and streams[0].languages == ("en",)
