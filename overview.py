"""The aggregated admin Overview payload: everything the database and
in-memory state can answer in one call. Service pings and the TorBox
list stay on their own endpoints because they call other services.

Every block is built through _safe() so one failing source (a scraper
registry error, a TorBox usage query) leaves the rest of the page
usable; the failed block shows its neutral default.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

import db

log = logging.getLogger(__name__)

CACHE_TTL_SEC = 30
_cache: dict = {"data": None, "ts": 0.0}
_lock = threading.Lock()

# library_sync.orphans() is a full media-tree walk plus a full table load;
# it does not need to be fresher than a few minutes. Cached separately from
# the rest of the payload so it stays off the 30 s path.
ORPHANS_CACHE_TTL_SEC = 300
_orphans_cache: dict = {"data": None, "ts": None}


def _safe(fn, default, name: str | None = None, errors: list[str] | None = None):
    """Run fn(), returning default on any exception.

    name/errors are given by build() for the eight named blocks the
    frontend can distinguish from a real figure ("unavailable" instead of a
    plausible zero); a call without a name (an inner helper, not a
    top-level block) just logs at debug, as before."""
    try:
        return fn()
    except Exception as exc:
        if name:
            log.warning("overview block failed: %s: %s", name, exc)
            if errors is not None and name not in errors:
                errors.append(name)
        else:
            log.debug("overview block failed: %s", exc)
        return default


def _cached_orphans() -> dict:
    import library_sync
    now = time.monotonic()
    ts = _orphans_cache["ts"]
    if _orphans_cache["data"] is not None and ts is not None and now - ts < ORPHANS_CACHE_TTL_SEC:
        return _orphans_cache["data"]
    data = library_sync.orphans()
    _orphans_cache["data"] = data
    _orphans_cache["ts"] = time.monotonic()
    return data


def _scrapers() -> list[dict]:
    import scrapers
    # probe=False: the Overview poll must never make an outbound HTTP call.
    # A scraper without in-memory latency samples reports the cached probe
    # result (or "unknown" when nothing fresh is cached) instead of
    # triggering a live probe.
    return [{"name": r["name"], "state": r["state"], "latency_ms": r.get("latency_ms")}
            for r in scrapers.health_rows(probe=False)]


def _torbox_adds() -> dict:
    import torbox
    u = torbox.createtorrent_usage()
    return {"uncached": int(u.get("count", 0)), "cached": int(u.get("cached_count", 0) or 0),
            "limit": int(u.get("limit", 60) or 60), "resets_in_sec": int(u.get("resets_in_sec", 0) or 0)}


def _approvals() -> dict:
    import requests_admin
    return {"pending": int(requests_admin.view_counts().get("pending", 0)),
            "oldest_age_sec": db.oldest_pending_user_request_age_sec()}


def _attention() -> int:
    import library_admin
    return int(library_admin.view_count("attention"))


def _consistency() -> dict:
    orphans = _safe(_cached_orphans, {"db_count": 0, "strm_without_db": 0, "db_without_strm": 0})
    mirrored, total = db.count_requests_mirrored()
    last = db.get_last_cleanup_run()
    return {"db_items": int(orphans.get("db_count", 0)),
            "strm_without_db": int(orphans.get("strm_without_db", 0)),
            "db_without_strm": int(orphans.get("db_without_strm", 0)),
            "arr_mirrored": mirrored, "arr_total": total,
            "last_cleanup": ({"ran_at": last["ran_at"], "deleted": int(last.get("deleted", 0))} if last else None)}


_BASE_DEFAULT = {
    "library": {"movie_count": 0, "episode_count": 0, "series_count": 0},
    "requests": {"total": 0, "succeeded_7d": 0, "failed_7d": 0, "success_rate_7d": 0.0},
    "wanted": {"active": 0, "found": 0, "give_up": 0},
    "movies_pending": 0,
    "egress_bytes_month": 0,
    "egress_estimated_bytes_month": 0,
    "qualities": {},
}
_PLAY_COUNTS_DEFAULT = {"plays": 0, "titles": 0}


def build() -> dict:
    import egress_estimate
    import stats
    import torbox
    errors: list[str] = []
    # The 60 s cache stats.get_overview() sits behind, not the uncached
    # media-tree walk (_build_overview): three full tree walks plus six
    # heavy view-count queries every 30 s is the cost this call avoids.
    base = _safe(stats.get_overview, _BASE_DEFAULT, name="base", errors=errors)
    today = _safe(lambda: db.play_counts(0), _PLAY_COUNTS_DEFAULT, name="plays", errors=errors)
    week = _safe(lambda: db.play_counts(7), _PLAY_COUNTS_DEFAULT, name="plays", errors=errors)
    last_429 = _safe(torbox.last_429_at, None, name="last_429", errors=errors)
    failed_7d = int(base["requests"]["failed_7d"])
    succeeded_7d = int(base["requests"]["succeeded_7d"])
    wanted_active = int(base["wanted"]["active"])
    return {
        "status": {
            "scrapers": _safe(_scrapers, [], name="scrapers", errors=errors),
            "torbox_adds": _safe(_torbox_adds, {"uncached": 0, "cached": 0, "limit": 60, "resets_in_sec": 0},
                                  name="torbox_adds", errors=errors),
            "failures_7d": failed_7d,
            "queue": {"retry": len(_safe(db.get_pending_retries, [])), "wanted": wanted_active},
            "attention": _safe(_attention, 0, name="attention", errors=errors),
            "approvals": _safe(_approvals, {"pending": 0, "oldest_age_sec": None}, name="approvals", errors=errors),
        },
        "activity": {
            "plays": {"today": today["plays"], "week": week["plays"],
                      "titles_today": today["titles"], "titles_week": week["titles"]},
            "requests_7d": {"total": succeeded_7d + failed_7d,
                            "succeeded": succeeded_7d, "failed": failed_7d,
                            "success_rate": base["requests"]["success_rate_7d"]},
            "egress": {"proxied_bytes": base["egress_bytes_month"],
                       "estimated_bytes": base["egress_estimated_bytes_month"]},
        },
        "library": {
            "movies": base["library"]["movie_count"],
            "episodes": base["library"]["episode_count"],
            "series": base["library"]["series_count"],
            "wanted": wanted_active,
            "upcoming": int(base.get("movies_pending", 0)),
            "qualities": base["qualities"],
            "consistency": _safe(_consistency, {"db_items": 0, "strm_without_db": 0, "db_without_strm": 0,
                                                 "arr_mirrored": 0, "arr_total": 0, "last_cleanup": None},
                                  name="consistency", errors=errors),
        },
        "torbox": {
            "recent_streams": egress_estimate.recent(900),
            "last_429_at": (datetime.fromtimestamp(last_429, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                            if last_429 else None),
        },
        "errors": errors,
    }


def get(force: bool = False) -> dict:
    now = time.monotonic()
    if not force and _cache["data"] is not None and now - _cache["ts"] < CACHE_TTL_SEC:
        return _cache["data"]
    with _lock:
        now = time.monotonic()
        if not force and _cache["data"] is not None and now - _cache["ts"] < CACHE_TTL_SEC:
            return _cache["data"]
        data = build()
        _cache["data"] = data
        _cache["ts"] = time.monotonic()
        return data
