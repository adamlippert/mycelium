"""Debridio scraper.

Debridio is a Stremio addon: GET {base}/{config}/stream/{type}/{id}.json.
Its stream objects carry no infoHash field, but the BitTorrent hash is present
in behaviorHints.bingeGroup as 'debridio-<40 hex>' and again in the play-URL
path. Verified 702/702 consistent, with 88 of Torrentio's 111 hashes for the
same title appearing verbatim.

The config segment is base64 JSON holding the Debridio API key AND the user's
TorBox key, so the request URL is a secret. Nothing here may log it.
"""
import base64
import json
import logging
import re

import requests

import config
import settings as _settings

log = logging.getLogger(__name__)

_RESOLUTIONS = ["8k", "4k", "1440p", "1080p", "720p", "480p", "360p", "unknown"]
_HEX40_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_B64_SEGMENT_RE = re.compile(r"/(?:ey[A-Za-z0-9+/=_-]{16,})")


def _s(key: str):
    return _settings.get(key, getattr(config, key, None))


def is_configured() -> bool:
    """Debridio needs its own key and a TorBox key to proxy for."""
    return bool((_s("DEBRIDIO_API_KEY") or "").strip()
                and (_s("TORBOX_API_KEY") or "").strip())


def build_config_token() -> str:
    """Base64 config segment for the addon URL, or '' when unconfigured.

    Deliberately permissive: every resolution, no excluded qualities, no size
    limit. Mycelium's own filters are soft (they self-disable rather than
    return nothing) while Debridio's are hard, so pushing ours down would
    remove streams before rank_streams could decide to allow them anyway.
    """
    override = (_s("DEBRIDIO_CONFIG_TOKEN") or "").strip()
    if override:
        return override
    if not is_configured():
        return ""
    cfg = {
        "api_key": (_s("DEBRIDIO_API_KEY") or "").strip(),
        "provider": "torbox",
        "providerKey": (_s("TORBOX_API_KEY") or "").strip(),
        "disableUncached": False,
        "maxSize": "",
        "maxReturnPerQuality": str(_s("DEBRIDIO_MAX_RESULTS") or 100),
        "resolutions": list(_RESOLUTIONS),
        "excludedQualities": [],
        "preferredLang": [],
    }
    return base64.b64encode(json.dumps(cfg, separators=(",", ":")).encode()).decode()


def redact(text) -> str:
    """Strip Debridio credentials from a URL or exception message.

    Every log, HTTP response and health payload that might carry a Debridio
    URL must pass through this. The config segment and the play-URL path both
    contain the user's TorBox key.

    Scrubs the live credential values first: requests embeds URLs in exception
    messages in shapes we cannot enumerate, so matching the actual secrets is
    the only reliable protection. The pattern rules below are a backstop.
    """
    if not text:
        return ""
    out = str(text)
    for key in ("DEBRIDIO_CONFIG_TOKEN", "DEBRIDIO_API_KEY", "TORBOX_API_KEY"):
        secret = (_s(key) or "").strip()
        if len(secret) >= 8:          # too short to be a key; avoid over-scrubbing
            out = out.replace(secret, "<redacted>")
    out = _B64_SEGMENT_RE.sub("/<config>", out)
    out = re.sub(r"/play/(\w+)/(\w+)/[^/]+/[^/]+/", r"/play/\1/\2/<redacted>/<redacted>/", out)
    return out


from streams import Stream, parse_quality, parse_seeders, parse_size_gb

_SEASON_PACK_RE = re.compile(r"\b(complete|season|s\d{1,2}(?!\s*e))\b", re.IGNORECASE)


def _max_results() -> int:
    try:
        return int(_s("DEBRIDIO_MAX_RESULTS") or 100)
    except (TypeError, ValueError):
        return 100


def _extract_hash(item: dict) -> str:
    """Recover the info hash from bingeGroup, falling back to the URL path."""
    binge = (item.get("behaviorHints") or {}).get("bingeGroup") or ""
    if binge.startswith("debridio-"):
        candidate = binge[len("debridio-"):]
        if _HEX40_RE.match(candidate):
            return candidate.lower()
    for part in (item.get("url") or "").split("/"):
        if _HEX40_RE.match(part):
            return part.lower()
    return ""


def _to_stream(item: dict) -> Stream | None:
    info_hash = _extract_hash(item)
    if not info_hash:
        return None
    name = item.get("name") or ""
    title = item.get("title") or ""
    filename = (item.get("behaviorHints") or {}).get("filename") or ""
    blob = f"{name} {title} {filename}"
    return Stream(
        name=name,
        title=title or filename,
        info_hash=info_hash,
        quality=parse_quality(blob),
        seeders=parse_seeders(title),
        size_gb=parse_size_gb(title),
        is_season_pack=bool(_SEASON_PACK_RE.search(filename or title)),
        source="debridio",
        cached="⚡" in name,
    )


def fetch(media_type: str, imdb_id: str, season: int | None = None,
          episode: int | None = None, timeout: int = 30) -> list[Stream]:
    """Return Debridio candidates. Never raises; returns [] on any failure."""
    token = build_config_token()
    if not token:
        return []
    kind = "movie" if media_type == "movie" else "series"
    stream_id = imdb_id if season is None else f"{imdb_id}:{season}:{episode or 1}"
    base = (_s("DEBRIDIO_BASE_URL") or "https://addon.debridio.com").rstrip("/")
    url = f"{base}/{token}/stream/{kind}/{stream_id}.json"

    log.info("Querying Debridio for %s (%s)", imdb_id, kind)
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        payload = resp.json() or {}
    except Exception as exc:
        log.warning("Debridio request failed for %s: %s", imdb_id, redact(exc))
        return []

    raw = payload.get("streams") or []
    out, skipped = [], 0
    for item in raw:
        stream = _to_stream(item)
        if stream is None:
            skipped += 1
        else:
            out.append(stream)
    if skipped:
        log.warning("Debridio: %d/%d stream(s) had no recoverable info hash "
                    "for %s - the response shape may have changed",
                    skipped, len(raw), imdb_id)

    _QUALITY_ORDER = {"2160p": 0, "1080p": 1, "720p": 2, "480p": 3, "": 4}
    out.sort(key=lambda s: (_QUALITY_ORDER.get(s.quality, 4), -s.size_gb))
    capped = out[:_max_results()]
    log.info("Debridio: %d stream(s) for %s (%d after cap)", len(out), imdb_id, len(capped))
    return capped
