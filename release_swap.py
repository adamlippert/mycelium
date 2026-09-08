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

    try:
        found = scrapers.merge_candidates(media_type, imdb_id, season, episode, raise_if_inconclusive=True)
    except scrapers.ScrapersUnavailable as exc:
        raise CandidatesUnavailable(str(exc) or exc.__class__.__name__) from exc

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

    kept, verdicts = streams.rank_streams_explained(found, override=db.get_show_override(imdb_id))
    verdict_of = {s.info_hash.lower(): v for s, v in zip(found, verdicts)}

    try:
        cached = {h.lower() for h in debrid.check_cached_multi([s.info_hash for s in found]).get("torbox", set())}
    except Exception as exc:
        log.warning("Cache check failed for %s candidates: %s", imdb_id, exc)
        cached = set()

    item = find_item(imdb_id, season, episode)
    current_hash = item["info_hash"].lower() if item else ""

    kept_hashes = {s.info_hash.lower() for s in kept}
    dropped = [s for s in found if s.info_hash.lower() not in kept_hashes]
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
    Both must be given together or both absent, otherwise invalid."""
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
    if (s is None) != (e is None):
        return None
    return (s, e)


def swap(item: dict, candidate: dict, blacklist_old: bool = False, action: str = "swapped") -> dict:
    """Put candidate's hash behind item's token. Nothing on disk changes.

    action names the activity-log event: the admin panel logs "swapped", the
    catbox auto-upgrader shares this same function but logs "upgraded", so
    both paths get identical side effects without identical labels."""
    import catbox
    old_hash = (item.get("info_hash") or "").lower()
    old_quality = item.get("quality") or "?"
    new_hash = candidate["info_hash"].lower()
    magnet = f"magnet:?xt=urn:btih:{new_hash}"
    with catbox._token_lock(item["token"]):
        db.update_virtual_item_upgrade(item["token"], new_hash, magnet, candidate.get("quality"), candidate.get("source"))
        db.update_virtual_rd_id(item["token"], None)
        catbox.invalidate_url_cache(item["token"])
        _drop_faststart_cache(item["token"])
        key = catbox._content_key(item)
        if key:
            db.reset_playability_state(key)
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


def swap_by_hash(imdb_id: str, info_hash: str, season: int | None = None, episode: int | None = None,
                 blacklist_old: bool = False) -> dict:
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
    return swap(item, match, blacklist_old)
