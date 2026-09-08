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
    with pytest.raises(Exception):
        tz.fetch("comet", "http://c", "/torznab/api", "movie", "tt1", raise_on_error=True)


def test_fetch_with_an_empty_base_url_returns_nothing_without_a_request(monkeypatch):
    monkeypatch.setattr(tz.requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no request expected")))
    assert tz.fetch("comet", "", "/torznab/api", "movie", "tt1") == []
