"""Single entry point for candidate discovery across every scraper.

Order in _SCRAPERS is priority. All enabled, healthy scrapers are queried
concurrently, then merged in priority order (NOT completion order) so dedup is
deterministic: the highest-priority source keeps the stream and the others are
recorded in also_seen_in.
"""
import concurrent.futures
import logging

import debridio
import health_cache
import settings as _settings
import torrentio
import zilean
from streams import Stream, rank_streams

log = logging.getLogger(__name__)


def _fetch_debridio(media_type, imdb_id, season, episode):
    return debridio.fetch(media_type, imdb_id, season, episode)


def _fetch_zilean(media_type, imdb_id, season, episode):
    # zilean.fetch_streams takes no media_type.
    return zilean.fetch_streams(imdb_id, season=season, episode=episode)


def _fetch_torrentio(media_type, imdb_id, season, episode):
    kind = "movie" if media_type == "movie" else "series"
    return torrentio.fetch_streams(kind, imdb_id, season=season, episode=episode)


# (name, settings key or None if always on, fetch adapter)
_SCRAPERS = [
    ("debridio", "DEBRIDIO_ENABLED", _fetch_debridio),
    ("zilean", "ZILEAN_ENABLED", _fetch_zilean),
    ("torrentio", None, _fetch_torrentio),
]


def _active() -> list[tuple]:
    out = []
    for name, key, fn in _SCRAPERS:
        if key is not None and not _settings.get(key, False):
            continue
        if not health_cache.is_up(name):
            log.debug("Scraper %s skipped: reported down", name)
            continue
        out.append((name, fn))
    return out


def fetch_candidates(media_type: str, imdb_id: str, season: int | None = None,
                     episode: int | None = None, *, prefer_season_pack: bool = False,
                     override: dict | None = None) -> list[Stream]:
    """Fetch, merge, dedup and rank candidates from every active scraper."""
    active = _active()
    if not active:
        log.warning("No scrapers active for %s", imdb_id)
        return []

    results: dict[str, list[Stream]] = {name: [] for name, _ in active}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(active)) as ex:
        futures = {ex.submit(fn, media_type, imdb_id, season, episode): name
                   for name, fn in active}
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result() or []
            except Exception as exc:
                log.warning("Scraper %s failed for %s: %s", name, imdb_id, exc)

    merged: list[Stream] = []
    by_hash: dict[str, Stream] = {}
    for name, _ in active:                       # priority order, not completion
        for stream in results[name]:
            if not stream.info_hash:
                continue
            existing = by_hash.get(stream.info_hash)
            if existing is None:
                by_hash[stream.info_hash] = stream
                merged.append(stream)
            elif name not in existing.also_seen_in and name != existing.source:
                existing.also_seen_in = existing.also_seen_in + (name,)

    log.info("Candidates for %s: %s -> %d unique",
             imdb_id, {n: len(results[n]) for n, _ in active}, len(merged))
    return rank_streams(merged, prefer_season_pack=prefer_season_pack, override=override)
