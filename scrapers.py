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
import scraper_metrics
import settings as _settings
import torrentio
import zilean
from streams import Stream, rank_streams

log = logging.getLogger(__name__)


class ScrapersUnavailable(Exception):
    """No scraper could be searched at all.

    Raised only when the caller asks for it (raise_if_inconclusive=True) and
    either nothing was active, or something failed AND nothing was found. A
    partial failure that still produced candidates is not inconclusive - it
    proceeds normally. It never means "found nothing" -- a successful search
    with no results is still an empty list. Callers that delete files on an
    empty result must tell the two apart or a ten-minute upstream outage looks
    like a library full of dead titles.
    """


def _fetch_debridio(media_type, imdb_id, season, episode, timeout=None):
    # raise_on_error=True: Debridio's adapter documents "never raises,
    # returns [] on failure", which would otherwise hide its failures from
    # the `failed` count below and defeat the outage guard entirely.
    if timeout is None:
        return debridio.fetch(media_type, imdb_id, season, episode, raise_on_error=True)
    return debridio.fetch(media_type, imdb_id, season, episode, timeout=timeout,
                          raise_on_error=True)


def _fetch_zilean(media_type, imdb_id, season, episode, timeout=None):
    # zilean.fetch_streams takes no media_type. raise_on_error=True for the
    # same reason as _fetch_debridio above - Zilean fails open too.
    if timeout is None:
        return zilean.fetch_streams(imdb_id, season=season, episode=episode,
                                    raise_on_error=True)
    return zilean.fetch_streams(imdb_id, season=season, episode=episode, timeout=timeout,
                                raise_on_error=True)


def _fetch_torrentio(media_type, imdb_id, season, episode, timeout=None):
    kind = "movie" if media_type == "movie" else "series"
    if timeout is None:
        return torrentio.fetch_streams(kind, imdb_id, season=season, episode=episode)
    return torrentio.fetch_streams(kind, imdb_id, season=season, episode=episode,
                                   timeout=timeout)


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


def merge_candidates(media_type: str, imdb_id: str, season: int | None = None,
                     episode: int | None = None, *, raise_if_inconclusive: bool = False,
                     timeout: int | None = None) -> list[Stream]:
    """Fetch, merge and dedup candidates from every active scraper, UNRANKED.

    Callers that want the house ranking use fetch_candidates(); this half
    exists for the web player, which applies its own browser-compatibility
    ordering to the raw pool and would silently narrow it by ranking first.
    """
    active = _active()
    if not active:
        log.warning("No scrapers active for %s", imdb_id)
        if raise_if_inconclusive:
            raise ScrapersUnavailable("no scraper is enabled and healthy")
        return []

    results: dict[str, list[Stream]] = {name: [] for name, _ in active}
    failed = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(active)) as ex:
        futures = {ex.submit(scraper_metrics.timed(name, fn),
                             media_type, imdb_id, season, episode, timeout): name
                   for name, fn in active}
        for future in concurrent.futures.as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result() or []
            except Exception as exc:
                failed += 1
                log.warning("Scraper %s failed for %s: %s",
                            name, imdb_id, debridio.redact(exc))

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

    # Evaluated AFTER the merge: a partial failure that still produced
    # candidates is not inconclusive - incomplete information must never
    # authorise a caller that deletes files, but if something WAS found the
    # repair is valid and must proceed.
    if raise_if_inconclusive and failed and not merged:
        raise ScrapersUnavailable(
            f"{failed} of {len(active)} active scraper(s) failed and nothing was found")

    log.info("Candidates for %s: %s -> %d unique",
             imdb_id, {n: len(results[n]) for n, _ in active}, len(merged))
    return merged


def fetch_candidates(media_type: str, imdb_id: str, season: int | None = None,
                     episode: int | None = None, *, prefer_season_pack: bool = False,
                     override: dict | None = None,
                     raise_if_inconclusive: bool = False) -> list[Stream]:
    """Fetch, merge, dedup and rank candidates from every active scraper.

    raise_if_inconclusive=True turns "could not search" into
    ScrapersUnavailable instead of an empty list; leave it off unless an empty
    result would make the caller destroy something.
    """
    merged = merge_candidates(media_type, imdb_id, season, episode,
                              raise_if_inconclusive=raise_if_inconclusive)
    return rank_streams(merged, prefer_season_pack=prefer_season_pack, override=override)
