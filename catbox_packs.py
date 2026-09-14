"""Season-pack reconciliation and episode detach/search, split out of
catbox.py so the play path stays lean. Imports catbox at module level for
the private state it shares with the play path (_pack_lock,
invalidate_url_cache, _content_key, db); catbox.py reaches back into this
module only through a lazy import at the call site in _materialize_locked,
so it cannot import catbox_packs at module level without deadlocking the
import.
"""
import logging
import re
import threading
from datetime import datetime

import catbox

log = logging.getLogger(__name__)


def reconcile_pack_files(token: str, item: dict, live: dict) -> int | None:
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
    with catbox._pack_lock(item["info_hash"]):
        return _reconcile_pack(token, item, season, videos)


def _reconcile_pack(token: str, item: dict, season, videos: list) -> int | None:
    import strm_generator
    siblings = [s for s in catbox.db.get_virtual_items_by_hash(item["info_hash"])
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
            catbox.db.update_virtual_file_id(s["token"], fid)
    unmatched = [s for s in siblings if s["token"] not in matched]
    if unmatched:
        log.warning("Catbox: %s S%02d pack %s has no file for %s; detaching them back to wanted. Files: %s",
                    item.get("title"), season, item["info_hash"][:8],
                    ", ".join(f"E{s['episode']:02d}" for s in sorted(unmatched, key=lambda s: s["episode"])),
                    "; ".join((f.get("name") or "").rsplit("/", 1)[-1] for f in videos))
        to_search = []
        for s in unmatched:
            status, title = detach_episode(s)
            if status == "wanted" and s.get("imdb_id"):
                to_search.append({"imdb_id": s["imdb_id"], "title": title,
                                  "season": season, "episode": s["episode"]})
        if to_search:
            _start_detached_search(to_search)
    return matched.get(token)


def detach_episode(vi: dict) -> tuple[str, str]:
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
    catbox.db.delete_virtual_item(token)
    catbox.invalidate_url_cache(token)
    ckey = catbox._content_key(vi)
    if ckey:
        try:
            catbox.db.reset_playability_state(ckey)
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
    title = series_title(vi.get("title") or "")
    if imdb_id:
        req = catbox.db.get_request_by_imdb(imdb_id) or {}
        # The virtual item's title carries the episode suffix ("Show S04E04");
        # a wanted row with that title would search and file under a folder
        # of that name. Prefer the request title, else strip the suffix.
        title = req.get("title") or series_title(vi.get("title") or "") or imdb_id
        season, episode = vi["season"], vi["episode"]
        catbox.db.upsert_wanted_episode(imdb_id, req.get("tmdb_id"), title, season, episode, None)
        row = catbox.db.get_wanted_episode(imdb_id, season, episode) or {}
        if row.get("title") and _EP_SUFFIX_RE.search(row["title"]):
            # An existing row seeded by 0.25.2 with the item title.
            catbox.db.set_wanted_episode_title(imdb_id, season, episode, title)
        air_date = row.get("air_date")
        if air_date and air_date > datetime.now().date().isoformat():
            status = "not_aired"
        catbox.db.mark_episode_status(imdb_id, season, episode, status)
        if vi.get("info_hash"):
            catbox.db.exclude_episode_hash(imdb_id, season, episode, vi["info_hash"])
    log.info("Catbox: detached S%02dE%02d of %s (token %s) back to %s",
             vi["season"], vi["episode"], vi.get("title"), token, status)
    return status, title


_EP_SUFFIX_RE = re.compile(r"\s+S\d{1,2}E\d{1,3}\s*$", re.IGNORECASE)


def series_title(item_title: str) -> str:
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
