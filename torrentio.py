import logging
import re

import requests

import release_tags
from config import (
    TORRENTIO_BASE_URL,
    TORRENTIO_OPTS,
)
from streams import (
    Stream,
    detect_languages,
    rank_streams,
    parse_seeders,
    parse_size_gb,
)

log = logging.getLogger(__name__)

# Historical name. Six call sites and several tests import TorrentioStream
# from here; keep it working.
TorrentioStream = Stream

# Categories this scraper can populate. Torrentio parses every category from
# the release name, including language via detect_languages.
CAPABILITIES = frozenset(("resolution", "source", "encode", "visual_tag", "audio_tag", "audio_channels", "language"))

_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}

# Language / audio markers in release titles
def _classify_quality(stream: dict) -> str:
    blob = f"{stream.get('name', '')} {stream.get('title', '')}"
    return release_tags.detect_resolution(blob)


_SEASON_NUMBER_RES = (
    re.compile(r"\bseason[ ._-]?(\d{1,2})(?!\d)", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z0-9])s(\d{1,2})(?!\d)(?![ ._-]?e\d)", re.IGNORECASE),
)


def _seasons_named(title: str) -> set[int]:
    """Season numbers a release name states explicitly (S01, Season 1,
    S01-S03 gives both ends). Empty when the name does not say."""
    out: set[int] = set()
    for rx in _SEASON_NUMBER_RES:
        for m in rx.finditer(title or ""):
            out.add(int(m.group(1)))
    return out


def names_other_season(title: str, season: int | None) -> bool:
    """True when the name states one or more seasons and this one is not
    among them: a season 1 pack offered for a season 4 search. Scrapers
    match on the series, so this happens on every season search."""
    if season is None:
        return False
    named = _seasons_named(title)
    return bool(named) and int(season) not in named


def _looks_like_season_pack(title: str, season: int | None) -> bool:
    if season is None:
        return False
    if names_other_season(title, season):
        return False
    blob = (title or "").lower()
    if "complete" in blob:
        return True
    if "season" in blob:
        return True
    if re.search(rf"s0*{season}(?!\d)(?!e\d)", blob, re.IGNORECASE):
        return True
    return False


def _to_stream(raw: dict, season: int | None) -> TorrentioStream | None:
    info_hash = raw.get("infoHash")
    if not info_hash:
        return None
    title = raw.get("title", "") or ""
    # bingeGroup (e.g. "torrentio|1080p|WEB-DL|hevc") is more reliable than
    # free-text title for quality/source/codec classification.
    binge_group = (raw.get("behaviorHints") or {}).get("bingeGroup") or ""
    binge_tokens = binge_group.replace("|", " ")
    # Combine all text sources so every regex (quality, WEBDL, REMUX, CAM, HEVC) fires.
    name = f"{raw.get('name', '') or ''} {binge_tokens}".strip()
    augmented = {"name": name, "title": title}
    return TorrentioStream(
        name=name,
        title=title,
        info_hash=info_hash.lower(),
        quality=_classify_quality(augmented),
        seeders=parse_seeders(title),
        size_gb=parse_size_gb(title),
        is_season_pack=_looks_like_season_pack(title, season),
        languages=detect_languages(f"{name} {title}"),
    )


def redact(text) -> str:
    """Strip TORRENTIO_OPTS out of a URL or exception message before it is
    logged. requests/urllib3 embed the fully-resolved request URL in
    HTTPError and ConnectionError text (raise_for_status, connection
    failures), and TORRENTIO_OPTS - a config segment users paste from
    Torrentio's own configure page - can carry a debrid API key. Scrubs the
    live value at call time, not the value the module was imported with, so
    a test or a runtime settings change is covered too."""
    if not text:
        return ""
    out = str(text)
    opts = str(TORRENTIO_OPTS or "").strip()
    if opts:
        out = out.replace(opts, "***")
    return out


def _build_url(media_type: str, imdb_id: str, season: int | None, episode: int | None) -> str:
    prefix = f"{TORRENTIO_BASE_URL.rstrip('/')}"
    if TORRENTIO_OPTS:
        prefix = f"{prefix}/{TORRENTIO_OPTS.strip('/')}"
    if media_type == "movie":
        return f"{prefix}/stream/movie/{imdb_id}.json"
    if season is None or episode is None:
        raise ValueError("season and episode are required for series")
    return f"{prefix}/stream/series/{imdb_id}:{season}:{episode}.json"


def fetch_streams(
    media_type: str,
    imdb_id: str,
    season: int | None = None,
    episode: int | None = None,
    timeout: int = 30,
) -> list[TorrentioStream]:
    url = _build_url(media_type, imdb_id, season, episode)
    # Never log the URL: TORRENTIO_OPTS (appended into it above) is a config
    # segment users paste from Torrentio's own configure page and can carry
    # a debrid API key, and this line lands at INFO in log_buffer, which
    # /ui/api/logs serves to any logged-in user.
    log.info("Querying Torrentio: %s %s", media_type, imdb_id)
    resp = requests.get(url, timeout=timeout, headers=_HTTP_HEADERS)
    resp.raise_for_status()
    payload = resp.json() or {}
    raw_streams = payload.get("streams", []) or []
    parsed = [s for s in (_to_stream(r, season) for r in raw_streams) if s is not None]
    log.info("Torrentio returned %d streams (%d parsed)", len(raw_streams), len(parsed))
    return parsed
