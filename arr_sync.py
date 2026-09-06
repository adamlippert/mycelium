"""Mirror Mycelium's library into Radarr and Sonarr.

The arrs are bookkeeping for the rest of the stack: Seerr reads them for
availability, Maintainerr deletes through them, and the calendar widgets in
Jellyfin Enhanced and Homarr read their monitored lists. None of that works
for titles they have never heard of, and until now Mycelium never told them.

One direction only. Mycelium decides what exists: a title is added here when
Mycelium adds it and removed here when "Remove from library" runs. Entries
are monitored with search OFF and the arrs are expected to have no download
client, so nothing is ever grabbed. The arrs never import .strm files, so a
mirrored title shows as "Missing" there. That is cosmetic and expected.

Every public function is best-effort: it logs and returns False rather than
raising into the pipeline that called it.
"""
import logging
import threading

import requests

import db
import settings as _settings

log = logging.getLogger(__name__)

_TIMEOUT = 15
_lock = threading.Lock()
# kind -> (quality_profile_id, root_folder). The arr's answer does not change
# between calls; asking once per process keeps reconcile cheap.
_defaults_cache: dict[str, tuple[int, str]] = {}


class ArrError(RuntimeError):
    pass


def is_enabled() -> bool:
    return bool(_settings.get("ARR_SYNC_ENABLED", False))


def _conn(kind: str) -> tuple[str, str]:
    """(base_url, api_key) for 'radarr' or 'sonarr'; empty strings when unset."""
    url = (_settings.get(f"{kind.upper()}_URL", "") or "").strip().rstrip("/")
    key = (_settings.get(f"{kind.upper()}_API_KEY", "") or "").strip()
    return url, key


def _request(method: str, url: str, api_key: str, *, params=None, json=None) -> tuple[int, object]:
    """One HTTP call: (status, decoded body or None). Tests replace this."""
    resp = requests.request(
        method, url,
        headers={"X-Api-Key": api_key, "Accept": "application/json"},
        params=params, json=json, timeout=_TIMEOUT,
    )
    body = None
    if resp.content:
        try:
            body = resp.json()
        except ValueError:
            body = resp.text
    return resp.status_code, body


def _defaults(kind: str, base: str, key: str) -> tuple[int, str]:
    """First quality profile, plus the root folder (setting, else the first)."""
    with _lock:
        if kind in _defaults_cache:
            return _defaults_cache[kind]
    status, profiles = _request("GET", f"{base}/api/v3/qualityprofile", key)
    if status != 200 or not profiles:
        raise ArrError(f"{kind}: no quality profiles ({status})")
    root = (_settings.get(f"{kind.upper()}_ROOT_FOLDER", "") or "").strip()
    if not root:
        status, roots = _request("GET", f"{base}/api/v3/rootfolder", key)
        if status != 200 or not roots:
            raise ArrError(f"{kind}: no root folders ({status})")
        root = roots[0]["path"]
    out = (int(profiles[0]["id"]), root)
    with _lock:
        _defaults_cache[kind] = out
    return out


def _lookup(base: str, key: str, resource: str, terms: list[str], id_field: str) -> dict | None:
    """First lookup hit that carries id_field, trying each term in order."""
    for term in terms:
        status, body = _request("GET", f"{base}/api/v3/{resource}/lookup", key,
                                params={"term": term})
        if status == 200 and body:
            for hit in body:
                if hit.get(id_field):
                    return hit
    return None


def _existing(base: str, key: str, resource: str, id_field: str, value) -> dict | None:
    status, body = _request("GET", f"{base}/api/v3/{resource}", key, params={id_field: value})
    if status == 200 and body:
        return body[0]
    return None


# -- Radarr --------------------------------------------------------------------

def _add_movie(imdb_id: str, tmdb_id: int | None, title: str) -> bool:
    base, key = _conn("radarr")
    if not base or not key:
        log.debug("Arr sync: Radarr not configured; skipping %s", imdb_id)
        return False
    terms = [f"imdb:{imdb_id}"] + ([f"tmdb:{tmdb_id}"] if tmdb_id else [])
    found = _lookup(base, key, "movie", terms, "tmdbId")
    if not found:
        log.info("Arr sync: Radarr has no match for %s (%s)", title or imdb_id, imdb_id)
        return False
    if found.get("id") or _existing(base, key, "movie", "tmdbId", found["tmdbId"]):
        return True
    profile_id, root = _defaults("radarr", base, key)
    body = dict(found)
    body.update({
        "qualityProfileId": profile_id,
        "rootFolderPath": root,
        "monitored": True,
        "minimumAvailability": "released",
        "addOptions": {"searchForMovie": False, "monitor": "movieOnly"},
    })
    status, resp = _request("POST", f"{base}/api/v3/movie", key, json=body)
    if status in (200, 201):
        log.info("Arr sync: mirrored %s (%s) into Radarr", title or imdb_id, imdb_id)
        return True
    if status == 400 and "exist" in str(resp).lower():
        return True
    log.warning("Arr sync: Radarr refused %s: %s %s", imdb_id, status, str(resp)[:200])
    return False


def _remove_movie(imdb_id: str, tmdb_id: int | None) -> bool:
    base, key = _conn("radarr")
    if not base or not key:
        return False
    if not tmdb_id:
        found = _lookup(base, key, "movie", [f"imdb:{imdb_id}"], "tmdbId")
        tmdb_id = found.get("tmdbId") if found else None
    if not tmdb_id:
        log.info("Arr sync: cannot resolve %s for Radarr removal", imdb_id)
        return False
    existing = _existing(base, key, "movie", "tmdbId", tmdb_id)
    if not existing:
        return True
    status, _ = _request("DELETE", f"{base}/api/v3/movie/{existing['id']}", key,
                         params={"deleteFiles": "false", "addImportExclusion": "false"})
    if status in (200, 204, 404):
        log.info("Arr sync: removed %s from Radarr", imdb_id)
        return True
    log.warning("Arr sync: Radarr delete of %s failed: %s", imdb_id, status)
    return False


# -- Sonarr --------------------------------------------------------------------

def _sonarr_find(base: str, key: str, imdb_id: str, tmdb_id: int | None) -> dict | None:
    found = _lookup(base, key, "series", [f"imdb:{imdb_id}"], "tvdbId")
    if found or not tmdb_id:
        return found
    import tmdb
    tvdb_id = tmdb.tvdb_id_for(tmdb_id)
    if not tvdb_id:
        return None
    return _lookup(base, key, "series", [f"tvdb:{tvdb_id}"], "tvdbId")


def _add_series(imdb_id: str, tmdb_id: int | None, title: str) -> bool:
    base, key = _conn("sonarr")
    if not base or not key:
        log.debug("Arr sync: Sonarr not configured; skipping %s", imdb_id)
        return False
    found = _sonarr_find(base, key, imdb_id, tmdb_id)
    if not found:
        log.info("Arr sync: Sonarr has no match for %s (%s)", title or imdb_id, imdb_id)
        return False
    if found.get("id") or _existing(base, key, "series", "tvdbId", found["tvdbId"]):
        return True
    profile_id, root = _defaults("sonarr", base, key)
    body = dict(found)
    body.update({
        "qualityProfileId": profile_id,
        "rootFolderPath": root,
        "monitored": True,
        "seasonFolder": True,
        "addOptions": {
            "searchForMissingEpisodes": False,
            "searchForCutoffUnmetEpisodes": False,
            "monitor": "all",
        },
    })
    status, resp = _request("POST", f"{base}/api/v3/series", key, json=body)
    if status in (200, 201):
        log.info("Arr sync: mirrored %s (%s) into Sonarr", title or imdb_id, imdb_id)
        return True
    if status == 400 and "exist" in str(resp).lower():
        return True
    log.warning("Arr sync: Sonarr refused %s: %s %s", imdb_id, status, str(resp)[:200])
    return False


def _remove_series(imdb_id: str, tmdb_id: int | None) -> bool:
    base, key = _conn("sonarr")
    if not base or not key:
        return False
    found = _sonarr_find(base, key, imdb_id, tmdb_id)
    if not found:
        log.info("Arr sync: cannot resolve %s for Sonarr removal", imdb_id)
        return False
    existing = _existing(base, key, "series", "tvdbId", found["tvdbId"])
    if not existing:
        return True
    status, _ = _request("DELETE", f"{base}/api/v3/series/{existing['id']}", key,
                         params={"deleteFiles": "false", "addImportListExclusion": "false"})
    if status in (200, 204, 404):
        log.info("Arr sync: removed %s from Sonarr", imdb_id)
        return True
    log.warning("Arr sync: Sonarr delete of %s failed: %s", imdb_id, status)
    return False


# -- public --------------------------------------------------------------------

def mirror_add(imdb_id: str, media_type: str, tmdb_id: int | None = None, title: str = "") -> bool:
    """Ensure the title exists in the matching arr. Never raises."""
    if not is_enabled() or not imdb_id:
        return False
    try:
        if media_type == "movie":
            return _add_movie(imdb_id, tmdb_id, title)
        return _add_series(imdb_id, tmdb_id, title)
    except Exception as exc:
        log.warning("Arr sync: add of %s failed: %s", imdb_id, exc)
        return False


def mirror_remove(imdb_id: str, media_type: str, tmdb_id: int | None = None) -> bool:
    """Ensure the title is absent from the matching arr. Never raises.
    A title the arr does not have counts as success, so a purge that was
    itself triggered by the arr's delete webhook does not fail."""
    if not is_enabled() or not imdb_id:
        return False
    try:
        if media_type == "movie":
            return _remove_movie(imdb_id, tmdb_id)
        return _remove_series(imdb_id, tmdb_id)
    except Exception as exc:
        log.warning("Arr sync: removal of %s failed: %s", imdb_id, exc)
        return False


def reconcile() -> dict:
    """Add every successful Mycelium title the arrs lack. Never removes from
    the arrs: they may hold titles Mycelium does not own. Scheduled."""
    out = {"checked": 0, "added": 0, "failed": 0, "skipped": 0}
    if not is_enabled():
        return out
    import radarr
    import sonarr
    have: dict[str, set] = {"movie": set(), "series": set()}
    r_base, r_key = _conn("radarr")
    s_base, s_key = _conn("sonarr")
    try:
        if r_base and r_key:
            for m in radarr.list_movies(r_base, r_key):
                have["movie"].update(x for x in (m.get("imdb_id"), m.get("tmdb_id")) if x)
        if s_base and s_key:
            for s in sonarr.list_series(s_base, s_key):
                have["series"].update(x for x in (s.get("imdb_id"), s.get("tmdb_id")) if x)
    except Exception as exc:
        log.warning("Arr sync: reconcile could not list the arrs: %s", exc)
        return out
    for row in db.get_recent(100000):
        if row.get("status") != "success":
            out["skipped"] += 1
            continue
        out["checked"] += 1
        kind = "movie" if row["media_type"] == "movie" else "series"
        if row["imdb_id"] in have[kind] or (row.get("tmdb_id") and row["tmdb_id"] in have[kind]):
            continue
        if mirror_add(row["imdb_id"], row["media_type"], row.get("tmdb_id"), row.get("title") or ""):
            out["added"] += 1
        else:
            out["failed"] += 1
    log.info("Arr sync: reconcile %s", out)
    return out
