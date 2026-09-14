"""Catbox-style lazy materialization for TorBox.

When CATBOX_MODE is enabled, .strm files contain a proxy URL pointing to
/stream/<token>. On playback the webhook ensures the torrent is in TorBox
(re-adding from the cached magnet if it has been released), fetches a fresh
CDN URL, and 307-redirects the client.

After CATBOX_IDLE_MINUTES of inactivity an item is removed from TorBox to
stay within TorBox's 30-day cache retention policy. The virtual entry stays
in the DB so playback works again on the next request.

Resolved CDN URLs are cached in-memory per token to avoid hammering TorBox's
60/hour createtorrent + 300/min general rate limits when Jellyfin sends
multiple probe/seek requests for the same item in quick succession.
"""
import logging
import re
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

import db
import settings as _settings
import torbox
from config import CATBOX_HOST, CATBOX_IDLE_MINUTES as _CATBOX_IDLE_MINUTES_DEFAULT

log = logging.getLogger(__name__)


# TorBox's requestdl opens a returned link for 3 hours; after that a new
# connection against it is refused, though a transfer already in flight
# continues. Cache inside that window with headroom, so a cached entry is
# never dead on arrival. The liveness check below stays as the backstop for
# links that die early.
_URL_CACHE_TTL_SEC = 9000  # 2.5 hours
ON_PLAY_READY_TIMEOUT_SEC = 45  # max wait on-play before giving up (cached = seconds)
_url_cache: dict[str, tuple[str, float]] = {}
_url_cache_lock = threading.Lock()


def _home(item: dict) -> int:
    """The account holding the item's torrent; until Task 3 homes items
    properly, an unhomed item uses the first enabled account."""
    import torbox_pool
    return item.get("torbox_account") or torbox_pool.accounts()[0].id

# Failure cooldown: after a failed materialize (429, timeout, no file found),
# block retries for a short window so Jellyfin's burst of probe requests doesn't
# hammer TorBox with repeated createtorrent calls.
_FAIL_COOLDOWN_SEC = 30        # standard failure (readd blocked, no file)
_FAIL_COOLDOWN_429_SEC = 120   # TorBox 429  -  back off longer
_fail_cache: dict[str, float] = {}  # token → expiry monotonic timestamp
_fail_cache_lock = threading.Lock()

# ── Reason codes (structured, for playability_state + admin UI) ───────────────
REASON_UNKNOWN_TOKEN    = "UNKNOWN_TOKEN"
REASON_NO_IMDB          = "NO_IMDB"
REASON_TORRENTIO_EMPTY  = "TORRENTIO_EMPTY"
REASON_NO_CACHED        = "NO_CACHED_RELEASE"
REASON_WAIT_TIMEOUT     = "WAIT_TIMEOUT"
REASON_NO_FILE          = "NO_FILE"
REASON_RD_429           = "RD_429"
REASON_TB_429           = "TB_429"
REASON_ADD_FAILED       = "ADD_FAILED"
REASON_SEARCH_ERROR     = "SEARCH_UNAVAILABLE"

def _fail_get(token: str) -> bool:
    with _fail_cache_lock:
        exp = _fail_cache.get(token)
        if exp is None:
            return False
        if exp > time.monotonic():
            return True
        del _fail_cache[token]
        return False

def _fail_put(token: str, ttl: int = _FAIL_COOLDOWN_SEC) -> None:
    with _fail_cache_lock:
        _fail_cache[token] = time.monotonic() + ttl

_token_locks: dict[str, threading.Lock] = {}

# Per-content search cache so Zilean/Torrentio are called at most once per hour
# for the same (imdb_id, season, episode) combo, regardless of how many tokens share it.
_search_cache: dict[tuple, tuple[float, object]] = {}  # key → (expiry, result)
_search_cache_lock = threading.Lock()
_SEARCH_HIT_TTL    = 300    # 5 min: re-check soon if a cached release was found
_SEARCH_MISS_TTL   = 21600  # 6 h:  nothing cached  -  back off (matches _fail_put below)
_token_locks_lock = threading.Lock()
_pack_locks: dict[str, threading.Lock] = {}

# ── scan/probe burst detection ────────────────────────────────────────────────
# A media-server library scan opens many DISTINCT .strm URLs in a short burst,
# whereas real playback touches a single token (plus seeks on that same token).
# When we see a burst of distinct tokens we treat the requests as scan probes and
# refuse to re-add idle-released torrents  -  re-materializing the whole library on
# every scan is slow and churns TorBox's createtorrent quota. Items already live
# in TorBox still resolve cheaply (mylist is cached), so they probe fine.
_SCAN_WINDOW_SEC = 25
# Deliberately above this deployment's realistic concurrent-user count (a
# handful of real users, see CLAUDE.md) so several people starting different
# titles within the same 25s window isn't misread as a library scan and
# denied re-add. A real scan opens far more than this many distinct items.
_SCAN_DISTINCT_THRESHOLD = 8
_recent_tokens: dict[str, float] = {}
_recent_lock = threading.Lock()


def _is_scan_burst(token: str) -> bool:
    """Record this token request and report whether we appear to be inside a
    library-scan burst (many distinct tokens within the recent window)."""
    now = time.monotonic()
    with _recent_lock:
        for t, ts in list(_recent_tokens.items()):
            if now - ts > _SCAN_WINDOW_SEC:
                del _recent_tokens[t]
        _recent_tokens[token] = now
        return len(_recent_tokens) >= _SCAN_DISTINCT_THRESHOLD


def _token_lock(token: str) -> threading.Lock:
    with _token_locks_lock:
        lock = _token_locks.get(token)
        if lock is None:
            lock = threading.Lock()
            _token_locks[token] = lock
        return lock


def _resolve_pack_files(token: str, item: dict, live: dict) -> int | None:
    """Match every episode of this pack (same hash and season) to a file
    now that TorBox has listed the files, and return the file id for
    `token`, or None when its episode is not in the pack.

    Matching is by name (strm_generator.episode_matches); when no name
    matches at all and the pack holds exactly one video file per
    registered episode, sorted names map onto sorted episode numbers.
    An episode with no file is detached: its .strm and virtual item go,
    Jellyfin is told, and it returns to the wanted list so the monitor
    searches for it on its own. That replaces the old fallback to the
    largest file, which played episode 2 for every missing episode.

    An empty files list (the single-item endpoint sometimes omits it)
    changes nothing: no match and no detaching."""
    import strm_generator
    videos = strm_generator.pack_videos(live.get("files") or [])
    if not videos:
        return None
    season = item.get("season")
    # Only the playing token's lock is held here; a sibling episode of the
    # same pack materializing at the same moment would reconcile the same
    # siblings, detach them twice and start a second search. One pack at a
    # time; the second caller then sees the detached rows already gone.
    with _pack_lock(item["info_hash"]):
        return _reconcile_pack(token, item, season, videos)


def _pack_lock(info_hash: str) -> threading.Lock:
    with _token_locks_lock:
        lock = _pack_locks.get(info_hash)
        if lock is None:
            lock = threading.Lock()
            _pack_locks[info_hash] = lock
        return lock


def _reconcile_pack(token: str, item: dict, season, videos: list) -> int | None:
    import strm_generator
    siblings = [s for s in db.get_virtual_items_by_hash(item["info_hash"])
                if s.get("season") == season and s.get("episode")]
    if not any(s["token"] == token for s in siblings):
        siblings.append(item)
    by_episode = strm_generator.map_episodes_to_files(videos, season, [s["episode"] for s in siblings])
    matched = {s["token"]: by_episode[s["episode"]] for s in siblings if s["episode"] in by_episode}
    if matched and not any(strm_generator.episode_matches(f.get("name") or "", season, s["episode"])
                           for s in siblings for f in videos):
        log.info("Catbox: %s S%02d pack %s: no episode tags in the file names, mapped %d files by order",
                 item.get("title"), season, item["info_hash"][:8], len(matched))
    for s in siblings:
        fid = matched.get(s["token"])
        if fid is not None and s.get("file_id") != fid:
            db.update_virtual_file_id(s["token"], fid)
    unmatched = [s for s in siblings if s["token"] not in matched]
    if unmatched:
        log.warning("Catbox: %s S%02d pack %s has no file for %s; detaching them back to wanted. Files: %s",
                    item.get("title"), season, item["info_hash"][:8],
                    ", ".join(f"E{s['episode']:02d}" for s in sorted(unmatched, key=lambda s: s["episode"])),
                    "; ".join((f.get("name") or "").rsplit("/", 1)[-1] for f in videos))
        to_search = []
        for s in unmatched:
            status, title = _detach_episode(s)
            if status == "wanted" and s.get("imdb_id"):
                to_search.append({"imdb_id": s["imdb_id"], "title": title,
                                  "season": season, "episode": s["episode"]})
        if to_search:
            _start_detached_search(to_search)
    return matched.get(token)


def _detach_episode(vi: dict) -> tuple[str, str]:
    """Remove an episode that its pack does not contain and put it back on
    the wanted list, so the monitor searches for it as its own torrent."""
    import os
    token = vi["token"]
    strm_path = vi.get("strm_path") or ""
    for path in (strm_path, strm_path[:-5] + ".nfo" if strm_path.endswith(".strm") else ""):
        if path:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
            except OSError as exc:
                log.warning("Catbox: could not remove %s: %s", path, exc)
    db.delete_virtual_item(token)
    invalidate_url_cache(token)
    ckey = _content_key(vi)
    if ckey:
        try:
            db.reset_playability_state(ckey)
        except Exception as exc:
            log.debug("Catbox: playability reset skipped for %s: %s", ckey, exc)
    if strm_path:
        try:
            import jellyfin
            jellyfin.note_change(strm_path, "Deleted")
        except Exception as exc:
            log.debug("Catbox: Jellyfin note skipped for %s: %s", strm_path, exc)
    imdb_id = vi.get("imdb_id")
    status = "wanted"
    title = _series_title(vi.get("title") or "")
    if imdb_id:
        req = db.get_request_by_imdb(imdb_id) or {}
        # The virtual item's title carries the episode suffix ("Show S04E04");
        # a wanted row with that title would search and file under a folder
        # of that name. Prefer the request title, else strip the suffix.
        title = req.get("title") or _series_title(vi.get("title") or "") or imdb_id
        season, episode = vi["season"], vi["episode"]
        db.upsert_wanted_episode(imdb_id, req.get("tmdb_id"), title, season, episode, None)
        row = db.get_wanted_episode(imdb_id, season, episode) or {}
        if row.get("title") and _EP_SUFFIX_RE.search(row["title"]):
            # An existing row seeded by 0.25.2 with the item title.
            db.set_wanted_episode_title(imdb_id, season, episode, title)
        air_date = row.get("air_date")
        if air_date and air_date > datetime.now().date().isoformat():
            status = "not_aired"
        db.mark_episode_status(imdb_id, season, episode, status)
        if vi.get("info_hash"):
            db.exclude_episode_hash(imdb_id, season, episode, vi["info_hash"])
    log.info("Catbox: detached S%02dE%02d of %s (token %s) back to %s",
             vi["season"], vi["episode"], vi.get("title"), token, status)
    return status, title


_EP_SUFFIX_RE = re.compile(r"\s+S\d{1,2}E\d{1,3}\s*$", re.IGNORECASE)


def _series_title(item_title: str) -> str:
    return _EP_SUFFIX_RE.sub("", item_title or "").strip()


def _start_detached_search(episodes: list[dict]) -> None:
    """Seam for tests; production starts the search on a daemon thread."""
    threading.Thread(target=_search_detached, args=(episodes,), daemon=True,
                     name="detached-search").start()


def _search_detached(episodes: list[dict]) -> None:
    """Search each detached episode right away instead of waiting for the
    next monitor run. Runs on its own thread, off the play request; every
    failure is logged, none reaches the player."""
    import monitor
    for ep in episodes:
        try:
            monitor.search_episode_now(ep["imdb_id"], ep["title"], ep["season"], ep["episode"])
        except Exception as exc:
            log.warning("Catbox: immediate search for %s S%02dE%02d failed: %s",
                        ep["title"], ep["season"], ep["episode"], exc)


def _content_key(item: dict) -> str | None:
    imdb_id = item.get("imdb_id")
    if not imdb_id:
        return None
    season, episode = item.get("season"), item.get("episode")
    if season and episode:
        return f"{imdb_id}:S{season:02d}E{episode:02d}"
    return imdb_id


_TOUCH_DEBOUNCE_SEC = 60  # last_played/play_count precision we actually need
_touch_cache: dict[str, float] = {}
_touch_cache_lock = threading.Lock()


def _touch_debounced(token: str) -> None:
    """db.touch_virtual_item() writes (UPDATE + commit) on every call. The two
    cache-hit call sites in materialize() run on every single byte-range
    request during active playback -- one player can trigger dozens of these
    a minute, each a synchronous SQLite write serializing against every other
    concurrent playback session's writes. play_count/last_played don't need
    per-chunk precision, so only actually write once per debounce window."""
    now = time.monotonic()
    with _touch_cache_lock:
        last = _touch_cache.get(token)
        if last is not None and now - last < _TOUCH_DEBOUNCE_SEC:
            return
        _touch_cache[token] = now
    db.touch_virtual_item(token)


def _cache_get(token: str) -> str | None:
    with _url_cache_lock:
        entry = _url_cache.get(token)
        if entry and entry[1] > time.monotonic():
            return entry[0]
        if entry:
            del _url_cache[token]
    return None


def _cache_put(token: str, url: str) -> None:
    with _url_cache_lock:
        _url_cache[token] = (url, time.monotonic() + _URL_CACHE_TTL_SEC)


def cache_url(token: str, url: str) -> None:
    """Store a CDN URL in the in-memory cache (used by preload)."""
    _cache_put(token, url)


def invalidate_url_cache(token: str | None = None) -> None:
    with _url_cache_lock:
        if token is None:
            _url_cache.clear()
        else:
            _url_cache.pop(token, None)


def catbox_host() -> str:
    """Externally reachable host for the .strm proxy URL. Settings DB first,
    env/config fallback. Must be reachable from Jellyfin."""
    return (_settings.get("CATBOX_HOST", CATBOX_HOST) or "").strip()


def proxy_url(token: str) -> str:
    return f"{catbox_host().rstrip('/')}/stream/{token}"


def register(info_hash: str, magnet: str, title: str, media_type: str,
             strm_path: str | None = None, torbox_id: int | None = None,
             file_id: int | None = None, imdb_id: str | None = None,
             quality: str | None = None, source: str | None = None,
             size_gb: float | None = None, season: int | None = None,
             episode: int | None = None, year: int | None = None) -> str:
    token = uuid.uuid4().hex[:16]
    db.insert_virtual_item(token, info_hash, magnet, title, media_type,
                            strm_path=strm_path, torbox_id=torbox_id, file_id=file_id,
                            imdb_id=imdb_id, quality=quality, source=source,
                            size_gb=size_gb, season=season, episode=episode, year=year)
    return token


def materialize(token: str, allow_readd: bool | None = None) -> str | None:
    """Ensure the torrent is in TorBox and return a fresh stream URL.
    Cached URLs are served for up to _URL_CACHE_TTL_SEC (2.5 hours, inside
    TorBox's 3 hour link window) to absorb Jellyfin's probe/seek bursts
    without spending TorBox createtorrent rate-limit slots.

    allow_readd controls whether an idle-released torrent may be re-added (which
    can block ~45s waiting for it to become ready). When None (default), it is
    auto-decided: during a scan-burst we skip the re-add so the scan stays fast.
    """
    cached = _cache_get(token)
    if cached:
        _touch_debounced(token)
        return cached

    # Respect failure cooldown  -  don't spam TorBox after a recent failed attempt.
    if _fail_get(token):
        return None

    if allow_readd is None:
        allow_readd = not _is_scan_burst(token)

    with _token_lock(token):
        # Re-check inside the lock: another thread may have succeeded or set cooldown.
        cached = _cache_get(token)
        if cached:
            _touch_debounced(token)
            return cached
        if _fail_get(token):
            return None
        url = _materialize_locked(token, allow_readd=allow_readd)
        if url:
            _cache_put(token, url)
            _schedule_next_episode_preload(token)
        else:
            _fail_put(token)
        return url


def _rd_get_url(item: dict, rd_id: str) -> str | None:
    """Get a playable URL from RealDebrid for this virtual item."""
    import re as _re
    import realdebrid as _rd
    if item["media_type"] == "movie":
        return _rd.get_main_video_url(rd_id)
    # Episode: match SxxExx in filename
    pairs = _rd.get_video_files_with_urls(rd_id)
    if not pairs:
        return None
    s_num, e_num = item.get("season"), item.get("episode")
    if s_num and e_num:
        ep_re = _re.compile(rf'[Ss]0?{s_num}[Ee]0?{e_num}\b', _re.IGNORECASE)
        matched = [(f, u) for f, u in pairs if ep_re.search(f.get("path") or f.get("name") or "")]
        if matched:
            return matched[0][1]
    return max(pairs, key=lambda fu: fu[0].get("bytes") or 0)[1]


def _materialize_locked(token: str, allow_readd: bool = True) -> str | None:
    item = db.get_virtual_item(token)
    if not item:
        log.warning("Catbox: unknown token %s", token)
        _metrics_inc("failed")
        return None

    ckey = _content_key(item)
    debrid_provider = (item.get("debrid_provider") or "torbox").lower()
    rematerialized = False

    # ── RealDebrid path ───────────────────────────────────────────────────────
    if debrid_provider == "realdebrid":
        import realdebrid as _rd
        rd_id = item.get("rd_id")

        # Fast path: rd_id still live in RD library
        if rd_id:
            info = _rd.get_info(rd_id)
            if info and info.get("status") == "downloaded":
                url = _rd_get_url(item, rd_id)
                if url:
                    db.touch_virtual_item(token)
                    if ckey:
                        db.update_playability_ok(ckey, "realdebrid")
                    _metrics_inc("ok" if not rematerialized else "rematerialized")
                    return url
            log.info("Catbox/RD: %s no longer in RD library  -  will re-add", item["title"])
            db.update_virtual_rd_id(token, None)
            rd_id = None
            rematerialized = True

        if not allow_readd:
            log.debug("Catbox/RD: skipping re-add for %s during scan-burst probe", item["title"])
            return None

        rematerialized = True
        log.info("Catbox/RD: searching cached release for %s", item["title"])
        fresh = _search_cached_release(item)
        if fresh is _SEARCH_UNAVAILABLE:
            _fail_put(token, _FAIL_COOLDOWN_SEC)
            if ckey:
                db.update_playability_fail(ckey, REASON_SEARCH_ERROR)
            return None
        if not fresh:
            log.error("Catbox/RD: no cached release for %s  -  keeping .strm, retry in 6h",
                      item["title"])
            _fail_put(token, 21600)  # 6h  -  repair job will clean up if truly dead
            if ckey:
                db.update_playability_fail(ckey, REASON_NO_CACHED)
            return None

        new_hash, new_magnet, provider = fresh
        db.update_virtual_item_upgrade(token, new_hash, new_magnet, None, None)
        db.update_virtual_debrid_provider(token, provider)
        if provider == "torbox":
            # Search found TorBox  -  fall through to TorBox block below
            debrid_provider = "torbox"
            item["debrid_provider"] = "torbox"
            item["info_hash"] = new_hash
            item["file_id"] = None
        else:
            try:
                result = _rd.add_magnet(new_magnet)
                rd_id = result["id"]
                rd_info = _rd.wait_until_ready(rd_id, timeout=ON_PLAY_READY_TIMEOUT_SEC)
                if not rd_info:
                    log.error("Catbox/RD: wait_until_ready timed out for %s", item["title"])
                    _fail_put(token, _FAIL_COOLDOWN_SEC)
                    if ckey:
                        db.update_playability_fail(ckey, REASON_WAIT_TIMEOUT)
                    return None
                db.update_virtual_rd_id(token, rd_id)
                url = _rd_get_url(item, rd_id)
                if url:
                    db.touch_virtual_item(token)
                    if ckey:
                        db.update_playability_ok(ckey, "realdebrid")
                    _metrics_inc("rematerialized")
                return url
            except Exception as exc:
                is_429 = "429" in str(exc)
                log.error("Catbox/RD: add_magnet failed for %s: %s", item["title"], exc)
                _fail_put(token, _FAIL_COOLDOWN_429_SEC if is_429 else _FAIL_COOLDOWN_SEC)
                if ckey:
                    db.update_playability_fail(ckey, REASON_RD_429 if is_429 else REASON_ADD_FAILED)
                return None

    # ── TorBox path ───────────────────────────────────────────────────────────
    torbox_id = item["torbox_id"]
    acct = _home(item)

    # Fast path: cached torbox_id still live in TorBox.
    if torbox_id:
        live = torbox.find_by_id(acct, torbox_id)
        if not live or not torbox._is_ready(live):
            torbox_id = None
            rematerialized = True

    # Second chance: torrent may still be in TorBox library under its hash.
    if not torbox_id and item.get("info_hash"):
        existing = torbox.find_by_hash(acct, item["info_hash"])
        if existing and torbox._is_ready(existing):
            torbox_id = existing["id"]
            db.set_virtual_torbox(token, torbox_id, acct)
            log.info("Catbox: %s still in library (id=%s)  -  no re-add needed",
                     item["title"], torbox_id)

    # Third chance: use the stored magnet to add directly  -  covers both items that
    # previously had a torbox_id (fell out of mylist top-1000) and freshly lazy-
    # registered items (torbox_id=NULL, magnet already selected at request time).
    if not torbox_id and item.get("magnet") and allow_readd:
        try:
            log.info("Catbox: %s adding stored magnet", item["title"])
            added = torbox.add_magnet(acct, item["magnet"], reason="catbox-readd")
            _tid = added.get("id") or added.get("torrent_id")
            existing = added if _tid and torbox._is_ready(added) else (
                torbox.find_by_id(acct, _tid) if _tid else
                torbox.find_by_hash(acct, item["info_hash"], force_refresh=True)
            )
            if not (existing and torbox._is_ready(existing)) and _tid:
                existing = torbox.wait_until_ready(
                    acct, item["info_hash"], timeout=ON_PLAY_READY_TIMEOUT_SEC, torrent_id=_tid)
            if existing and torbox._is_ready(existing):
                torbox_id = existing["id"]
                db.set_virtual_torbox(token, torbox_id, acct)
                log.info("Catbox: %s added via stored magnet (id=%s)", item["title"], torbox_id)
        except Exception as exc:
            exc_str = str(exc)
            is_rate_limited = (isinstance(exc, torbox.RateLimited)
                               or "429" in exc_str or "403" in exc_str)
            log.warning("Catbox: stored-magnet re-add failed for %s: %s", item["title"], exc)
            if is_rate_limited:
                # 429 = rate limited; 403 = API key/plan issue  -  either way
                # there is no point continuing to checkcached, it will also fail.
                _fail_put(token, _FAIL_COOLDOWN_429_SEC)
                if ckey:
                    db.update_playability_fail(ckey, REASON_TB_429)
                return None

    # Fourth chance: known hash may be cached on RD even if TorBox doesn't have it.
    # This avoids a full Torrentio search for items where Torrentio returns 0 results.
    if not torbox_id and item.get("info_hash") and allow_readd:
        try:
            import realdebrid as _rd
            if _rd.is_configured():
                known_hash = item["info_hash"].lower()
                rd_instant = _rd.check_cached([known_hash])
                if known_hash in {h.lower() for h in rd_instant}:
                    log.info("Catbox: known hash cached on RD for %s  -  switching to RD path",
                             item["title"])
                    db.update_virtual_debrid_provider(token, "realdebrid")
                    magnet = item.get("magnet") or f"magnet:?xt=urn:btih:{known_hash}"
                    rd_result = _rd.add_magnet(magnet)
                    rd_id = rd_result["id"]
                    rd_info = _rd.wait_until_ready(rd_id, timeout=ON_PLAY_READY_TIMEOUT_SEC)
                    if rd_info:
                        db.update_virtual_rd_id(token, rd_id)
                        url = _rd_get_url(item, rd_id)
                        if url:
                            db.touch_virtual_item(token)
                            if ckey:
                                db.update_playability_ok(ckey, "realdebrid")
                            _metrics_inc("rematerialized")
                            return url
                    log.error("Catbox: RD wait_until_ready timed out for %s", item["title"])
                    _fail_put(token, _FAIL_COOLDOWN_SEC)
                    if ckey:
                        db.update_playability_fail(ckey, REASON_WAIT_TIMEOUT)
                    return None
        except Exception as exc:
            log.warning("Catbox: RD known-hash check failed for %s: %s", item["title"], exc)

    if not torbox_id and not allow_readd:
        log.debug("Catbox: skipping re-add for %s during scan-burst probe", item["title"])
        return None

    if not torbox_id:
        rematerialized = True
        log.info("Catbox: searching fresh cached release for %s", item["title"])
        fresh = _search_cached_release(item)
        if fresh is _SEARCH_UNAVAILABLE:
            _fail_put(token, _FAIL_COOLDOWN_SEC)
            if ckey:
                db.update_playability_fail(ckey, REASON_SEARCH_ERROR)
            return None
        if not fresh:
            log.error("Catbox: no cached release found for %s  -  keeping .strm, retry in 6h",
                      item["title"])
            _fail_put(token, 21600)  # 6h  -  repair job will clean up if truly dead
            if ckey:
                db.update_playability_fail(ckey, REASON_NO_CACHED)
            return None

        new_hash, new_magnet, provider = fresh
        db.update_virtual_debrid_provider(token, provider)
        if provider == "realdebrid":
            # Search found RD  -  switch provider and handle via RD
            import realdebrid as _rd
            db.update_virtual_item_upgrade(token, new_hash, new_magnet, None, None)
            try:
                result = _rd.add_magnet(new_magnet)
                rd_id = result["id"]
                rd_info = _rd.wait_until_ready(rd_id, timeout=ON_PLAY_READY_TIMEOUT_SEC)
                if not rd_info:
                    _fail_put(token, _FAIL_COOLDOWN_SEC)
                    if ckey:
                        db.update_playability_fail(ckey, REASON_WAIT_TIMEOUT)
                    return None
                db.update_virtual_rd_id(token, rd_id)
                item["rd_id"] = rd_id
                url = _rd_get_url(item, rd_id)
                if url:
                    db.touch_virtual_item(token)
                    if ckey:
                        db.update_playability_ok(ckey, "realdebrid")
                    _metrics_inc("rematerialized")
                return url
            except Exception as exc:
                is_429 = "429" in str(exc)
                log.error("Catbox: RD add_magnet failed for %s: %s", item["title"], exc)
                _fail_put(token, _FAIL_COOLDOWN_429_SEC if is_429 else _FAIL_COOLDOWN_SEC)
                if ckey:
                    db.update_playability_fail(ckey, REASON_RD_429 if is_429 else REASON_ADD_FAILED)
                return None

        if new_hash != (item.get("info_hash") or "").lower():
            log.info("Catbox: swapping hash %s → %s", item["title"], new_hash)
            db.update_virtual_item_upgrade(token, new_hash, new_magnet, None, None)
            item["info_hash"] = new_hash
            item["file_id"] = None

        try:
            added = torbox.add_magnet(acct, new_magnet, reason="catbox-search", cached=True)
            # Use the ID from the add response to avoid a full mylist refresh.
            # TorBox returns "torrent_id" for cached adds, "id" for others.
            _tid = added.get("id") or added.get("torrent_id")
            live = added if _tid and torbox._is_ready(added) else None
            if not live:
                live = torbox.find_by_id(acct, _tid) if _tid else None
            if not live or not torbox._is_ready(live):
                live = torbox.wait_until_ready(
                    acct, new_hash, timeout=ON_PLAY_READY_TIMEOUT_SEC, torrent_id=_tid or None)
            if not live:
                log.error("Catbox: fresh release not ready for %s  -  keeping .strm, retry soon",
                          item["title"])
                _fail_put(token, _FAIL_COOLDOWN_SEC)
                if ckey:
                    db.update_playability_fail(ckey, REASON_WAIT_TIMEOUT)
                return None
            torbox_id = live["id"]
            db.set_virtual_torbox(token, torbox_id, acct)
        except Exception as exc:
            is_429 = "429" in str(exc)
            log.error("Catbox: add_magnet failed for %s: %s", token, exc)
            _fail_put(token, _FAIL_COOLDOWN_429_SEC if is_429 else _FAIL_COOLDOWN_SEC)
            if ckey:
                db.update_playability_fail(ckey, REASON_TB_429 if is_429 else REASON_ADD_FAILED)
            return None

    file_id = item["file_id"]
    is_episode = item["media_type"] != "movie" and item.get("season") and item.get("episode")
    if file_id is not None and is_episode and db.hash_has_duplicate_file_ids(item["info_hash"]):
        # Two episodes of this pack point at one file: the old largest-file
        # fallback. Match the pack's files again for the whole season.
        file_id = None
    # TorBox file ids start at 0, so a preset 0 is a known file, not "unknown":
    # `if not file_id` sent the first episode of every pack through the
    # listing again and failed the play when the ?id= endpoint omitted files.
    if file_id is None:
        live = torbox.find_by_id(acct, torbox_id)
        if live:
            import strm_generator
            if item["media_type"] == "movie":
                main = strm_generator._pick_main_movie_file(live.get("files") or [])
                if main:
                    file_id = main["id"]
                    db.update_virtual_file_id(token, file_id)
                elif not (live.get("files")):
                    # TorBox returned the torrent without a files list (common for the
                    # ?id= single-item endpoint).  Use file_id=0 which tells TorBox to
                    # serve the largest file automatically  -  works for single-file movies.
                    log.info("Catbox: no files list for %s  -  using file_id=0 (auto)", item["title"])
                    file_id = 0
            elif is_episode:
                file_id = _resolve_pack_files(token, item, live)
            else:
                videos = [f for f in (live.get("files") or [])
                          if strm_generator._is_video(f.get("name") or "")
                          and not strm_generator._is_trailer(f)]
                main = max(videos, key=lambda f: f.get("size") or 0) if videos else None
                if main:
                    file_id = main["id"]
                    db.update_virtual_file_id(token, file_id)

    if file_id is None or (not file_id and file_id != 0):
        log.error("Catbox: no playable file found for %s  -  keeping .strm, retry later", token)
        _fail_put(token, _FAIL_COOLDOWN_SEC)
        if ckey:
            db.update_playability_fail(ckey, REASON_NO_FILE)
        return None

    import strm_generator
    url = torbox.request_download_link(acct, torbox_id, file_id)
    if url:
        db.touch_virtual_item(token)
        if ckey:
            db.update_playability_ok(ckey, "torbox")
        _metrics_inc("rematerialized" if rematerialized else "ok")
    else:
        _metrics_inc("failed")
    return url


def _metrics_inc(result: str) -> None:
    try:
        import metrics_prom
        metrics_prom.catbox_stream_total.labels(result=result).inc()
    except Exception:
        pass


def _remove_strm(item: dict) -> None:
    """Delete the .strm file for a definitively dead item so Jellyfin stops showing it."""
    import os
    strm_path = item.get("strm_path")
    if not strm_path:
        return
    try:
        if os.path.exists(strm_path):
            os.remove(strm_path)
            log.info("Catbox: removed dead .strm %s", strm_path)
    except Exception as exc:
        log.warning("Catbox: could not remove .strm %s: %s", strm_path, exc)


_SEARCH_UNAVAILABLE = object()  # sentinel: search couldn't run (no imdb_id, network error)


def _search_cached_release(item: dict) -> object:
    """Thin cache layer around _search_best_cached_release.

    Deduplicates Zilean/Torrentio calls when multiple tokens share the same
    (imdb_id, season, episode).  A miss is cached for 6 h, a hit for 5 min
    (so a newly-cached release is picked up quickly on retry).
    """
    imdb_id = item.get("imdb_id")
    if not imdb_id:
        # No imdb_id → _search_best_cached_release will handle + log the warning.
        return _search_best_cached_release(item)
    key = (imdb_id, item.get("season"), item.get("episode"))
    now = time.monotonic()
    with _search_cache_lock:
        entry = _search_cache.get(key)
        if entry and entry[0] > now:
            result = entry[1]
            log.debug("Catbox search cache hit for %s %s  -  skipping Zilean/Torrentio",
                      imdb_id, key[1:])
            return result
    result = _search_best_cached_release(item)
    if result is _SEARCH_UNAVAILABLE:
        # Don't cache the outage sentinel: the token's own retry cooldown is
        # _FAIL_COOLDOWN_SEC (30s), but caching it here would fall through to
        # _SEARCH_MISS_TTL (6h) below, same as a real miss - the title would
        # not be re-searched again until long after any real outage ended.
        return result
    ttl = _SEARCH_HIT_TTL if result else _SEARCH_MISS_TTL
    with _search_cache_lock:
        _search_cache[key] = (now + ttl, result)
    return result


def _search_best_cached_release(item: dict) -> tuple[str, str] | None | object:
    """Search Torrentio for the best currently-cached release for this item.

    Returns:
      (info_hash, magnet)   -  found a cached release
      None                  -  searched OK, nothing cached right now
      _SEARCH_UNAVAILABLE   -  couldn't search (no imdb_id, network error)  -  do NOT remove .strm
    """
    imdb_id = item.get("imdb_id")
    if not imdb_id:
        # Try to resolve imdb_id from TMDB using title + year, then persist it.
        try:
            import tmdb as _tmdb
            kind = "movie" if item.get("media_type") == "movie" else "tv"
            title = item.get("title") or ""
            year = item.get("year")
            results = _tmdb._get("/search/" + ("movie" if kind == "movie" else "tv"),
                                  params={"query": title, "year": year or ""}) or {}
            hits = results.get("results") or []
            if hits:
                tmdb_id = hits[0]["id"]
                imdb_id = _tmdb.tmdb_to_imdb(tmdb_id, media_type=kind)
                if imdb_id:
                    db.update_virtual_item_imdb(item["token"], imdb_id)
                    log.info("Catbox search: resolved imdb_id %s for %s via TMDB",
                             imdb_id, title)
        except Exception as exc:
            log.warning("Catbox search: TMDB lookup failed for %s: %s", item.get("title"), exc)
    if not imdb_id:
        log.warning("Catbox search: no imdb_id for %s  -  keeping .strm, will retry later",
                    item["title"])
        return _SEARCH_UNAVAILABLE
    try:
        import scrapers
        import debrid
        import blacklist
        media_type = item["media_type"]
        season = item.get("season")
        episode = item.get("episode")

        try:
            ranked = scrapers.fetch_candidates(
                "movie" if media_type == "movie" else "series",
                imdb_id, season=season, episode=episode,
                raise_if_inconclusive=True,
            )
        except scrapers.ScrapersUnavailable as exc:
            # "Could not search" is not "nothing is cached": the caller backs
            # off 6h on a real miss, which would outlive the outage by hours.
            log.warning("Catbox search: no scraper could be searched for %s (%s)"
                        "  -  keeping .strm", item.get("title"), exc)
            return _SEARCH_UNAVAILABLE
        if not ranked:
            return None
        ranked = blacklist.filter_candidates(ranked)
        if media_type != "movie":
            ranked = blacklist.filter_for_episode(ranked, imdb_id, season, episode)
        log.info("Catbox search: %d candidate(s) after ranking/filter for %s",
                 len(ranked), item.get("title"))
        if not ranked:
            return None
        hashes = [s.info_hash for s in ranked]
        cache_results = debrid.check_cached_multi(hashes)
        rd_cached = cache_results.get("realdebrid", set())
        tb_cached = cache_results.get("torbox", set())
        log.info("Catbox search: RD=%d TB=%d cached out of %d for %s",
                 len(rd_cached), len(tb_cached), len(ranked), item.get("title"))
        # RD first, TorBox fallback
        for s in ranked:
            if s.info_hash in rd_cached:
                return s.info_hash.lower(), s.magnet, "realdebrid"
        for s in ranked:
            if s.info_hash in tb_cached:
                return s.info_hash.lower(), s.magnet, "torbox"
        return None
    except Exception as exc:
        log.warning("Catbox search: failed for %s: %s  -  keeping .strm", item["title"], exc)
        return _SEARCH_UNAVAILABLE


def _schedule_next_episode_preload(token: str) -> None:
    """After a series episode materializes successfully, preload the next episode
    in background so it is instant when the user gets there.

    Lookup order: same season episode+1, then season+1 episode 1.
    Only fires if CATBOX_PRELOAD is enabled and the next episode has a
    registered virtual_item with info_hash + magnet."""
    try:
        import settings as _s
        import config as _cfg
        if not _s.get("CATBOX_PRELOAD", _cfg.CATBOX_PRELOAD):
            return
        item = db.get_virtual_item(token)
        if not item or item.get("media_type") != "series":
            return
        imdb_id = item.get("imdb_id")
        season = item.get("season")
        episode = item.get("episode")
        if not (imdb_id and season and episode):
            return
        # Try next episode in same season, then first episode of the next season
        nxt = db.get_virtual_item_by_episode(imdb_id, season, episode + 1)
        if not nxt:
            nxt = db.get_virtual_item_by_episode(imdb_id, season + 1, 1)
        if not nxt:
            return
        next_hash = nxt.get("info_hash")
        next_magnet = nxt.get("magnet")
        next_title = nxt.get("title") or ""
        if not (next_hash and next_magnet):
            return
        import strm_generator as _sg
        import threading as _t
        _t.Thread(
            target=_sg._preload_torrent,
            args=(next_hash, next_magnet, next_title),
            daemon=True,
        ).start()
        log.debug("Catbox: scheduled preload for next episode %s", next_title)
    except Exception as exc:
        log.debug("Catbox: next-episode preload scheduling failed: %s", exc)


def _sweep_caches() -> None:
    """Prune expired entries from the in-memory caches that are only cleaned
    on read (_url_cache, _fail_cache, _search_cache) or on next scan-burst
    check (_recent_tokens). A token that's cached once and never queried
    again would otherwise sit in memory forever on a long-running instance.

    _token_locks is deliberately NOT swept here: a lock object can be handed
    out to a caller and acquired moments after this check finds it free,
    so deleting it here could let two callers end up serialized on two
    different Lock objects for the same token instead of one - a real
    correctness bug, not just a leak. Left as a known, harmless memory growth."""
    now_mono = time.monotonic()

    with _url_cache_lock:
        for t in [t for t, (_, exp) in _url_cache.items() if exp <= now_mono]:
            del _url_cache[t]

    with _fail_cache_lock:
        for t in [t for t, exp in _fail_cache.items() if exp <= now_mono]:
            del _fail_cache[t]

    with _touch_cache_lock:
        for t in [t for t, ts in _touch_cache.items() if now_mono - ts > _TOUCH_DEBOUNCE_SEC]:
            del _touch_cache[t]

    with _search_cache_lock:
        for k in [k for k, (exp, _) in _search_cache.items() if exp <= now_mono]:
            del _search_cache[k]

    with _recent_lock:
        for t in [t for t, ts in _recent_tokens.items() if now_mono - ts > _SCAN_WINDOW_SEC]:
            del _recent_tokens[t]


_last_reconcile: dict | None = None
_reconcile_lock = threading.Lock()


def last_reconcile() -> dict | None:
    """The most recent reconcile_torbox_ids() result, or None since start."""
    with _reconcile_lock:
        return dict(_last_reconcile) if _last_reconcile else None


def reconcile_torbox_ids() -> dict:
    """Compare stored TorBox ids with TorBox's own list. An id whose torrent
    is gone (deleted in the TorBox app, expired) is cleared so the next play
    re-adds cleanly instead of discovering the loss first; when the same
    hash lives under another id the item is pointed at that one. Never
    deletes anything on TorBox. An empty list is treated as an outage and
    changes nothing: it would otherwise clear every id at once."""
    result = {"ran_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
              "checked": 0, "cleared": 0, "repointed": 0, "skipped": None}
    items = db.get_virtual_items_with_torbox_id()
    result["checked"] = len(items)
    if items:
        live_by_account: dict[int, list | None] = {}

        def _live_for(acct_id: int):
            if acct_id not in live_by_account:
                try:
                    live_by_account[acct_id] = torbox.list_torrents(acct_id, force_refresh=True)
                except Exception as exc:
                    log.warning("Catbox: TorBox id reconcile skipped for account %s, list unavailable: %s",
                                acct_id, exc)
                    live_by_account[acct_id] = None
            return live_by_account[acct_id]

        any_live = False
        for item in items:
            acct_id = _home(item)
            live = _live_for(acct_id)
            if not live:
                continue
            any_live = True
            live_ids = {t.get("id") for t in live}
            by_hash = {(t.get("hash") or "").lower(): t.get("id") for t in live if t.get("hash")}
            if item["torbox_id"] in live_ids:
                continue
            if _token_lock(item["token"]).locked():
                continue  # a play is materializing it right now
            other = by_hash.get((item.get("info_hash") or "").lower())
            if other is not None:
                db.set_virtual_torbox(item["token"], other, acct_id)
                result["repointed"] += 1
                log.info("Catbox: %s (%s) now under TorBox id %s, was %s",
                         item.get("title"), item["token"], other, item["torbox_id"])
            else:
                db.set_virtual_torbox(item["token"], None, None)
                invalidate_url_cache(item["token"])
                result["cleared"] += 1
                log.info("Catbox: TorBox id %s for %s (%s) is gone; cleared, next play re-adds",
                         item["torbox_id"], item.get("title"), item["token"])
        if not any_live:
            result["skipped"] = "TorBox list empty or unavailable"
        elif result["cleared"] or result["repointed"]:
            log.info("Catbox: TorBox id reconcile: %d checked, %d cleared, %d repointed",
                     result["checked"], result["cleared"], result["repointed"])
    global _last_reconcile
    with _reconcile_lock:
        _last_reconcile = result
    return result


def release_idle() -> int:
    """Remove TorBox items idle longer than CATBOX_IDLE_MINUTES. Returns count released."""
    _sweep_caches()
    idle_minutes = _settings.get("CATBOX_IDLE_MINUTES", _CATBOX_IDLE_MINUTES_DEFAULT)
    cutoff = datetime.utcnow() - timedelta(minutes=idle_minutes)
    cutoff_iso = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    items = db.get_idle_virtual_items(cutoff_iso)
    released = 0
    for item in items:
        try:
            acct = _home(item)
            deleted = torbox.delete_torrent(acct, item["torbox_id"])
            if not deleted:
                # Torrent may already be gone from TorBox (evicted or manually removed).
                # Still clear the local reference so catbox can re-add it on next play.
                still_there = torbox.find_by_id(acct, item["torbox_id"])
                if still_there:
                    continue
            db.update_virtual_torbox_id(item["token"], None)
            log.info("Catbox: released idle torrent %s (%s)", item["torbox_id"], item["title"])
            released += 1
        except Exception as exc:
            log.warning("Catbox: failed to release idle torrent %s (%s): %s",
                        item["torbox_id"], item.get("title"), exc)
    if released:
        log.info("Catbox: released %d idle torrent(s)", released)
    return released
