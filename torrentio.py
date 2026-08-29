import logging
import re

import requests

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
    _QUALITY_PATTERNS,
)

log = logging.getLogger(__name__)

# Historical name. Six call sites and several tests import TorrentioStream
# from here; keep it working.
TorrentioStream = Stream

_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}

# Language / audio markers in release titles
def _classify_quality(stream: dict) -> str:
    blob = f"{stream.get('name', '')} {stream.get('title', '')}"
    for label, pattern in _QUALITY_PATTERNS.items():
        if pattern.search(blob):
            return label
    return "unknown"


def _looks_like_season_pack(title: str, season: int | None) -> bool:
    if season is None:
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
    log.info("Querying Torrentio: %s", url)
    resp = requests.get(url, timeout=timeout, headers=_HTTP_HEADERS)
    resp.raise_for_status()
    payload = resp.json() or {}
    raw_streams = payload.get("streams", []) or []
    parsed = [s for s in (_to_stream(r, season) for r in raw_streams) if s is not None]
    log.info("Torrentio returned %d streams (%d parsed)", len(raw_streams), len(parsed))
    return parsed


def pick_best(
    streams: list[TorrentioStream],
    prefer_season_pack: bool = False,
) -> TorrentioStream | None:
    ranked = rank_streams(streams, prefer_season_pack=prefer_season_pack)
    if not ranked:
        return None
    best = ranked[0]
    log.info(
        "Selected stream: quality=%s seeders=%d size=%.2fGB pack=%s hash=%s",
        best.quality,
        best.seeders,
        best.size_gb,
        best.is_season_pack,
        best.info_hash,
    )
    return best
