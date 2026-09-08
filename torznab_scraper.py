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

import settings as _settings
import release_tags
from streams import LANGUAGE_CODES, Stream, detect_languages, parse_quality
from torrentio import _looks_like_season_pack

log = logging.getLogger(__name__)

_HEX40_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_APIKEY_QS_RE = re.compile(r"apikey=[^&\s'\"]*", re.IGNORECASE)
# A protected Comet instance carries its access token in the URL PATH
# (https://comet.example/s/<token>/torznab/api), not a query string, so the
# apikey= rule above cannot see it.
_COMET_TOKEN_RE = re.compile(r"/s/[^/\s'\"]+/")
_NS = "{http://torznab.com/schemas/2015/feed}"
# Every category comes from the release title through the shared helpers,
# so both Torznab scrapers can populate what Torrentio can; Comet adds its
# own language and resolution attributes on top (comet/api/endpoints/torznab.py).
CAPABILITIES = frozenset(("resolution", "source", "encode", "visual_tag", "audio_tag", "audio_channels", "language"))

LIMIT = 100  # MediaFusion clamps to 100; Comet ignores the parameter

# The two Torznab paths, owned here so scrapers.py, health_cache.py and
# service_tests.py describe the same endpoint instead of re-typing the
# literal string three times.
COMET_PATH = "/torznab/api"        # comet/api/endpoints/torznab.py
MEDIAFUSION_PATH = "/torznab"      # backend/src/routes/torznab.rs

# M8 / debridio._MIN_SECRET_LEN: a secret shorter than this is too short to
# be a real key (and too likely to be a placeholder like "true") to scrub
# safely - replacing every occurrence of a one- or two-character string would
# mangle unrelated log text instead of protecting anything.
_MIN_SECRET_LEN = 4


def redact(text) -> str:
    """Strip Torznab credentials out of a URL or exception message before it
    is logged. requests/urllib3 embed the fully-resolved request URL in
    HTTPError and ConnectionError text on the two most common failure paths,
    so this must catch three shapes: the configured MediaFusion api key
    (read from settings, not passed in, so every call site gets the same
    protection for free), any apikey=<value> query fragment (a backstop for
    a differently-encoded key), and a Comet protected-instance access token
    living in the URL path rather than a query string."""
    if not text:
        return ""
    out = str(text)
    secret = str(_settings.get("MEDIAFUSION_API_KEY", "") or "")
    if len(secret) >= _MIN_SECRET_LEN:
        out = out.replace(secret, "***")
    out = _APIKEY_QS_RE.sub("apikey=***", out)
    out = _COMET_TOKEN_RE.sub("/s/***/", out)
    return out


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
        quality=_quality(attrs, title),
        seeders=seeders,
        size_gb=round(size_bytes / (1024 ** 3), 2),
        is_season_pack=_looks_like_season_pack(title, season),
        languages=_languages(attrs, title),
        source=name,
        cached=False,
    )


def _quality(attrs: dict[str, str], title: str) -> str:
    """Comet's `resolution` attribute when it names one of our buckets
    (its parser also emits 1440p, which is not one), else the title."""
    tagged = release_tags.detect_resolution(attrs.get("resolution") or "")
    if tagged != release_tags.UNKNOWN:
        return tagged
    return parse_quality(title)


def _languages(attrs: dict[str, str], title: str) -> tuple[str, ...]:
    """Codes from Comet's comma-joined `language` attribute (ISO 639-1, the
    same codes the language rules use; unknown ones dropped) merged with
    what the title says, sorted for a stable order."""
    from_attr = {c.strip().lower() for c in (attrs.get("language") or "").split(",")}
    known = {c for c in from_attr if c in LANGUAGE_CODES}
    return tuple(sorted(known | set(detect_languages(title))))


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
        log.warning("%s request failed for %s: %s", name, imdb_id, redact(exc))
        if raise_on_error:
            raise
        return []
    log.info("%s: %d stream(s) for %s", name, len(streams), imdb_id)
    return streams
