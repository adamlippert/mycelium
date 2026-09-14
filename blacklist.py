import logging

import db
import settings

log = logging.getLogger(__name__)


def _threshold() -> int:
    return settings.get("BLACKLIST_FAIL_THRESHOLD", 3)


def is_blacklisted(info_hash: str) -> bool:
    rec = db.get_failed_hash(info_hash)
    return bool(rec and rec["fail_count"] >= _threshold())


def record_failure(info_hash: str, error: str | None = None) -> None:
    db.record_failed_hash(info_hash, error)
    try:
        import metrics_prom
        metrics_prom.blacklist_failures_total.inc()
    except Exception:
        pass
    rec = db.get_failed_hash(info_hash)
    if rec and rec["fail_count"] >= _threshold():
        log.warning("Hash %s now blacklisted (%d failures)", info_hash, rec["fail_count"])


def filter_candidates(candidates: list) -> list:
    """Remove blacklisted hashes from a candidate list."""
    if not candidates:
        return candidates
    blacklisted = db.get_blacklisted_hashes(_threshold())
    if not blacklisted:
        return candidates
    filtered = [c for c in candidates if c.info_hash not in blacklisted]
    if len(filtered) < len(candidates):
        log.info("Filtered %d blacklisted candidate(s)", len(candidates) - len(filtered))
    return filtered


def filter_for_episode(candidates: list, imdb_id: str | None, season, episode) -> list:
    """Drop releases recorded as not containing this episode (a season pack
    that turned out to be partial, see catbox_packs.detach_episode). Season packs
    sort first, so without this the same pack would win every search for
    the episode and loop with the detach on the next play."""
    if not candidates or not imdb_id or not season or not episode:
        return candidates
    excluded = db.excluded_hashes_for(imdb_id, season, episode)
    if not excluded:
        return candidates
    filtered = [c for c in candidates if (c.info_hash or "").lower() not in excluded]
    if len(filtered) < len(candidates):
        log.info("%s S%02dE%02d: skipped %d release(s) known not to contain the episode",
                 imdb_id, season, episode, len(candidates) - len(filtered))
    return filtered
