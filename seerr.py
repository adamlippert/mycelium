import logging

import requests

import config

log = logging.getLogger(__name__)


def _seerr_url() -> str:
    """Resolve SEERR_URL from settings DB first, env/config fallback.

    Imports settings locally (not at module level) so this always reads
    whatever object is currently in sys.modules["settings"]: several test
    files reimport that module fresh mid-session, and a module-level `import
    settings as _settings` bound here at seerr.py's own first import would
    silently keep pointing at the stale one.
    """
    import settings
    return (settings.get("SEERR_URL", config.SEERR_URL) or "").strip()


def _seerr_api_key() -> str:
    import settings
    return (settings.get("SEERR_API_KEY", config.SEERR_API_KEY) or "").strip()


def is_configured() -> bool:
    """True when a Seerr URL is set (settings DB or env). SPA-only mode → False."""
    return bool(_seerr_url())


def _headers() -> dict[str, str]:
    key = _seerr_api_key()
    return {"X-Api-Key": key} if key else {}


def get_request(request_id: str | int, timeout: int = 10) -> dict:
    base = _seerr_url()
    if not base:
        raise RuntimeError("SEERR_URL is not configured")
    url = f"{base.rstrip('/')}/api/v1/request/{request_id}"
    log.info("Fetching Seerr request: %s", url)
    resp = requests.get(url, headers=_headers(), timeout=timeout)
    resp.raise_for_status()
    return resp.json() or {}


def list_approved_requests(take: int = 20, skip: int = 0, timeout: int = 10) -> list[dict]:
    base = _seerr_url()
    if not base:
        raise RuntimeError("SEERR_URL is not configured")
    url = f"{base.rstrip('/')}/api/v1/request"
    params = {"filter": "approved", "take": take, "skip": skip}
    log.info("Fetching approved Seerr requests (take=%d skip=%d)", take, skip)
    resp = requests.get(url, headers=_headers(), params=params, timeout=timeout)
    resp.raise_for_status()
    return (resp.json() or {}).get("results", [])


# Seerr's spec also lists "deleted", but 3.4.1 answers 200 to it and changes
# nothing (measured 2026-09-07). Removing a title is delete_media().
_MEDIA_STATES = ("available", "partial", "processing", "pending", "unknown")


def find_media(tmdb_id: int, media_type: str, timeout: int = 10) -> dict | None:
    """Look a title up by TMDB id: GET /movie/{tmdb} or /tv/{tmdb}.

    Returns {"media_id", "status", "request_ids"} from mediaInfo, where
    request_ids are the pending (1) and approved (2) requests, or None when
    Seerr has never seen the title. This needs no Seerr request id, which
    titles requested before 0.14.0 and every series lack."""
    base = _seerr_url()
    if not base or not tmdb_id:
        return None
    kind = "movie" if media_type == "movie" else "tv"
    resp = requests.get(f"{base.rstrip('/')}/api/v1/{kind}/{tmdb_id}",
                        headers=_headers(), timeout=timeout)
    if resp.status_code >= 400:
        log.debug("Seerr lookup of %s %s failed: %s", kind, tmdb_id, resp.status_code)
        return None
    info = (resp.json() or {}).get("mediaInfo") or {}
    if not info.get("id"):
        return None
    request_ids = [int(r["id"]) for r in (info.get("requests") or [])
                   if r.get("id") and r.get("status") in (1, 2)]
    return {"media_id": int(info["id"]), "status": info.get("status"), "request_ids": request_ids}


def delete_media(media_id: int, timeout: int = 10) -> bool:
    """DELETE /media/{id}: what Seerr's own "clear media data" does. The
    title becomes requestable again at once; an already-missing record
    counts as done."""
    base = _seerr_url()
    if not base:
        return False
    resp = requests.delete(f"{base.rstrip('/')}/api/v1/media/{media_id}",
                           headers=_headers(), timeout=timeout)
    if resp.status_code == 404:
        return True
    if resp.status_code >= 400:
        log.warning("Seerr delete of media %s failed: %s %s", media_id, resp.status_code, resp.text[:200])
        return False
    return True


def set_media_status_by_id(media_id: int, status: str, timeout: int = 10) -> bool:
    """POST /media/{mediaId}/{status}."""
    if status not in _MEDIA_STATES:
        raise ValueError(f"bad Seerr media status {status!r}")
    base = _seerr_url()
    if not base:
        return False
    resp = requests.post(f"{base.rstrip('/')}/api/v1/media/{media_id}/{status}",
                         headers=_headers(), json={"is4k": False}, timeout=timeout)
    if resp.status_code >= 400:
        log.warning("Seerr media %s -> %s failed: %s %s", media_id, status, resp.status_code, resp.text[:200])
        return False
    return True


def decline_request(request_id: int, timeout: int = 10) -> bool:
    """POST /request/{id}/decline. Needs MANAGE_REQUESTS on the API key's user."""
    base = _seerr_url()
    if not base:
        return False
    resp = requests.post(f"{base.rstrip('/')}/api/v1/request/{request_id}/decline",
                         headers=_headers(), timeout=timeout)
    if resp.status_code >= 400:
        log.warning("Seerr decline of request %s failed: %s %s", request_id, resp.status_code, resp.text[:200])
        return False
    return True


def set_media_status(request_id: int, status: str, timeout: int = 10) -> bool:
    """Resolve the request's media id, then POST /media/{mediaId}/{status}."""
    if status not in _MEDIA_STATES:
        raise ValueError(f"bad Seerr media status {status!r}")
    base = _seerr_url()
    if not base:
        return False
    media_id = ((get_request(request_id, timeout=timeout).get("media") or {}).get("id"))
    if not media_id:
        log.warning("Seerr request %s has no media id", request_id)
        return False
    return set_media_status_by_id(media_id, status, timeout=timeout)
