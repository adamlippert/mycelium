import logging

import requests

import settings as _settings
from config import ZILEAN_URL as _ZILEAN_URL_DEFAULT
from torrentio import TorrentioStream, _looks_like_season_pack

log = logging.getLogger(__name__)

# Zilean's DMM payload carries no language information of any kind, so every
# stream it returns has an empty `languages`. That is "did not say", not "has
# no audio" - see streams.detect_languages.
#
# No production code reads this flag today - it has no callers outside tests.
# It is deliberate groundwork for a planned filter model that needs to tell
# "this scraper cannot possibly know" apart from "this stream just didn't say".
# Keep it; it is not unused by oversight.
LANGUAGES_AVAILABLE = False

# Categories this scraper can populate. Zilean does not provide language data,
# only the six categories that come from release name parsing. The distinction:
# resolution, source, encode, visual_tag, audio_tag, audio_channels are
# text-derived (parsed from the release name at rank time); language is
# field-derived (read from Stream.languages, which zilean.py never populates).
# All other scrapers populate language; only Zilean omits it.
CAPABILITIES = frozenset(("resolution", "source", "encode", "visual_tag", "audio_tag", "audio_channels"))

_BYTES_PER_GB = 1024 ** 3

# Maps Zilean quality field to the token that rank_streams() regex filters recognise.
_QUALITY_TOKEN_MAP = {
    "WEB-DL": "WEB-DL",
    "WEB": "WEBRip",
    "BluRay": "BluRay",
    "BluRay REMUX": "BluRay Remux",
    "BRRip": "BRRip",
    "DVDRip": "DVDRip",
    "HDTV": "HDTV",
    "CAM": "CAM",
    "TS": "TS",
}


def _to_stream(raw: dict, season: int | None) -> TorrentioStream | None:
    info_hash = raw.get("info_hash") or ""
    if not info_hash:
        return None

    raw_title = raw.get("raw_title", "") or ""
    resolution = (raw.get("resolution") or "unknown").lower()
    # Normalise to the labels used in RESOLUTION_PREFERRED / release_tags.detect_resolution.
    quality = resolution if resolution in ("2160p", "1080p", "720p", "480p") else "unknown"

    zilean_quality = raw.get("quality") or ""
    # Embed the quality token in name so release_tags.detect_sources (webdl,
    # remux, cam, etc.) fires correctly.
    source_token = _QUALITY_TOKEN_MAP.get(zilean_quality, zilean_quality)
    name = f"{raw_title} {source_token}".strip()

    size_str = raw.get("size") or "0"
    try:
        size_gb = round(int(size_str) / _BYTES_PER_GB, 2)
    except (ValueError, TypeError):
        size_gb = 0.0

    return TorrentioStream(
        name=name,
        title=raw_title,
        info_hash=info_hash.lower(),
        quality=quality,
        seeders=0,
        size_gb=size_gb,
        is_season_pack=_looks_like_season_pack(raw_title, season),
        source="zilean",
    )


def _from_native(raw: dict, season: int | None) -> TorrentioStream:
    raw_title = raw.get("raw_title", "") or ""
    return TorrentioStream(
        name=raw_title,
        title=raw_title,
        info_hash=(raw.get("info_hash") or "").lower(),
        quality="unknown",
        seeders=0,
        size_gb=round((raw.get("size_bytes") or 0) / _BYTES_PER_GB, 2),
        is_season_pack=_looks_like_season_pack(raw_title, season),
        source="zilean",
    )


def fetch_streams(
    imdb_id: str,
    season: int | None = None,
    episode: int | None = None,
    timeout: int = 10,
    raise_on_error: bool = False,
) -> list[TorrentioStream]:
    """raise_on_error=True re-raises on a query failure instead of the default
    fail-open []. scrapers.py sets this so its outage guard can tell "could
    not search" apart from "searched, found nothing"."""
    mode = _settings.get("ZILEAN_MODE", "external")
    if mode == "native":
        return _fetch_streams_native(imdb_id, season, episode, raise_on_error)
    return _fetch_streams_external(imdb_id, season, episode, timeout, raise_on_error)


def _fetch_streams_native(imdb_id: str, season: int | None, episode: int | None,
                          raise_on_error: bool = False) -> list[TorrentioStream]:
    import tmdb
    import zilean_index
    try:
        title = tmdb.display_title(imdb_id, media_type="tv" if season is not None else "movie")
        if not title:
            # A per-title condition (nothing to resolve), not a scraper outage:
            # never raise here even when raise_on_error is set.
            log.warning("Zilean (native): could not resolve title for %s, skipping", imdb_id)
            return []
        raw_list = zilean_index.search(title, season=season, episode=episode)
        parsed = [_from_native(r, season) for r in raw_list]
        log.info("Zilean (native) returned %d results for %r", len(parsed), title)
        return parsed
    except Exception as exc:
        # Match _fetch_streams_external's fail-open behavior: a DB error
        # (disk I/O, lock contention on the shared zilean_index file) must
        # not propagate up into processor.py's season loop.
        log.warning("Zilean (native) unavailable for %s: %s", imdb_id, exc)
        if raise_on_error:
            raise
        return []


def _fetch_streams_external(
    imdb_id: str,
    season: int | None,
    episode: int | None,
    timeout: int,
    raise_on_error: bool = False,
) -> list[TorrentioStream]:
    params: dict[str, object] = {"ImdbId": imdb_id}
    if season is not None:
        params["Season"] = season
    if episode is not None:
        params["Episode"] = episode
    zilean_url = _settings.get("ZILEAN_URL", _ZILEAN_URL_DEFAULT)
    url = f"{zilean_url.rstrip('/')}/dmm/filtered"
    log.info("Querying Zilean: %s params=%s", url, params)
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("Zilean unavailable: %s", exc)
        if raise_on_error:
            raise
        return []
    raw_list = resp.json() or []
    parsed = [s for s in (_to_stream(r, season) for r in raw_list) if s is not None]
    log.info("Zilean returned %d results (%d parsed)", len(raw_list), len(parsed))
    return parsed
