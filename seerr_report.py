"""Report request outcomes back to Seerr.

Seerr shows "Processing" from approval until something says otherwise. It
learns about success on its own eventually (its Jellyfin scan), learns
about removal only when its availability sync runs (hours), and never
learns about failure. This closes all three: success is reported at once,
a terminal failure declines the request so the person can re-request, a
title wanted for longer than SEERR_DECLINE_WANTED_AFTER_DAYS is declined
once while Mycelium keeps searching, and a purge removes Seerr's media
record so the title is requestable again immediately.

A title is found in Seerr by its TMDB id first (/movie/{tmdb}, /tv/{tmdb});
that works for titles requested before Mycelium stored Seerr request ids,
for series, and for titles that entered through Mycelium's own Discover
page but also exist in Seerr. The Seerr request id on file is the fallback.
Every function is best-effort and never raises.
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


def _lookup(imdb_id: str, tmdb_id: int | None, media_type: str | None) -> dict | None:
    """seerr.find_media() for the title, filling the TMDB id and media type
    from the request row when the caller did not have them."""
    if not tmdb_id or not media_type:
        try:
            row = db.get_request_by_imdb(imdb_id) or {}
        except Exception as exc:
            log.debug("seerr_report: request row lookup for %s failed: %s", imdb_id, exc)
            row = {}
        tmdb_id = tmdb_id or row.get("tmdb_id")
        media_type = media_type or row.get("media_type")
    if not tmdb_id:
        return None
    try:
        return seerr.find_media(tmdb_id, media_type or "movie")
    except Exception as exc:
        log.debug("seerr_report: Seerr lookup of tmdb %s failed: %s", tmdb_id, exc)
        return None


def _media_id(imdb_id: str, tmdb_id: int | None, media_type: str | None) -> int | None:
    found = _lookup(imdb_id, tmdb_id, media_type)
    if found:
        return found["media_id"]
    rid = _request_id(imdb_id)
    if not rid:
        return None
    try:
        return (seerr.get_request(rid).get("media") or {}).get("id")
    except Exception as exc:
        log.debug("seerr_report: Seerr request %s lookup failed: %s", rid, exc)
        return None


def _open_requests(imdb_id: str, tmdb_id: int | None, media_type: str | None) -> list[int]:
    found = _lookup(imdb_id, tmdb_id, media_type)
    if found:
        return found["request_ids"]
    rid = _request_id(imdb_id)
    return [rid] if rid else []


def on_success(imdb_id: str, tmdb_id: int | None = None, media_type: str | None = None) -> bool:
    if not _enabled():
        return False
    media_id = _media_id(imdb_id, tmdb_id, media_type)
    if not media_id:
        return False
    try:
        ok = seerr.set_media_status_by_id(media_id, "available")
    except Exception as exc:
        log.warning("seerr_report: could not mark %s available: %s", imdb_id, exc)
        return False
    if ok:
        log.info("Seerr: media %s (%s) marked available", media_id, imdb_id)
    return ok


def on_failed(imdb_id: str, reason: str, tmdb_id: int | None = None,
              media_type: str | None = None) -> bool:
    """Decline every open Seerr request for the title. True if any was."""
    if not _enabled():
        return False
    declined = 0
    for rid in _open_requests(imdb_id, tmdb_id, media_type):
        try:
            if seerr.decline_request(rid):
                declined += 1
                log.info("Seerr: request %s (%s) declined: %s", rid, imdb_id, reason)
        except Exception as exc:
            log.warning("seerr_report: could not decline request %s for %s: %s", rid, imdb_id, exc)
    if declined:
        try:
            db.clear_webhook_events(imdb_id)
        except Exception as exc:
            log.debug("seerr_report: clearing webhook dedup keys for %s failed: %s", imdb_id, exc)
    return declined > 0


def on_purged(imdb_id: str, tmdb_id: int | None = None, media_type: str | None = None) -> bool:
    """The title was removed from the library: delete Seerr's media record.

    Seerr would otherwise keep showing it Available until its availability
    sync runs, hours later, and nobody could re-request it in the meantime.
    The "deleted" media status looked like the gentler option but Seerr
    3.4.1 ignores it; DELETE /media is what its own "clear media data"
    button does. Not called by the Delete button, which keeps the files."""
    if not _enabled():
        return False
    media_id = _media_id(imdb_id, tmdb_id, media_type)
    if not media_id:
        return False
    try:
        ok = seerr.delete_media(media_id)
    except Exception as exc:
        log.warning("seerr_report: could not delete Seerr media for %s: %s", imdb_id, exc)
        return False
    if ok:
        log.info("Seerr: media %s (%s) removed after purge", media_id, imdb_id)
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
        imdb_id, tmdb_id = row["imdb_id"], row.get("tmdb_id")
        if not _open_requests(imdb_id, tmdb_id, "movie"):
            # Seerr has nothing open for it: nothing to report, so mark it
            # done rather than re-scanning the same row on every sweep.
            db.mark_wanted_seerr_reported(imdb_id)
            continue
        if on_failed(imdb_id, f"no acceptable release after {days} days", tmdb_id, "movie"):
            declined += 1
            db.mark_wanted_seerr_reported(imdb_id)
        # Otherwise leave seerr_reported = 0: a Seerr outage today should not
        # stop the decline from being retried on the next sweep.
    return declined
