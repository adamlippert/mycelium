# Comet and MediaFusion Scrapers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Comet and MediaFusion as candidate sources through one shared Torznab adapter, with their own settings, health probes and testers.

**Architecture:** A new `torznab_scraper.py` fetches and parses a Torznab RSS feed into `Stream` objects. `scrapers._SCRAPERS` gains two entries (comet, mediafusion) between zilean and torrentio, each a thin adapter reading its URL and key from settings. `health_cache._probe` probes `t=caps`. Settings, config and testers follow the Debridio pattern.

**Tech Stack:** Python 3.12, `requests`, `xml.etree.ElementTree`, pytest. No frontend changes: the Scrapers page and Settings page are schema and registry driven.

**Spec:** `docs/superpowers/specs/2026-09-08-torznab-scrapers-design.md`

## Global Constraints

- NEVER write an em-dash (`--` as punctuation in prose or comments, or U+2014) anywhere. Use a comma, a colon, or a new sentence.
- Tests never import `app.py`; route or wiring checks read source text through a `_src()` helper.
- No test touches the network: fake `requests.get` on the module under test (`torznab_scraper.requests.get`), `service_tests._http`, or `health_cache.requests.get`.
- Every DB-touching test file carries its own `_isolated_db` fixture; these tasks need none (no database).
- Runner: `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/ -q -p no:cacheprovider` (1039 passing at start). Mutation-check every new test: break the implementation, the test must fail, restore.
- Registry order after this plan: `debridio, zilean, comet, mediafusion, torrentio`.
- Scraper names are exactly `comet` and `mediafusion` (lower case) everywhere: `Stream.source`, registry, probe, metrics.
- Torznab paths: Comet `/torznab/api`, MediaFusion `/torznab`. `limit=100` on every search. `apikey` only when a key is set.
- Settings keys: `COMET_ENABLED`, `COMET_URL`, `MEDIAFUSION_ENABLED`, `MEDIAFUSION_URL`, `MEDIAFUSION_API_KEY`; MediaFusion URL default `https://mediafusion.elfhosted.com`; Comet URL default empty.
- Commit trailer on every commit: `Claude-Session: https://claude.ai/code/session_017Cc8iouqJoYhUcnJhhgapA`. No Co-Authored-By.

---

## File structure

| File | Responsibility |
|---|---|
| `torznab_scraper.py` (new) | Build the Torznab query, fetch, parse the RSS, map items to `Stream` |
| `scrapers.py` | Two registry entries and their fetch adapters |
| `health_cache.py` | `t=caps` probe for both names |
| `config.py` | Five env defaults |
| `settings.py` | Key buckets, `HOT_RELOAD`, five fields in the scrapers section |
| `service_tests.py` | `test_comet`, `test_mediafusion`, shared `_test_torznab` |
| `tests/test_torznab_scraper.py` (new) | Adapter tests with a fixture feed |
| `tests/test_scrapers.py` | Registry order and merge with five sources |
| `tests/test_scraper_health_page.py` | Disabled rows and down state for the new names |
| `tests/test_settings_schema.py` | Keys typed, placed, hot reload |
| `tests/test_service_tests.py` | Tester behaviour |
| `docs/INTEGRATIONS.md`, `README.md`, `CHANGELOG.md` | Docs |

---

### Task 1: The Torznab adapter

**Files:**
- Create: `torznab_scraper.py`
- Test: `tests/test_torznab_scraper.py`

**Interfaces:**
- Consumes: `streams.Stream`, `streams.parse_quality`, `streams.parse_seeders`, `streams.parse_size_gb`, `streams.detect_languages`, `torrentio._looks_like_season_pack(title, season)`.
- Produces: `torznab_scraper.fetch(name, base_url, path, media_type, imdb_id, season=None, episode=None, *, api_key="", timeout=30, raise_on_error=False) -> list[Stream]`, `torznab_scraper.build_url(base_url, path, media_type, imdb_id, season, episode, api_key) -> tuple[str, dict]` (url, params), `torznab_scraper.parse_feed(name, text, season) -> tuple[list[Stream], int]` (streams, skipped count).

- [ ] **Step 1: Write the failing tests**

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/test_torznab_scraper.py -q -p no:cacheprovider`
Expected: FAIL with `ModuleNotFoundError: No module named 'torznab_scraper'`

- [ ] **Step 3: Write the adapter**

```python
"""Torznab adapter shared by the Comet and MediaFusion scrapers.

Both add-ons expose a Torznab feed: Comet at /torznab/api
(comet/api/endpoints/torznab.py) and MediaFusion at /torznab
(backend/src/routes/torznab.rs). Items carry the info hash, size and
seeders as torznab:attr entries and the magnet as the link. Neither says
whether a debrid service has the torrent cached; Mycelium checks TorBox
itself, so every Stream here has cached=False.
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET

import requests

from streams import Stream, detect_languages, parse_quality
from torrentio import _looks_like_season_pack

log = logging.getLogger(__name__)

_HEX40_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_NS = "{http://torznab.com/schemas/2015/feed}"
LIMIT = 100  # MediaFusion clamps to 100; Comet ignores the parameter


def build_url(base_url: str, path: str, media_type: str, imdb_id: str,
              season: int | None, episode: int | None, api_key: str) -> tuple[str, dict]:
    url = f"{(base_url or '').rstrip('/')}{path}"
    params: dict = {"t": "movie", "imdbid": imdb_id, "limit": LIMIT}
    if media_type != "movie":
        params["t"] = "tvsearch"
        if season is not None:
            params["season"] = season
        if episode is not None:
            params["ep"] = episode
    if api_key:
        params["apikey"] = api_key
    return url, params


def _attrs(item) -> dict[str, str]:
    return {a.get("name") or "": a.get("value") or "" for a in item.findall(f"{_NS}attr")}


def _to_stream(name: str, item, season: int | None) -> Stream | None:
    attrs = _attrs(item)
    info_hash = (attrs.get("infohash") or item.findtext("guid") or "").strip().lower()
    if not _HEX40_RE.match(info_hash):
        return None
    title = (item.findtext("title") or "").strip()
    try:
        size_bytes = int(attrs.get("size") or item.findtext("size") or 0)
    except ValueError:
        size_bytes = 0
    try:
        seeders = int(attrs.get("seeders") or 0)
    except ValueError:
        seeders = 0
    return Stream(
        name=title,
        title=title,
        info_hash=info_hash,
        quality=parse_quality(title),
        seeders=seeders,
        size_gb=round(size_bytes / (1024 ** 3), 2),
        is_season_pack=_looks_like_season_pack(title, season),
        languages=detect_languages(title),
        source=name,
        cached=False,
    )


def parse_feed(name: str, text: str, season: int | None) -> tuple[list[Stream], int]:
    """Streams in feed order, deduped on hash, plus the count of items
    skipped for lack of a usable hash. Raises ET.ParseError on bad XML."""
    root = ET.fromstring(text)
    items = root.findall(".//item")
    out: list[Stream] = []
    seen: set[str] = set()
    skipped = 0
    for item in items:
        stream = _to_stream(name, item, season)
        if stream is None:
            skipped += 1
            continue
        if stream.info_hash in seen:
            continue
        seen.add(stream.info_hash)
        out.append(stream)
    if skipped:
        log.warning("%s: %d/%d Torznab item(s) had no usable info hash; the feed shape may have changed",
                    name, skipped, len(items))
    return out, skipped


def fetch(name: str, base_url: str, path: str, media_type: str, imdb_id: str,
          season: int | None = None, episode: int | None = None, *,
          api_key: str = "", timeout: int = 30, raise_on_error: bool = False) -> list[Stream]:
    """Return candidates from one Torznab endpoint. Never raises by default;
    raise_on_error=True re-raises so scrapers.py's outage guard can tell
    "could not search" from "searched, found nothing"."""
    if not base_url:
        return []
    url, params = build_url(base_url, path, media_type, imdb_id, season, episode, api_key)
    log.info("Querying %s for %s (%s)", name, imdb_id, params["t"])
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
        streams, _ = parse_feed(name, resp.text, season)
    except Exception as exc:
        log.warning("%s request failed for %s: %s", name, imdb_id, exc)
        if raise_on_error:
            raise
        return []
    log.info("%s: %d stream(s) for %s", name, len(streams), imdb_id)
    return streams
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/test_torznab_scraper.py -q -p no:cacheprovider`
Expected: 8 passed. If `heat.size_gb` rounds differently, the 47008801577-byte item is 43.78 GiB; keep the assertion at one decimal.

- [ ] **Step 5: Mutation check**

Change `if stream.info_hash in seen:` to `if False:`; the dedupe test must fail. Restore. Change `params["t"] = "tvsearch"` to `"search"`; the URL test must fail. Restore. Run the file again: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add torznab_scraper.py tests/test_torznab_scraper.py
git commit -m "feat(scrapers): Torznab adapter for Comet and MediaFusion feeds

Claude-Session: https://claude.ai/code/session_017Cc8iouqJoYhUcnJhhgapA"
```

---

### Task 2: Registry entries and health probe

**Files:**
- Modify: `scrapers.py` (the `_fetch_*` adapters and `_SCRAPERS`)
- Modify: `health_cache.py:29-62` (`_probe`)
- Test: `tests/test_scrapers.py`, `tests/test_scraper_health_page.py`

**Interfaces:**
- Consumes: `torznab_scraper.fetch(...)` from Task 1.
- Produces: registry names `comet` and `mediafusion`; `scrapers._fetch_comet(media_type, imdb_id, season, episode, timeout=None)` and `scrapers._fetch_mediafusion(...)`; `health_cache._probe("comet")`, `health_cache._probe("mediafusion")`. Settings keys read here: `COMET_URL`, `MEDIAFUSION_URL`, `MEDIAFUSION_API_KEY`, `COMET_ENABLED`, `MEDIAFUSION_ENABLED` (Task 3 declares them; until then `_settings.get` returns the default passed).

- [ ] **Step 1: Write the failing tests**

In `tests/test_scrapers.py`, extend `_wire` and add tests:

```python
def _wire(monkeypatch, deb=(), zil=(), tor=(), com=(), mf=()):
    monkeypatch.setattr(scrapers.debridio, "fetch", lambda *a, **k: list(deb))
    monkeypatch.setattr(scrapers.zilean, "fetch_streams", lambda *a, **k: list(zil))
    monkeypatch.setattr(scrapers.torrentio, "fetch_streams", lambda *a, **k: list(tor))

    def fake_torznab(name, base_url, path, media_type, imdb_id, season=None, episode=None, **kw):
        return list(com) if name == "comet" else list(mf)

    monkeypatch.setattr(scrapers.torznab_scraper, "fetch", fake_torznab)


def test_registry_order_puts_the_torznab_scrapers_before_torrentio():
    assert [n for n, _, _ in scrapers._SCRAPERS] == ["debridio", "zilean", "comet", "mediafusion", "torrentio"]
    keys = {n: k for n, k, _ in scrapers._SCRAPERS}
    assert keys["comet"] == "COMET_ENABLED" and keys["mediafusion"] == "MEDIAFUSION_ENABLED"


def test_torznab_results_merge_and_record_also_seen_in(monkeypatch):
    h = "a" * 40
    _wire(monkeypatch, zil=[_s(h, "zilean")], com=[_s(h, "comet")], mf=[_s(h, "mediafusion")],
          tor=[_s(h, "torrentio")])
    out = scrapers.fetch_candidates("movie", "tt1")
    assert len(out) == 1 and out[0].source == "zilean"
    assert out[0].also_seen_in == ("comet", "mediafusion", "torrentio")


def test_comet_adapter_passes_url_and_settings(monkeypatch):
    seen = {}

    def fake_torznab(name, base_url, path, media_type, imdb_id, season=None, episode=None, **kw):
        seen.update(name=name, base_url=base_url, path=path, kw=kw, season=season, episode=episode)
        return []

    monkeypatch.setattr(scrapers.torznab_scraper, "fetch", fake_torznab)
    values = {"COMET_URL": "http://comet:8000", "MEDIAFUSION_URL": "https://mf.test", "MEDIAFUSION_API_KEY": "pw"}
    monkeypatch.setattr(scrapers._settings, "get", lambda k, d=None: values.get(k, d))
    scrapers._fetch_comet("series", "tt1", 1, 2, timeout=9)
    assert seen["name"] == "comet" and seen["base_url"] == "http://comet:8000" and seen["path"] == "/torznab/api"
    assert seen["season"] == 1 and seen["episode"] == 2
    assert seen["kw"] == {"api_key": "", "timeout": 9, "raise_on_error": True}
    scrapers._fetch_mediafusion("movie", "tt1", None, None)
    assert seen["name"] == "mediafusion" and seen["path"] == "/torznab" and seen["base_url"] == "https://mf.test"
    assert seen["kw"] == {"api_key": "pw", "raise_on_error": True}
```

In `tests/test_scraper_health_page.py`:

```python
def test_torznab_scrapers_are_listed_and_disabled_by_default(monkeypatch):
    _settings_returning({}, monkeypatch)
    _fresh_metrics()
    rows = {r["name"]: r for r in scrapers.health_rows()}
    assert rows["comet"]["state"] == "disabled"
    assert rows["mediafusion"]["state"] == "disabled"
    assert list(rows) == ["debridio", "zilean", "comet", "mediafusion", "torrentio"]


def test_a_torznab_caps_probe_that_is_refused_means_down(monkeypatch):
    import health_cache

    class _Resp:
        status_code = 403

    calls = []

    def fake_get(url, timeout=None, **kw):
        calls.append(url)
        return _Resp()

    monkeypatch.setattr(health_cache.requests, "get", fake_get)
    monkeypatch.setattr(health_cache._settings, "get",
                        lambda k, d=None: {"COMET_URL": "https://comet.test", "MEDIAFUSION_URL": "https://mf.test"}.get(k, d))
    assert health_cache._probe("comet") is False
    assert calls[-1] == "https://comet.test/torznab/api?t=caps"
    _Resp.status_code = 200
    assert health_cache._probe("mediafusion") is True
    assert calls[-1] == "https://mf.test/torznab?t=caps"


def test_a_torznab_probe_without_a_url_is_down(monkeypatch):
    import health_cache
    monkeypatch.setattr(health_cache._settings, "get", lambda k, d=None: {}.get(k, d))
    monkeypatch.setattr(health_cache.requests, "get",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no request expected")))
    assert health_cache._probe("comet") is False
```

Check whether `_fresh_metrics()` exists in that file (it does at line 24); call it the way the neighbouring tests do.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/test_scrapers.py tests/test_scraper_health_page.py -q -p no:cacheprovider`
Expected: the new tests FAIL (`AttributeError: module 'scrapers' has no attribute 'torznab_scraper'`, order assertion).

- [ ] **Step 3: Add the adapters and registry entries**

In `scrapers.py`, add `import torznab_scraper` next to the other scraper imports, then after `_fetch_torrentio`:

```python
_COMET_PATH = "/torznab/api"        # comet/api/endpoints/torznab.py
_MEDIAFUSION_PATH = "/torznab"      # backend/src/routes/torznab.rs


def _fetch_comet(media_type, imdb_id, season, episode, timeout=None):
    kw = {"api_key": "", "raise_on_error": True}
    if timeout is not None:
        kw["timeout"] = timeout
    return torznab_scraper.fetch("comet", str(_settings.get("COMET_URL", "") or ""), _COMET_PATH,
                                 media_type, imdb_id, season, episode, **kw)


def _fetch_mediafusion(media_type, imdb_id, season, episode, timeout=None):
    kw = {"api_key": str(_settings.get("MEDIAFUSION_API_KEY", "") or ""), "raise_on_error": True}
    if timeout is not None:
        kw["timeout"] = timeout
    return torznab_scraper.fetch("mediafusion",
                                 str(_settings.get("MEDIAFUSION_URL", "https://mediafusion.elfhosted.com") or ""),
                                 _MEDIAFUSION_PATH, media_type, imdb_id, season, episode, **kw)
```

And the registry:

```python
_SCRAPERS = [
    ("debridio", "DEBRIDIO_ENABLED", _fetch_debridio),
    ("zilean", "ZILEAN_ENABLED", _fetch_zilean),
    ("comet", "COMET_ENABLED", _fetch_comet),
    ("mediafusion", "MEDIAFUSION_ENABLED", _fetch_mediafusion),
    ("torrentio", None, _fetch_torrentio),
]
```

- [ ] **Step 4: Add the probe**

In `health_cache._probe`, before the `except Exception` line, add two branches:

```python
        if name in ("comet", "mediafusion"):
            key = "COMET_URL" if name == "comet" else "MEDIAFUSION_URL"
            default = "" if name == "comet" else "https://mediafusion.elfhosted.com"
            base = str(_settings.get(key, default) or "").rstrip("/")
            if not base:
                return False
            path = "/torznab/api" if name == "comet" else "/torznab"
            r = requests.get(f"{base}{path}?t=caps", timeout=3)
            # 403 is what Comet's public instance answers on this path: a
            # misconfigured URL must show as down, not silently empty.
            return r.status_code < 400
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/test_scrapers.py tests/test_scraper_health_page.py tests/test_scraper_outage.py -q -p no:cacheprovider`
Expected: all pass. `tests/test_scraper_outage.py` enables every key and fakes only the three original fetchers, so the new entries would reach the network: add `monkeypatch.setattr(scrapers.torznab_scraper, "fetch", lambda *a, **k: [])` to its enabling fixture (line 161 area) so both new scrapers return nothing there.

- [ ] **Step 6: Mutation check**

Swap the comet and mediafusion registry entries; the order test must fail. Restore. Change `return r.status_code < 400` to `< 500`; the 403 probe test must fail. Restore.

- [ ] **Step 7: Run the full suite and commit**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/ -q -p no:cacheprovider`
Expected: all pass. Note that `tests/test_migrate_source.py` builds the scraper-name set from `_SCRAPERS`; a longer list is fine.

```bash
git add scrapers.py health_cache.py tests/test_scrapers.py tests/test_scraper_health_page.py tests/test_scraper_outage.py
git commit -m "feat(scrapers): comet and mediafusion in the registry with caps probes

Claude-Session: https://claude.ai/code/session_017Cc8iouqJoYhUcnJhhgapA"
```

---

### Task 3: Settings, config and testers

**Files:**
- Modify: `config.py:44-47` (after the Debridio block)
- Modify: `settings.py` (`_BOOL_KEYS`, `HOT_RELOAD`, the scrapers section fields after `DEBRIDIO_CONFIG_TOKEN`)
- Modify: `service_tests.py` (two testers, `TESTS`)
- Test: `tests/test_settings_schema.py`, `tests/test_service_tests.py`

**Interfaces:**
- Consumes: nothing from Tasks 1 and 2 at code level (testers call `service_tests._http`, not the adapter).
- Produces: config attributes `COMET_ENABLED`, `COMET_URL`, `MEDIAFUSION_ENABLED`, `MEDIAFUSION_URL`, `MEDIAFUSION_API_KEY`; schema fields with `test="comet"` and `test="mediafusion"`; `service_tests.TESTS["comet"]`, `TESTS["mediafusion"]`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_settings_schema.py`:

```python
def test_the_torznab_scraper_keys_are_typed_placed_and_hot():
    import config
    fields = settings.fields_by_key()
    for key in ("COMET_ENABLED", "MEDIAFUSION_ENABLED"):
        assert key in settings._BOOL_KEYS and fields[key]["kind"] == "bool"
    assert fields["COMET_URL"]["kind"] == "url" and fields["COMET_URL"]["depends_on"] == "COMET_ENABLED"
    assert fields["COMET_URL"]["test"] == "comet" and fields["COMET_URL"]["required"] is True
    assert fields["MEDIAFUSION_URL"]["kind"] == "url" and fields["MEDIAFUSION_URL"]["test"] == "mediafusion"
    assert fields["MEDIAFUSION_API_KEY"]["kind"] == "secret" and fields["MEDIAFUSION_API_KEY"]["depends_on"] == "MEDIAFUSION_ENABLED"
    section = next(s for s in settings.SECTIONS if s["id"] == "scrapers")
    keys = [f["key"] for f in section["fields"]]
    assert keys.index("DEBRIDIO_CONFIG_TOKEN") < keys.index("COMET_ENABLED") < keys.index("MEDIAFUSION_ENABLED")
    for key in ("COMET_ENABLED", "COMET_URL", "MEDIAFUSION_ENABLED", "MEDIAFUSION_URL", "MEDIAFUSION_API_KEY"):
        assert key in settings.HOT_RELOAD
    assert config.COMET_ENABLED is False and config.COMET_URL == ""
    assert config.MEDIAFUSION_ENABLED is False and config.MEDIAFUSION_URL == "https://mediafusion.elfhosted.com"
    assert config.MEDIAFUSION_API_KEY == ""
```

In `tests/test_service_tests.py` (uses the existing `http` fixture and `FakeResp(status, body, ctype)`, whose `.text` is `str(body)`):

```python
_CAPS = ('<?xml version="1.0" encoding="UTF-8"?><caps><server version="6.1.5" '
         'title="MediaFusion | ElfHosted" url="https://mf.test"/></caps>')


def test_mediafusion_reports_the_caps_server(http, monkeypatch):
    routes, calls = http
    routes["/torznab?t=caps"] = FakeResp(200, _CAPS, ctype="text/xml")
    out = service_tests.run("mediafusion", {"MEDIAFUSION_URL": "https://mf.test", "MEDIAFUSION_API_KEY": "pw"})
    assert out["ok"] and out["message"] == "MediaFusion | ElfHosted 6.1.5"
    assert calls[-1][1] == "https://mf.test/torznab?t=caps&apikey=pw"
    assert "pw" not in out["message"]


def test_comet_explains_a_refused_torznab_path(http, monkeypatch):
    routes, calls = http
    routes["/torznab/api?t=caps"] = FakeResp(403, "Forbidden", ctype="text/html")
    out = service_tests.run("comet", {"COMET_URL": "https://comet.elfhosted.com"})
    assert out["ok"] is False
    assert out["message"] == "this instance does not expose Torznab; use your own Comet URL"


def test_comet_blank_url_uses_the_schema_label(http, monkeypatch):
    monkeypatch.setattr(service_tests._settings, "get", lambda k, d=None: d)
    out = service_tests.run("comet", {})
    assert out == {"ok": False, "message": "Comet URL is empty"}
```

`service_tests._need` returns the schema label as written ("Comet URL") since the cleanup pass, hence the expected message. `FakeResp(status, body, ctype)` stores `str(body)` as `.text`, which is why the caps XML is passed as the body.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/test_settings_schema.py tests/test_service_tests.py -q -p no:cacheprovider`
Expected: the new tests FAIL (`KeyError: 'COMET_URL'`, `KeyError: 'comet'` or similar).

- [ ] **Step 3: Config and settings**

In `config.py`, after the Debridio block:

```python
# Torznab feeds. Comet's public instance refuses /torznab/api, so Comet is
# self-hosted only; MediaFusion's public ElfHosted feed works without a key.
COMET_ENABLED = _env("COMET_ENABLED", "false").lower() in ("1", "true", "yes")
COMET_URL = _env("COMET_URL", "")
MEDIAFUSION_ENABLED = _env("MEDIAFUSION_ENABLED", "false").lower() in ("1", "true", "yes")
MEDIAFUSION_URL = _env("MEDIAFUSION_URL", "https://mediafusion.elfhosted.com")
MEDIAFUSION_API_KEY = _env("MEDIAFUSION_API_KEY", "")
```

In `settings.py`: add `"COMET_ENABLED", "MEDIAFUSION_ENABLED"` to `_BOOL_KEYS` (next to `DEBRIDIO_ENABLED`); add all five keys to `HOT_RELOAD` (next to the Debridio entries); in the scrapers section, after the `DEBRIDIO_CONFIG_TOKEN` field:

```python
            _f("COMET_ENABLED", "Use Comet", "Search a Comet instance's Torznab feed. Self-hosted only: the public instance refuses this path."),
            _f("COMET_URL", "Comet URL", "Address of your Comet instance, with its access token path if protected.", "url",
               placeholder="http://comet:8000", depends_on="COMET_ENABLED", test="comet", required=True),
            _f("MEDIAFUSION_ENABLED", "Use MediaFusion", "Search MediaFusion's Torznab feed. The public ElfHosted instance works without a key."),
            _f("MEDIAFUSION_URL", "MediaFusion URL", "Leave the default for the public instance or point at your own.", "url",
               placeholder="https://mediafusion.elfhosted.com", depends_on="MEDIAFUSION_ENABLED", test="mediafusion"),
            _f("MEDIAFUSION_API_KEY", "MediaFusion API key", "Only for a private instance: its API password.", "secret",
               advanced=True, depends_on="MEDIAFUSION_ENABLED", test="mediafusion"),
```

Help lines must stay short sentences without dashes (`test_help_lines_are_short_sentences` guards this).

- [ ] **Step 4: Testers**

In `service_tests.py`, before `TESTS`:

```python
def _test_torznab(v: dict, url_key: str, path: str, api_key: str, label: str,
                  refused: str) -> dict:
    if (m := _need(v, url_key)):
        return {"ok": False, "message": f"{m} is empty"}
    base = _v(v, url_key).rstrip("/")
    url = f"{base}{path}?t=caps"
    if api_key:
        url += f"&apikey={api_key}"
    r = _http("GET", url)
    if r.status_code == 403:
        return {"ok": False, "message": refused}
    if r.status_code >= 400:
        return {"ok": False, "message": f"{label} refused the request ({_status(r)})"}
    import xml.etree.ElementTree as ET
    try:
        server = ET.fromstring(r.text).find("server")
    except ET.ParseError:
        server = None
    if server is None:
        return {"ok": False, "message": f"{label} answered, but not with a Torznab caps document"}
    title = server.get("title") or label
    version = server.get("version") or ""
    return {"ok": True, "message": f"{title} {version}".strip()}


def test_comet(v: dict) -> dict:
    return _test_torznab(v, "COMET_URL", "/torznab/api", "", "Comet",
                         "this instance does not expose Torznab; use your own Comet URL")


def test_mediafusion(v: dict) -> dict:
    return _test_torznab(v, "MEDIAFUSION_URL", "/torznab", _v(v, "MEDIAFUSION_API_KEY"), "MediaFusion",
                         "MediaFusion refused the request (HTTP 403); a private instance needs its API password")
```

Register both in `TESTS`: `"comet": test_comet, "mediafusion": test_mediafusion`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/test_settings_schema.py tests/test_service_tests.py -q -p no:cacheprovider`
Expected: all pass, including `test_every_schema_test_and_picker_name_is_registered` and `test_every_typed_key_is_listed_once_or_deliberately_unlisted`.

- [ ] **Step 6: Mutation check**

Remove `"COMET_ENABLED"` from `_BOOL_KEYS`; the typed test must fail. Restore. Change the 403 branch to return ok True; the Comet tester test must fail. Restore.

- [ ] **Step 7: Full suite and commit**

Run: `PYTHONDONTWRITEBYTECODE=1 .venv-sdd/bin/python -m pytest tests/ -q -p no:cacheprovider`

```bash
git add config.py settings.py service_tests.py tests/test_settings_schema.py tests/test_service_tests.py
git commit -m "feat(settings): Comet and MediaFusion fields with caps testers

Claude-Session: https://claude.ai/code/session_017Cc8iouqJoYhUcnJhhgapA"
```

---

### Task 4: Docs and changelog

**Files:**
- Modify: `docs/INTEGRATIONS.md` (new section after "Auto-requesters and the TorBox add budget")
- Modify: `README.md` (the scraper list; grep `Zilean` in the features section to find it)
- Modify: `CHANGELOG.md` (`## [Unreleased]`)
- Test: `tests/test_spa_shell.py` runs the releases guard; no test change needed unless a release is cut.

**Interfaces:**
- Consumes: the setting keys and behaviour from Tasks 1 to 3.
- Produces: nothing.

- [ ] **Step 1: INTEGRATIONS.md**

Append:

```markdown
## Comet and MediaFusion

Two more candidate sources, both read through their Torznab feed
(`/torznab/api` on Comet, `/torznab` on MediaFusion). They sit between
Zilean and Torrentio in priority: a release found by several scrapers is
kept once, credited to the highest one, with the others listed under
"also seen in".

**MediaFusion** works out of the box: Settings > Scrapers > Use
MediaFusion, with the public ElfHosted instance as the default URL. A
private instance takes its API password in the MediaFusion API key
field.

**Comet** is self-hosted only. The public instance refuses the Torznab
path, so the Test button reports "this instance does not expose
Torznab" for it. Point Comet URL at your own instance
(`http://comet:8000` on the same Docker network); a protected instance
carries its access token in the path (`https://comet.example/s/<token>`).

Neither feed says whether TorBox has a release cached. Mycelium checks
TorBox itself, exactly as it does for Torrentio results, so the cache
badge and the add budget behave the same. The Scrapers page shows each
one with its latency and state; a wrong URL shows as "down".
```

- [ ] **Step 2: README**

Find the sentence or bullet listing scrapers (grep `Zilean` under the features section) and add Comet (self-hosted) and MediaFusion (public instance by default) to it, keeping the sentence shape. No dashes.

- [ ] **Step 3: CHANGELOG**

Under `## [Unreleased]`:

```markdown
### Added

- Comet and MediaFusion as scrapers, read through their Torznab feeds by
  one shared adapter. Each has an enable toggle, a URL and a Test button
  in Settings > Scrapers; MediaFusion defaults to the public ElfHosted
  instance, Comet needs your own instance. They rank between Zilean and
  Torrentio, share the dedupe, outage guard and latency metrics, and show
  on the Scrapers page. Neither reports cache status; TorBox's own check
  decides, as before.
```

- [ ] **Step 4: Check and commit**

Run: `grep -n "—" docs/INTEGRATIONS.md README.md CHANGELOG.md | grep -v "^CHANGELOG.md:[0-9]*:.*\(egress\|cross-site\)" ` and confirm no new em-dash; run the full suite.

```bash
git add docs/INTEGRATIONS.md README.md CHANGELOG.md
git commit -m "docs: Comet and MediaFusion scrapers

Claude-Session: https://claude.ai/code/session_017Cc8iouqJoYhUcnJhhgapA"
```
