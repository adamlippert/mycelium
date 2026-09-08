"""Pick another release for a movie or one episode.

candidates() is the list the processor saw, with each candidate's rule
verdict and TorBox cache state, so the admin Library drawer can offer a
manual swap when the auto-picked release turns out to be wrong.
"""
from __future__ import annotations

import logging

import db

log = logging.getLogger(__name__)

# Display label for each release_tags.detect_sources() value. Anything not
# listed here falls back to an upper-cased copy of the raw tag.
_SOURCE_LABELS = {
    "remux": "REMUX",
    "bluray": "BluRay",
    "bdrip": "BDRip",
    "brrip": "BRRip",
    "webdl": "WEB-DL",
    "webrip": "WEBRip",
    "web": "WEB",
    "hdrip": "HDRip",
    "dvdrip": "DVDRip",
    "dvd": "DVD",
    "hdtv": "HDTV",
    "satrip": "SATRip",
    "tvrip": "TVRip",
    "r5": "R5",
    "ppvrip": "PPVRip",
    "ts": "TS",
    "tc": "TC",
    "scr": "SCR",
    "cam": "CAM",
    "workprint": "Workprint",
}


class CandidatesUnavailable(Exception):
    """The scrapers could not answer; the caller can offer Retry."""


def find_item(imdb_id: str, season: int | None = None, episode: int | None = None) -> dict | None:
    if season is not None and episode is not None:
        return db.get_virtual_item_by_episode(imdb_id, season, episode)
    items = db.get_virtual_items_by_imdb(imdb_id, media_type="movie")
    return items[0] if items else None


def _release_source(name: str) -> str | None:
    import release_tags
    found = release_tags.detect_sources(name or "")
    if not found:
        return None
    return _SOURCE_LABELS.get(found[0], found[0].upper())


def _row(s, verdict, cached: set[str], current_hash: str) -> dict:
    return {
        "info_hash": s.info_hash.lower(), "name": s.name, "quality": s.quality,
        "source": _release_source(s.name), "size_gb": s.size_gb, "seeders": s.seeders,
        "languages": list(s.languages), "cached": s.info_hash.lower() in cached,
        "scrapers": [s.source, *s.also_seen_in], "kept": verdict.kept,
        "rule": None if verdict.kept else verdict.rule, "value": None if verdict.kept else verdict.value,
        "current": s.info_hash.lower() == current_hash,
    }


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

    # current.source is the candidate row's release-type label, not the raw
    # virtual_items.source DB value (which holds the scraper name, not a
    # release-type tag); null when the current hash isn't among the found
    # candidates at all.
    current = None
    if item:
        current_row = next((r for r in rows if r["current"]), None)
        current = {"info_hash": current_hash, "quality": item.get("quality"),
                   "source": current_row["source"] if current_row else None}

    return {"current": current, "candidates": rows}
