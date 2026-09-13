"""Pick another release for a movie or one episode.

candidates() is the list the processor saw, with each candidate's rule
verdict and TorBox cache state, so the admin Library drawer can offer a
manual swap when the auto-picked release turns out to be wrong.
"""
from __future__ import annotations

import logging
import re
import threading
import time

import db
import release_tags

log = logging.getLogger(__name__)

_HASH = re.compile(r"^[0-9a-fA-F]{40}$")

# How long swap_by_hash may reuse a candidates() result instead of scraping
# again. The candidates route and the panel never read this cache - they
# always scrape - only swap_by_hash's own re-validation does.
_CANDIDATES_CACHE_TTL_SEC = 300.0

_candidates_cache_lock = threading.Lock()
# (imdb_id, season, episode) -> (time.monotonic() at insert, candidates() result)
_candidates_cache: dict[tuple, tuple[float, dict]] = {}


class CandidatesUnavailable(Exception):
    """The scrapers could not answer; the caller can offer Retry."""


def find_item(imdb_id: str, season: int | None = None, episode: int | None = None) -> dict | None:
    if season is not None and episode is not None:
        return db.get_virtual_item_by_episode(imdb_id, season, episode)
    items = db.get_virtual_items_by_imdb(imdb_id, media_type="movie")
    return items[0] if items else None


def _row(s, verdict, cached: set[str], current_hash: str) -> dict:
    return {
        "info_hash": s.info_hash.lower(), "name": s.name, "quality": s.quality,
        "source": release_tags.source_label(s.name), "size_gb": s.size_gb, "seeders": s.seeders,
        "languages": list(s.languages), "cached": s.info_hash.lower() in cached,
        "scrapers": [s.source, *s.also_seen_in], "kept": verdict.kept,
        "rule": None if verdict.kept else verdict.rule, "value": None if verdict.kept else verdict.value,
        "current": s.info_hash.lower() == current_hash,
    }


def _cache_key(imdb_id: str, season: int | None, episode: int | None) -> tuple:
    return (imdb_id, season, episode)


def _store_candidates_cache(imdb_id: str, season: int | None, episode: int | None, result: dict) -> None:
    """Remember a candidates() result for swap_by_hash to reuse, and drop any
    entry older than the TTL so the dict never grows without bound. There is
    no "never" sentinel to worry about: an absent key already means that."""
    now = time.monotonic()
    with _candidates_cache_lock:
        stale = [k for k, (ts, _) in _candidates_cache.items() if now - ts > _CANDIDATES_CACHE_TTL_SEC]
        for k in stale:
            del _candidates_cache[k]
        _candidates_cache[_cache_key(imdb_id, season, episode)] = (now, result)


def _fresh_cached_candidates(imdb_id: str, season: int | None, episode: int | None) -> dict | None:
    """A cached candidates() result younger than the TTL, or None when there
    is no entry or it has expired."""
    key = _cache_key(imdb_id, season, episode)
    now = time.monotonic()
    with _candidates_cache_lock:
        entry = _candidates_cache.get(key)
        if entry is None:
            return None
        ts, result = entry
        if now - ts > _CANDIDATES_CACHE_TTL_SEC:
            del _candidates_cache[key]
            return None
        return result


def candidates(imdb_id: str, media_type: str, season: int | None = None, episode: int | None = None) -> dict:
    """The candidate releases the processor would have seen for this title
    (or episode), each tagged with its filter verdict and cache state.

    Raises CandidatesUnavailable when no scraper could be searched at all.
    A cache-check failure degrades to "nothing cached" rather than failing
    the whole call, since the list itself is still useful without badges.
    """
    import blacklist
    import debrid
    import scrapers
    import streams

    season_mode = season is not None and episode is None
    try:
        # A season scrape asks for episode 1, as the processor does, and keeps
        # the packs; single-episode releases cannot serve a whole season.
        found = scrapers.merge_candidates(media_type, imdb_id, season, 1 if season_mode else episode,
                                          raise_if_inconclusive=True)
    except scrapers.ScrapersUnavailable as exc:
        raise CandidatesUnavailable(str(exc) or exc.__class__.__name__) from exc
    if season_mode:
        found = [s for s in found if s.is_season_pack]

    # merge_candidates dedups per scraper but not across a mixed-case rehit of
    # the same torrent; collapse before ranking so no hash produces two rows.
    seen: set[str] = set()
    deduped = []
    for s in found:
        h = s.info_hash.lower()
        if h in seen:
            continue
        seen.add(h)
        deduped.append(s)
    found = deduped

    found = blacklist.filter_candidates(found)

    kept, verdicts = streams.rank_streams_explained(found, prefer_season_pack=season_mode,
                                                    override=db.get_show_override(imdb_id))
    verdict_of = {s.info_hash.lower(): v for s, v in zip(found, verdicts)}

    try:
        cached = {h.lower() for h in debrid.check_cached_multi([s.info_hash for s in found]).get("torbox", set())}
    except Exception as exc:
        log.warning("Cache check failed for %s candidates: %s", imdb_id, exc)
        cached = set()

    kept_hashes = {s.info_hash.lower() for s in kept}
    dropped = [s for s in found if s.info_hash.lower() not in kept_hashes]

    if season_mode:
        # "current" is every hash the season's episodes sit on; the row's
        # flag marks packs already in use. Coverage says which episodes a
        # cached pack contains, from TorBox's file list.
        eps = season_episodes(imdb_id, season)
        current_hashes = {(e.get("info_hash") or "").lower() for e in eps if e.get("info_hash")}
        rows = [_row(s, verdict_of[s.info_hash.lower()], cached, "") for s in kept + dropped]
        coverage = _season_coverage([r["info_hash"] for r in rows if r["cached"]], season,
                                    [e["episode"] for e in eps])
        for r in rows:
            r["current"] = r["info_hash"] in current_hashes
            r["episodes"] = coverage.get(r["info_hash"])
        result = {"current": None, "candidates": rows}
        _store_candidates_cache(imdb_id, season, episode, result)
        return result

    item = find_item(imdb_id, season, episode)
    current_hash = item["info_hash"].lower() if item else ""
    rows = [_row(s, verdict_of[s.info_hash.lower()], cached, current_hash) for s in kept + dropped]

    # current.source prefers the freshly-scraped candidate row's label, since
    # that reflects this live scrape; when the current hash isn't among the
    # found candidates at all, fall back to the stored virtual_items.source,
    # which now holds the same kind of release-type label.
    current = None
    if item:
        current_row = next((r for r in rows if r["current"]), None)
        current = {"info_hash": current_hash, "quality": item.get("quality"),
                   "source": current_row["source"] if current_row else item.get("source")}

    result = {"current": current, "candidates": rows}
    # Cached for swap_by_hash's own re-validation only; the route and the
    # panel that called this always want a live scrape, so nothing here reads
    # the cache back.
    _store_candidates_cache(imdb_id, season, episode, result)
    return result


def _drop_faststart_cache(token: str) -> None:
    """Remove the .fsh fast-start cache for token, if any. The .fsh file is
    keyed only by token, so a stale one after a swap would serve the old
    release's rewritten moov header on top of the new file's mdat bytes:
    garbage or a hard playback failure. init() not having run (startup
    failure, or simply not called in tests) is expected and quiet; a file
    that exists but resists deletion is not, and is worth a warning."""
    import mp4_faststart
    if mp4_faststart._CACHE_DIR is None:
        log.debug("No fast-start cache dir for %s: mp4_faststart.init() not called", token)
        return
    path = mp4_faststart._cache_path(token)
    if not path.exists():
        return
    try:
        path.unlink()
    except OSError as exc:
        log.warning("Could not drop fast-start cache for %s: %s", token, exc)


def parse_episode_ref(season, episode) -> tuple[int | None, int | None] | None:
    """Coerce a season/episode pair from a JSON body into ints, or None when
    invalid. None stays None; an int (not bool) or a digit string becomes
    int; anything else is invalid. A negative season or episode is invalid
    the same way a non-integer is (season 0 stays allowed, for specials).
    A season without an episode addresses the whole season (season swap);
    an episode without a season is invalid."""
    def _coerce(v):
        if v is None:
            return None, True
        if isinstance(v, bool):
            return None, False
        if isinstance(v, int):
            n = v
        elif isinstance(v, str) and re.fullmatch(r"-?\d+", v.strip()):
            n = int(v.strip())
        else:
            return None, False
        if n < 0:
            return None, False
        return n, True

    s, s_ok = _coerce(season)
    e, e_ok = _coerce(episode)
    if not s_ok or not e_ok:
        return None
    if s is None and e is not None:
        return None
    return (s, e)


BUSY_MESSAGE = "busy: a playback is materializing this title, try again in a few minutes"
ADMIN_LOCK_TIMEOUT_SEC = 10.0
UPGRADER_LOCK_TIMEOUT_SEC = 5.0


def swap(item: dict, candidate: dict, blacklist_old: bool = False, action: str = "swapped",
         lock_timeout: float | None = None) -> dict:
    """Put candidate's hash behind item's token. Nothing on disk changes.

    action names the activity-log event: the admin panel logs "swapped", the
    catbox auto-upgrader shares this same function but logs "upgraded", so
    both paths get identical side effects without identical labels.

    lock_timeout bounds the wait for the token lock, which catbox.materialize
    can hold for up to ten minutes while TorBox readies the torrent. On a
    timeout nothing is changed and {ok: False, message: BUSY_MESSAGE} comes
    back; None waits without limit."""
    import catbox
    old_hash = (item.get("info_hash") or "").lower()
    old_quality = item.get("quality") or "?"
    new_hash = candidate["info_hash"].lower()
    magnet = f"magnet:?xt=urn:btih:{new_hash}"
    lock = catbox._token_lock(item["token"])
    if not lock.acquire(timeout=-1 if lock_timeout is None else lock_timeout):
        return {"ok": False, "message": BUSY_MESSAGE}
    try:
        db.update_virtual_item_upgrade(item["token"], new_hash, magnet, candidate.get("quality"), candidate.get("source"))
        db.update_virtual_rd_id(item["token"], None)
        catbox.invalidate_url_cache(item["token"])
        _drop_faststart_cache(item["token"])
        key = catbox._content_key(item)
        if key:
            db.reset_playability_state(key)
    finally:
        lock.release()
    if item.get("season") is None and item.get("imdb_id"):
        req = db.get_request_by_imdb(item["imdb_id"])
        if req:
            db.set_request_release(req["id"], candidate.get("quality"), candidate.get("source"), new_hash)
    title = item.get("title") or item.get("imdb_id") or "?"
    label = " ".join(x for x in (candidate.get("quality"), candidate.get("source")) if x) or new_hash[:8]
    db.log_activity(action, title, f"{old_quality} to {candidate.get('quality') or '?'} ({candidate.get('name') or new_hash[:8]})",
                    True, imdb_id=item.get("imdb_id"))
    if blacklist_old and old_hash:
        db.blacklist_hash(old_hash, "replaced by admin")
    return {"ok": True, "message": f"next play uses {label}"}


def season_episodes(imdb_id: str, season: int) -> list[dict]:
    """Every episode of a season Mycelium knows: present ones with their
    virtual item (token, info_hash) and wanted ones with their status."""
    with db._connect() as conn:
        present = {r["episode"]: dict(r) for r in conn.execute(
            "SELECT * FROM virtual_items WHERE imdb_id = ? AND season = ? AND episode IS NOT NULL",
            (imdb_id, season))}
    wanted = {w["episode"]: w for w in db.get_wanted_episodes_for_title(imdb_id) if w["season"] == season}
    out = []
    for ep in sorted(set(present) | set(wanted)):
        p, w = present.get(ep), wanted.get(ep)
        out.append({"episode": ep, "item": p, "info_hash": p["info_hash"] if p else None,
                    "wanted_status": w["status"] if w else None})
    return out


def _season_coverage(hashes: list[str], season: int, episodes: list[int]) -> dict[str, list[int] | None]:
    """{hash: sorted episode numbers the pack contains} from TorBox's file
    list, or None for a hash whose files could not be listed. One batched
    call; a failure leaves every hash unknown."""
    import strm_generator
    import torbox
    if not hashes:
        return {}
    try:
        listing = torbox.check_cached_files(hashes)
    except Exception as exc:
        log.warning("Season coverage lookup failed: %s", exc)
        listing = {}
    out: dict[str, list[int] | None] = {}
    for h in hashes:
        videos = strm_generator.pack_videos((listing.get(h) or {}).get("files") or [])
        if not videos or not episodes:
            out[h] = None
            continue
        out[h] = sorted(strm_generator.map_episodes_to_files(videos, season, episodes))
    return out


def swap_season(imdb_id: str, info_hash: str, season: int, blacklist_old: bool = False) -> dict:
    """Put one season pack behind every episode of a season. Episodes with a
    strm that the pack contains are swapped behind their token (file id set
    from the pack's file list); wanted episodes the pack contains are
    registered; episodes the pack lacks are left as they are and the pack
    is recorded as not containing them; a busy token is skipped. When
    TorBox cannot list the pack's files, only present episodes swap, with
    no file id, and the first play reconciles."""
    import strm_generator
    import torbox
    if not _HASH.match(info_hash or ""):
        return {"ok": False, "message": "not a valid info hash"}
    info_hash = info_hash.lower()
    req = db.get_request_by_imdb(imdb_id)
    if not req:
        return {"ok": False, "message": "unknown title"}
    eps = season_episodes(imdb_id, season)
    if not eps:
        return {"ok": False, "message": "nothing known about that season"}
    listing = _fresh_cached_candidates(imdb_id, season, None)
    if listing is None:
        try:
            listing = candidates(imdb_id, req["media_type"], season, None)
        except CandidatesUnavailable as exc:
            return {"ok": False, "message": f"scrapers unavailable: {exc}"}
    match = next((c for c in listing["candidates"] if c["info_hash"] == info_hash), None)
    if not match:
        return {"ok": False, "message": "that hash is not in the candidate list"}

    try:
        files = (torbox.check_cached_files([info_hash]).get(info_hash) or {}).get("files") or []
    except Exception as exc:
        log.warning("Season swap: file list for %s unavailable: %s", info_hash[:8], exc)
        files = []
    videos = strm_generator.pack_videos(files)
    known = bool(videos)
    mapping = strm_generator.map_episodes_to_files(videos, season, [e["episode"] for e in eps]) if known else {}
    if known and not mapping:
        return {"ok": False, "message": "that pack's files carry no episode this season matches"}

    import catbox
    magnet = f"magnet:?xt=urn:btih:{info_hash}"
    # swapped: present, moved to the pack. registered: wanted, now has a strm.
    # kept: present but the pack lacks it, keeps its release. skipped: wanted
    # and the pack lacks it, stays wanted. failed: in the pack but no strm
    # could be written. busy: token lock held by a playback.
    swapped, registered, kept, skipped, failed, busy = [], [], [], [], [], []
    old_hashes: set[str] = set()
    # Under the new pack's lock: a sibling materializing on it meanwhile
    # would reconcile a half-migrated season. catbox takes token then pack;
    # swap() bounds its token wait, so the reverse order here cannot hang.
    with catbox._pack_lock(info_hash):
        for e in eps:
            ep = e["episode"]
            item = e["item"]
            in_pack = (ep in mapping) if known else True
            if item is not None:
                if (item.get("info_hash") or "").lower() == info_hash:
                    if known and item.get("file_id") is None and ep in mapping:
                        db.update_virtual_file_id(item["token"], mapping[ep])
                    continue
                if not in_pack:
                    db.exclude_episode_hash(imdb_id, season, ep, info_hash)
                    kept.append(ep)
                    continue
                r = swap(item, match, blacklist_old=False, lock_timeout=ADMIN_LOCK_TIMEOUT_SEC)
                if not r["ok"]:
                    busy.append(ep)
                    continue
                if ep in mapping:
                    db.update_virtual_file_id(item["token"], mapping[ep])
                if item.get("info_hash"):
                    old_hashes.add(item["info_hash"].lower())
                swapped.append(ep)
            elif not known:
                continue  # wanted, contents unknown: left for the monitor
            elif in_pack:
                if strm_generator.create_lazy_episode_strm(
                    info_hash, magnet, req["title"], season, ep, imdb_id=imdb_id,
                    quality=match.get("quality"), source=match.get("source"), size_gb=match.get("size_gb"),
                    file_id=mapping.get(ep),
                ):
                    registered.append(ep)
                else:
                    failed.append(ep)
            else:
                db.exclude_episode_hash(imdb_id, season, ep, info_hash)
                skipped.append(ep)
    if registered:
        try:
            import jellyfin
            jellyfin.refresh_library()
        except Exception as exc:
            log.warning("Season swap: Jellyfin refresh failed: %s", exc)
    if blacklist_old and old_hashes:
        # Only hashes no episode of this season still plays from (kept and
        # busy episodes stay on theirs).
        still_used = {(e["info_hash"] or "").lower() for e in season_episodes(imdb_id, season) if e["info_hash"]}
        for h in old_hashes - still_used:
            db.blacklist_hash(h, "replaced by admin (season swap)")
    label = " ".join(x for x in (match.get("quality"), match.get("source")) if x) or info_hash[:8]
    eplist = lambda ns: ", ".join(f"E{n:02d}" for n in ns)  # noqa: E731
    parts = []
    if swapped:
        parts.append(f"{len(swapped)} swapped")
    if registered:
        parts.append(f"{len(registered)} registered")
    if kept:
        parts.append(f"{len(kept)} not in the pack, kept their release ({eplist(kept)})")
    if skipped:
        parts.append(f"{len(skipped)} not in the pack, still wanted ({eplist(skipped)})")
    if failed:
        parts.append(f"{len(failed)} could not be registered ({eplist(failed)})")
    if busy:
        parts.append(f"{len(busy)} busy, try again later ({eplist(busy)})")
    changed = bool(swapped or registered)
    # Episodes the pack lacks are information, not failure; a busy token or
    # a strm that could not be written is.
    ok = changed or not (failed or busy)
    summary = ", ".join(parts) or "every episode was already on this pack"
    message = f"S{season:02d}: {summary}; next play uses {label}" if changed else f"S{season:02d}: {summary}"
    db.log_activity("swapped", req["title"], f"S{season:02d} to {label} ({match.get('name') or info_hash[:8]}): {summary}",
                    ok, imdb_id=imdb_id)
    return {"ok": ok, "message": message, "swapped": swapped, "registered": registered, "kept": kept,
            "skipped": skipped, "failed": failed, "busy": busy}


def swap_by_hash(imdb_id: str, info_hash: str, season: int | None = None, episode: int | None = None,
                 blacklist_old: bool = False) -> dict:
    if season is not None and episode is None:
        return swap_season(imdb_id, info_hash, season, blacklist_old)
    if not _HASH.match(info_hash or ""):
        return {"ok": False, "message": "not a valid info hash"}
    req = db.get_request_by_imdb(imdb_id)
    if not req:
        return {"ok": False, "message": "unknown title"}
    item = find_item(imdb_id, season, episode)
    if not item:
        return {"ok": False, "message": "no file for that episode" if season is not None else "no file for this title"}
    if (item.get("info_hash") or "").lower() == info_hash.lower():
        return {"ok": False, "message": "that is already the current release"}
    listing = _fresh_cached_candidates(imdb_id, season, episode)
    if listing is None:
        try:
            listing = candidates(imdb_id, req["media_type"], season, episode)
        except CandidatesUnavailable as exc:
            return {"ok": False, "message": f"scrapers unavailable: {exc}"}
    match = next((c for c in listing["candidates"] if c["info_hash"] == info_hash.lower()), None)
    if not match:
        return {"ok": False, "message": "that hash is not in the candidate list"}
    return swap(item, match, blacklist_old, lock_timeout=ADMIN_LOCK_TIMEOUT_SEC)
