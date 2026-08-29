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
