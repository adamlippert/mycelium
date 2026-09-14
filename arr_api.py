"""Calls shared by radarr.py and sonarr.py: both root folder and quality
profile lookups hit the same /api/v3/ shape and shape the response the
same way, so there is one implementation instead of two identical ones."""
import requests


def _headers(api_key: str) -> dict:
    return {"X-Api-Key": api_key, "Accept": "application/json"}


def root_folders(url: str, api_key: str, timeout: int = 8) -> list[dict]:
    """[{"path", "free_space"}] from /api/v3/rootfolder. Raises on a bad
    key or an unreachable host so the caller can show the reason."""
    resp = requests.get(f"{url.rstrip('/')}/api/v3/rootfolder",
                        headers=_headers(api_key), timeout=timeout)
    resp.raise_for_status()
    return [{"path": f.get("path"), "free_space": f.get("freeSpace")}
            for f in (resp.json() or []) if f.get("path")]


def quality_profiles(url: str, api_key: str, timeout: int = 8) -> list[dict]:
    """[{"id", "name"}] from /api/v3/qualityprofile. Raises on a bad key
    or an unreachable host so the caller can show the reason."""
    resp = requests.get(f"{url.rstrip('/')}/api/v3/qualityprofile",
                        headers=_headers(api_key), timeout=timeout)
    resp.raise_for_status()
    return [{"id": p.get("id"), "name": p.get("name")}
            for p in (resp.json() or []) if p.get("id") is not None and p.get("name")]
