"""Sonarr API client  -  pull all series from an existing Sonarr instance."""
import logging

import requests

log = logging.getLogger(__name__)


def _headers(api_key: str) -> dict:
    return {"X-Api-Key": api_key, "Accept": "application/json"}


def list_series(url: str, api_key: str, timeout: int = 30) -> list[dict]:
    """Return all series from Sonarr. Each item has id, tvdbId, imdbId, tmdbId, title, monitored, seasons, path."""
    base = url.rstrip("/")
    log.info("Sonarr: fetching series from %s", base)
    resp = requests.get(f"{base}/api/v3/series", headers=_headers(api_key), timeout=timeout)
    resp.raise_for_status()
    items = resp.json() or []
    out = []
    for s in items:
        seasons = [se.get("seasonNumber") for se in (s.get("seasons") or [])
                   if se.get("seasonNumber", 0) >= 1 and se.get("monitored")]
        out.append({
            "id": s.get("id"),
            "tvdb_id": s.get("tvdbId"),
            "tmdb_id": s.get("tmdbId"),
            "imdb_id": s.get("imdbId") or "",
            "title": s.get("title") or "",
            "year": s.get("year"),
            "monitored": bool(s.get("monitored")),
            "seasons": seasons,
            "path": s.get("path"),
        })
    log.info("Sonarr: %d series returned", len(out))
    return out


def ping(url: str, api_key: str, timeout: int = 8) -> bool:
    try:
        resp = requests.get(f"{url.rstrip('/')}/api/v3/system/status",
                            headers=_headers(api_key), timeout=timeout)
        return resp.status_code == 200
    except Exception as exc:
        log.warning("Sonarr ping failed: %s", exc)
        return False


def system_status(url: str, api_key: str, timeout: int = 8) -> dict | None:
    """{"version": ...} from /api/v3/system/status, or None when unreachable
    or refused. Feeds the Test button in Settings."""
    try:
        resp = requests.get(f"{url.rstrip('/')}/api/v3/system/status",
                            headers=_headers(api_key), timeout=timeout)
        if resp.status_code != 200:
            log.warning("Sonarr status returned %s", resp.status_code)
            return None
        return {"version": (resp.json() or {}).get("version")}
    except Exception as exc:
        log.warning("Sonarr status failed: %s", exc)
        return None


def root_folders(url: str, api_key: str, timeout: int = 8) -> list[dict]:
    """[{"path", "free_space"}] from /api/v3/rootfolder. Raises on a bad
    key or an unreachable host so the caller can show the reason."""
    resp = requests.get(f"{url.rstrip('/')}/api/v3/rootfolder",
                        headers=_headers(api_key), timeout=timeout)
    resp.raise_for_status()
    return [{"path": f.get("path"), "free_space": f.get("freeSpace")}
            for f in (resp.json() or []) if f.get("path")]
