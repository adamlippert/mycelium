"""Radarr API client  -  pull all movies from an existing Radarr instance."""
import logging

import requests

from arr_api import root_folders, quality_profiles  # noqa: F401 (re-exported)

log = logging.getLogger(__name__)


def _headers(api_key: str) -> dict:
    return {"X-Api-Key": api_key, "Accept": "application/json"}


def list_movies(url: str, api_key: str, timeout: int = 30) -> list[dict]:
    """Return all movies from Radarr. Each item has id, tmdbId, imdbId, title, year, monitored, path."""
    base = url.rstrip("/")
    log.info("Radarr: fetching movies from %s", base)
    resp = requests.get(f"{base}/api/v3/movie", headers=_headers(api_key), timeout=timeout)
    resp.raise_for_status()
    items = resp.json() or []
    out = []
    for m in items:
        out.append({
            "id": m.get("id"),
            "tmdb_id": m.get("tmdbId"),
            "imdb_id": m.get("imdbId") or "",
            "title": m.get("title") or "",
            "year": m.get("year"),
            "monitored": bool(m.get("monitored")),
            "has_file": bool(m.get("hasFile")),
            "path": m.get("path"),
        })
    log.info("Radarr: %d movie(s) returned", len(out))
    return out


def ping(url: str, api_key: str, timeout: int = 8) -> bool:
    try:
        resp = requests.get(f"{url.rstrip('/')}/api/v3/system/status",
                            headers=_headers(api_key), timeout=timeout)
        return resp.status_code == 200
    except Exception as exc:
        log.warning("Radarr ping failed: %s", exc)
        return False


def system_status(url: str, api_key: str, timeout: int = 8) -> dict | None:
    """{"version": ...} from /api/v3/system/status, or None when unreachable
    or refused. Feeds the Test button in Settings."""
    try:
        resp = requests.get(f"{url.rstrip('/')}/api/v3/system/status",
                            headers=_headers(api_key), timeout=timeout)
        if resp.status_code != 200:
            log.warning("Radarr status returned %s", resp.status_code)
            return None
        return {"version": (resp.json() or {}).get("version")}
    except Exception as exc:
        log.warning("Radarr status failed: %s", exc)
        return None


