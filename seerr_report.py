"""Report request outcomes back to Seerr.

Seerr shows "Processing" from approval until something says otherwise. It
learns about success on its own eventually (its Jellyfin scan), and never
learns about failure. This closes both: success is reported at once, a
terminal failure declines the request so the person can re-request, and a
title that has been wanted for longer than SEERR_DECLINE_WANTED_AFTER_DAYS
is declined once while Mycelium keeps searching.

Only titles that came in through Seerr have a request id; everything else
is skipped silently. Every function is best-effort and never raises.
"""
import logging

import db
import seerr

log = logging.getLogger(__name__)


def _enabled() -> bool:
    # Imported locally, not at module level: see seerr._seerr_url's docstring.
    import settings
    return bool(settings.get("SEERR_REPORT_STATUS", True)) and seerr.is_configured()


def _request_id(imdb_id: str) -> int | None:
    try:
        return db.get_seerr_request_id(imdb_id)
    except Exception as exc:
        log.debug("seerr_report: lookup of %s failed: %s", imdb_id, exc)
        return None


def on_success(imdb_id: str) -> bool:
    if not _enabled():
        return False
    rid = _request_id(imdb_id)
    if not rid:
        return False
    try:
        ok = seerr.set_media_status(rid, "available")
    except Exception as exc:
        log.warning("seerr_report: could not mark %s available: %s", imdb_id, exc)
        return False
    if ok:
        log.info("Seerr: request %s (%s) marked available", rid, imdb_id)
    return ok


def on_failed(imdb_id: str, reason: str) -> bool:
    if not _enabled():
        return False
    rid = _request_id(imdb_id)
    if not rid:
        return False
    try:
        ok = seerr.decline_request(rid)
    except Exception as exc:
        log.warning("seerr_report: could not decline %s: %s", imdb_id, exc)
        return False
    if ok:
        log.info("Seerr: request %s (%s) declined: %s", rid, imdb_id, reason)
    return ok


def report_stale_wanted() -> int:
    """Decline, once, every wanted movie older than the configured cutoff."""
    if not _enabled():
        return 0
    import settings
    days = int(settings.get("SEERR_DECLINE_WANTED_AFTER_DAYS", 30) or 0)
    if days <= 0:
        return 0
    declined = 0
    for row in db.get_stale_wanted_movies(days):
        rid = _request_id(row["imdb_id"])
        if rid is None:
            # No Seerr id, ever: nothing to report, so mark it done rather
            # than re-scanning the same unreportable row on every sweep.
            db.mark_wanted_seerr_reported(row["imdb_id"])
            continue
        if on_failed(row["imdb_id"], f"no acceptable release after {days} days"):
            declined += 1
            db.mark_wanted_seerr_reported(row["imdb_id"])
        # Otherwise leave seerr_reported = 0: a Seerr outage today should not
        # stop the decline from being retried on the next sweep.
    return declined
