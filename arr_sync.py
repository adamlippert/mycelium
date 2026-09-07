"""Mirror Mycelium's library into Radarr and Sonarr.

The arrs are bookkeeping for the rest of the stack: Seerr reads them for
availability, Maintainerr deletes through them, and the calendar widgets in
Jellyfin Enhanced and Homarr read their monitored lists. None of that works
for titles they have never heard of, and until now Mycelium never told them.

Mycelium decides what gets added: a title is added here when Mycelium adds
it and removed here when "Remove from library" runs. The other way round, a
title Mycelium mirrored that later vanishes from the arr, or whose .strm
files vanish from disk, is taken as deleted elsewhere and purged from
Mycelium by reconcile(), behind guards against a rebuilt arr or a lost
mount (ARR_SYNC_PURGE_ENABLED=false restores the add-only mirror). Entries
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

# A success can make up to six calls while the per-title lock is held; this
# is bookkeeping, so an arr that does not answer in 8 s is treated as down.
_TIMEOUT = 8
_lock = threading.Lock()
# (quality_profile_id, root_folder) per arr, fetched once so reconcile stays
# cheap. Keyed on (kind, base url, root-folder setting) so a changed URL or a new
# root-folder pick in Settings takes effect on the next call, not after a
# restart.
_defaults_cache: dict[tuple[str, str, str], tuple[int, str]] = {}


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
    root_setting = (_settings.get(f"{kind.upper()}_ROOT_FOLDER", "") or "").strip()
    cache_key = (kind, base, root_setting)
    with _lock:
        if cache_key in _defaults_cache:
            return _defaults_cache[cache_key]
    status, profiles = _request("GET", f"{base}/api/v3/qualityprofile", key)
    if status != 200 or not profiles:
        raise ArrError(f"{kind}: no quality profiles ({status})")
    root = root_setting
    if not root:
        status, roots = _request("GET", f"{base}/api/v3/rootfolder", key)
        if status != 200 or not roots:
            raise ArrError(f"{kind}: no root folders ({status})")
        root = roots[0]["path"]
    out = (int(profiles[0]["id"]), root)
    with _lock:
        _defaults_cache[cache_key] = out
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


def rescan(kind: str, base: str, key: str, arr_id: int) -> bool:
    """Ask the arr to look at one title's folder now. Without this a new
    stub is only noticed by the arr's 12-hourly refresh."""
    if kind == "movie":
        body = {"name": "RescanMovie", "movieId": int(arr_id)}
    else:
        body = {"name": "RescanSeries", "seriesId": int(arr_id)}
    status, resp = _request("POST", f"{base}/api/v3/command", key, json=body)
    if status in (200, 201):
        return True
    log.warning("Arr sync: %s rescan of %s failed: %s %s", kind, arr_id, status, str(resp)[:200])
    return False


def _write_stubs(imdb_id: str, media_type: str, arr_obj: dict | None) -> int:
    """Stubs for a title the arr now knows; rescan if anything was written.
    Best-effort: a stub problem never fails the mirror."""
    import arr_stubs
    if not arr_stubs.is_enabled() or not arr_obj or not arr_obj.get("path"):
        return 0
    kind = "movie" if media_type == "movie" else "series"
    try:
        written = arr_stubs.write_title(imdb_id, media_type, arr_obj["path"])
    except Exception as exc:
        log.warning("Arr sync: stubs for %s failed: %s", imdb_id, exc)
        return 0
    if written and arr_obj.get("id"):
        base, key = _conn("radarr" if kind == "movie" else "sonarr")
        try:
            rescan(kind, base, key, arr_obj["id"])
        except Exception as exc:
            log.warning("Arr sync: rescan for %s failed: %s", imdb_id, exc)
    return written


# -- Radarr --------------------------------------------------------------------

def _add_movie(imdb_id: str, tmdb_id: int | None, title: str) -> tuple[str, dict | None]:
    base, key = _conn("radarr")
    if not base or not key:
        log.debug("Arr sync: Radarr not configured; skipping %s", imdb_id)
        return "skipped", None
    terms = [f"imdb:{imdb_id}"] + ([f"tmdb:{tmdb_id}"] if tmdb_id else [])
    found = _lookup(base, key, "movie", terms, "tmdbId")
    if not found:
        log.info("Arr sync: Radarr has no match for %s (%s)", title or imdb_id, imdb_id)
        return "unmatched", None
    if found.get("id"):
        return "present", found
    existing = _existing(base, key, "movie", "tmdbId", found["tmdbId"])
    if existing:
        return "present", existing
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
        return "added", resp if isinstance(resp, dict) else None
    if status == 400 and "exist" in str(resp).lower():
        return "present", _existing(base, key, "movie", "tmdbId", found["tmdbId"])
    log.warning("Arr sync: Radarr refused %s: %s %s", imdb_id, status, str(resp)[:200])
    return "failed", None


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
        try:
            import arr_stubs
            arr_stubs.remove_title("movie", imdb_id)
        except Exception as exc:
            log.warning("Arr sync: stub removal for %s failed: %s", imdb_id, exc)
        return True
    try:
        import arr_stubs
        arr_stubs.remove_title("movie", imdb_id, existing.get("path"))
    except Exception as exc:
        log.warning("Arr sync: stub removal for %s failed: %s", imdb_id, exc)
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


def _add_series(imdb_id: str, tmdb_id: int | None, title: str) -> tuple[str, dict | None]:
    base, key = _conn("sonarr")
    if not base or not key:
        log.debug("Arr sync: Sonarr not configured; skipping %s", imdb_id)
        return "skipped", None
    found = _sonarr_find(base, key, imdb_id, tmdb_id)
    if not found:
        log.info("Arr sync: Sonarr has no match for %s (%s)", title or imdb_id, imdb_id)
        return "unmatched", None
    if found.get("id"):
        return "present", found
    existing = _existing(base, key, "series", "tvdbId", found["tvdbId"])
    if existing:
        return "present", existing
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
        return "added", resp if isinstance(resp, dict) else None
    if status == 400 and "exist" in str(resp).lower():
        return "present", _existing(base, key, "series", "tvdbId", found["tvdbId"])
    log.warning("Arr sync: Sonarr refused %s: %s %s", imdb_id, status, str(resp)[:200])
    return "failed", None


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
        try:
            import arr_stubs
            arr_stubs.remove_title("series", imdb_id)
        except Exception as exc:
            log.warning("Arr sync: stub removal for %s failed: %s", imdb_id, exc)
        return True
    try:
        import arr_stubs
        arr_stubs.remove_title("series", imdb_id, existing.get("path"))
    except Exception as exc:
        log.warning("Arr sync: stub removal for %s failed: %s", imdb_id, exc)
    status, _ = _request("DELETE", f"{base}/api/v3/series/{existing['id']}", key,
                         params={"deleteFiles": "false", "addImportListExclusion": "false"})
    if status in (200, 204, 404):
        log.info("Arr sync: removed %s from Sonarr", imdb_id)
        return True
    log.warning("Arr sync: Sonarr delete of %s failed: %s", imdb_id, status)
    return False


# -- public --------------------------------------------------------------------

def _stubs_enabled() -> bool:
    import arr_stubs
    return arr_stubs.is_enabled()


def _ensure(imdb_id: str, media_type: str, tmdb_id: int | None, title: str) -> str:
    """One of "added", "present", "unmatched", "failed", "skipped". Never raises."""
    state, _ = _ensure_with_stubs(imdb_id, media_type, tmdb_id, title)
    return state


def _ensure_with_stubs(imdb_id: str, media_type: str, tmdb_id: int | None,
                       title: str, write_stubs: bool = True) -> tuple[str, int]:
    """(state, stubs written). write_stubs=False lets a caller (reconcile,
    when the stub root turned out unmounted for this run) suppress stub
    writes without touching the ARR_STUBS_ENABLED setting itself."""
    if not is_enabled() or not imdb_id:
        return "skipped", 0
    try:
        if media_type == "movie":
            state, arr_obj = _add_movie(imdb_id, tmdb_id, title)
        else:
            state, arr_obj = _add_series(imdb_id, tmdb_id, title)
    except Exception as exc:
        log.warning("Arr sync: add of %s failed: %s", imdb_id, exc)
        return "failed", 0
    stubs = _write_stubs(imdb_id, media_type, arr_obj) if write_stubs and state in ("added", "present") else 0
    if state in ("added", "present"):
        try:
            db.mark_arr_mirrored(imdb_id)
        except Exception as exc:
            log.debug("Arr sync: could not mark %s mirrored: %s", imdb_id, exc)
    return state, stubs


def mirror_add(imdb_id: str, media_type: str, tmdb_id: int | None = None, title: str = "") -> bool:
    """Ensure the title exists in the matching arr. Never raises."""
    return _ensure(imdb_id, media_type, tmdb_id, title) in ("added", "present")


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
    """Add every successful Mycelium title the arrs lack, and write stubs
    for it: a title the listing already shows the arr holds gets its stub
    straight from that listing entry (no lookup call needed); a title
    Mycelium finds unknown goes through _ensure_with_stubs, which adds or
    matches it in the arr first. Then purges what was deleted elsewhere:
    a mirrored title the arr confirms it no longer has, or one whose .strm
    files are all gone from disk (a Jellyfin delete). Never removes an arr
    entry it did not put there: the arrs may hold titles Mycelium does not
    own. Scheduled."""
    out = {"checked": 0, "added": 0, "present": 0, "failed": 0, "skipped": 0, "stubs": 0, "purged": 0}
    if not is_enabled():
        return out
    import radarr
    import sonarr
    stubs_enabled = _stubs_enabled()
    if stubs_enabled:
        import arr_stubs
        ok, note = arr_stubs.root_status()
        if not ok:
            log.warning("Arr stubs: %s", note)
            stubs_enabled = False
    have: dict[str, dict] = {"movie": {}, "series": {}}
    r_base, r_key = _conn("radarr")
    s_base, s_key = _conn("sonarr")
    try:
        if r_base and r_key:
            for m in radarr.list_movies(r_base, r_key):
                entry = {"id": m.get("id"), "path": m.get("path")}
                for k in (m.get("imdb_id"), m.get("tmdb_id")):
                    if k:
                        have["movie"][k] = entry
        if s_base and s_key:
            for s in sonarr.list_series(s_base, s_key):
                entry = {"id": s.get("id"), "path": s.get("path")}
                for k in (s.get("imdb_id"), s.get("tmdb_id")):
                    if k:
                        have["series"][k] = entry
    except Exception as exc:
        log.warning("Arr sync: reconcile could not list the arrs: %s", exc)
        return out
    success: list[dict] = []
    gone_in_arr: list[dict] = []
    configured = {k: _arr_configured(k) for k in ("movie", "series")}
    for row in db.get_recent(100000):
        if row.get("status") != "success":
            out["skipped"] += 1
            continue
        success.append(row)
        out["checked"] += 1
        kind = "movie" if row["media_type"] == "movie" else "series"
        entry = have[kind].get(row["imdb_id"]) or (row.get("tmdb_id") and have[kind].get(row["tmdb_id"]))
        if entry is not None:
            try:
                db.mark_arr_mirrored(row["imdb_id"])
            except Exception as exc:
                log.debug("Arr sync: could not mark %s mirrored: %s", row["imdb_id"], exc)
            if not stubs_enabled:
                # Known already and nothing to write: the old short-circuit,
                # unaffected by whether the listing carried id/path.
                continue
            # Counts a title the listing already showed the arr holds.
            out["present"] += 1
            if entry.get("id") and entry.get("path"):
                out["stubs"] += _write_stubs(row["imdb_id"], row["media_type"], entry)
            continue
        if row.get("arr_mirrored_at") and configured[kind]:
            # The arr held this title once and lists it no more. Absence
            # from the listing is a hint, not proof: the listing was taken
            # before this loop started, and Sonarr often lists a series
            # without any imdb/tmdb id at all. So a fresh mirror is left
            # alone, and the arr is asked directly before anything is
            # believed. Only a confirmed "absent" is a deletion.
            if not _older_than_grace(row):
                continue
            verdict, arr_obj = _arr_holds(kind, row["imdb_id"], row.get("tmdb_id"))
            if verdict == "absent":
                gone_in_arr.append(row)
                continue
            if verdict == "present":
                out["present"] += 1
                if stubs_enabled:
                    out["stubs"] += _write_stubs(row["imdb_id"], row["media_type"], arr_obj)
                continue
            # unknown: fall through to the add path, which reports the failure
        state, stubs = _ensure_with_stubs(row["imdb_id"], row["media_type"], row.get("tmdb_id"),
                                          row.get("title") or "", write_stubs=stubs_enabled)
        out["stubs"] += stubs
        if state == "present":
            # Counts a title the listing missed (Sonarr with no imdb/tmdb
            # for the series) but the arr lookup found already added.
            out["present"] += 1
        elif state == "added":
            out["added"] += 1
        else:
            out["failed"] += 1
    try:
        out["purged"], refused = _purge_deleted_elsewhere(gone_in_arr, success, have)
    except Exception as exc:
        log.warning("Arr sync: purge pass failed: %s", exc)
        refused = gone_in_arr
    for row in refused:
        # A refused purge falls back to the old behaviour: put the title back
        # in the arr. Idempotent, and it keeps a rebuilt arr from leaving the
        # library unmirrored for good.
        state, stubs = _ensure_with_stubs(row["imdb_id"], row["media_type"], row.get("tmdb_id"),
                                          row.get("title") or "", write_stubs=stubs_enabled)
        out["stubs"] += stubs
        out["added" if state == "added" else "present" if state == "present" else "failed"] += 1
    log.info("Arr sync: reconcile %s", out)
    return out


def _arr_configured(kind: str) -> bool:
    base, key = _conn("radarr" if kind == "movie" else "sonarr")
    return bool(base and key)


def _purge_enabled() -> bool:
    return bool(_settings.get("ARR_SYNC_PURGE_ENABLED", True))


def _arr_holds(kind: str, imdb_id: str, tmdb_id) -> tuple[str, dict | None]:
    """Ask the arr directly whether it still holds a title its listing did
    not show. ("present", arr object), ("absent", None) when the arr matched
    the title and has no entry for it, or ("unknown", None) when it could
    not be asked or could not even match the title. Only "absent" may lead
    to a purge."""
    base, key = _conn("radarr" if kind == "movie" else "sonarr")
    try:
        if kind == "movie":
            terms = [f"imdb:{imdb_id}"] + ([f"tmdb:{tmdb_id}"] if tmdb_id else [])
            found = _lookup(base, key, "movie", terms, "tmdbId")
            resource, id_field = "movie", "tmdbId"
        else:
            found = _sonarr_find(base, key, imdb_id, tmdb_id)
            resource, id_field = "series", "tvdbId"
        if not found:
            return "unknown", None
        if found.get("id"):
            return "present", found
        existing = _existing(base, key, resource, id_field, found[id_field])
        if existing:
            return "present", existing
        return "absent", None
    except Exception as exc:
        log.warning("Arr sync: could not confirm %s with the arr: %s", imdb_id, exc)
        return "unknown", None


# A deletion elsewhere is only believed when it looks like one. Below this
# many mirrored titles the fraction guard cannot say anything; above it, more
# than this share vanishing at once is a rebuilt arr or a lost mount, and the
# right move is to purge nothing and say so.
_PURGE_GUARD_MIN_TITLES = 5
_PURGE_GUARD_MAX_SHARE = 0.5
_PURGE_GRACE_MINUTES = 10


def _older_than_grace(row: dict) -> bool:
    """True when the row was last touched (updated, or first mirrored) more
    than the grace ago. A row still being written, or mirrored after this
    run's listing was taken, must not look deleted. Unparseable dates count
    as recent: no purge."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    stamps = [row.get("updated_at") or row.get("created_at") or "", row.get("arr_mirrored_at") or ""]
    for raw in stamps:
        if not raw:
            continue
        try:
            when = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return False
        if now - when <= timedelta(minutes=_PURGE_GRACE_MINUTES):
            return False
    return True


def _purge_deleted_elsewhere(gone_in_arr: list[dict], success: list[dict],
                             have: dict[str, dict]) -> tuple[int, list[dict]]:
    """Purge titles that were deleted in the arr (mirrored, confirmed absent)
    or in Jellyfin (every .strm gone from disk), each behind a guard that
    refuses when the whole listing or the whole media tree looks gone. Makes
    the delete webhooks an optimisation rather than a need. Returns (purged,
    arr-side rows that were refused and should be re-added instead)."""
    import cleanup
    import config
    from pathlib import Path
    from arr_webhook import files_still_present
    victims: dict[str, dict] = {}
    refused: list[dict] = []
    if not _purge_enabled():
        if gone_in_arr:
            log.info("Arr sync: ARR_SYNC_PURGE_ENABLED is off; re-adding %d title(s) the arr no longer has",
                     len(gone_in_arr))
        return 0, list(gone_in_arr)

    for kind in ("movie", "series"):
        gone = [r for r in gone_in_arr if ("movie" if r["media_type"] == "movie" else "series") == kind]
        if not gone:
            continue
        mirrored = [r for r in success
                    if r.get("arr_mirrored_at") and ("movie" if r["media_type"] == "movie" else "series") == kind]
        name = "Radarr" if kind == "movie" else "Sonarr"
        if not have[kind]:
            log.warning("Arr sync: %s listed nothing while %d mirrored title(s) exist; "
                        "refusing to purge (rebuilt or unreachable arr?)", name, len(mirrored))
            refused.extend(gone)
            continue
        if len(mirrored) >= _PURGE_GUARD_MIN_TITLES and len(gone) > _PURGE_GUARD_MAX_SHARE * len(mirrored):
            log.warning("Arr sync: %d of %d mirrored titles vanished from %s at once; "
                        "refusing to purge (rebuilt arr?)", len(gone), len(mirrored), name)
            refused.extend(gone)
            continue
        for r in gone:
            victims[r["imdb_id"]] = (r, f"deleted in {name}")

    media_root = Path(config.MEDIA_PATH)
    tree_alive = media_root.is_dir() and next(media_root.rglob("*.strm"), None) is not None
    with_files: list[dict] = []
    missing: list[dict] = []
    for r in success:
        try:
            items = [i for i in db.get_virtual_items_by_imdb(r["imdb_id"]) if i.get("strm_path")]
        except Exception as exc:
            log.debug("Arr sync: items for %s unavailable: %s", r["imdb_id"], exc)
            continue
        if not items:
            continue
        with_files.append(r)
        if not files_still_present(items) and _older_than_grace(r):
            missing.append(r)
    if missing:
        if not tree_alive:
            log.warning("Arr sync: no .strm under %s; refusing to purge %d title(s) with missing files "
                        "(media mount gone?)", media_root, len(missing))
        elif len(with_files) >= _PURGE_GUARD_MIN_TITLES and len(missing) > _PURGE_GUARD_MAX_SHARE * len(with_files):
            log.warning("Arr sync: %d of %d titles lost their files at once; refusing to purge",
                        len(missing), len(with_files))
        else:
            for r in missing:
                victims.setdefault(r["imdb_id"], (r, "its .strm files are gone from disk"))

    purged = 0
    for imdb_id, (r, why) in victims.items():
        try:
            log.info("Arr sync: %s (%s) was %s; purging", r.get("title") or imdb_id, imdb_id, why)
            cleanup.purge_title(imdb_id, row_id=r.get("id"))
            purged += 1
            try:
                db.log_activity("purged", r.get("title") or imdb_id,
                                f"{imdb_id}: {why}; removed by the arr reconcile")
            except Exception:
                pass
        except Exception as exc:
            log.warning("Arr sync: purge of %s failed: %s", imdb_id, exc)
    return purged, refused
