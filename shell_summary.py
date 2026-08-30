"""Data the application shell needs on every page.

The sidebar counts and the topbar TorBox pill are fetched together on every
navigation, so they are served together rather than as three round trips.
"""
import logging

import db
import torbox

log = logging.getLogger(__name__)


def _torbox_state() -> tuple[str, str]:
    """('ok' | 'degraded' | 'down', human label).

    Based on torbox.createtorrent_usage(), which reports how many
    createtorrent calls happened against the local budget (limit 60/hour).
    There is no torbox.rate_limit_status(); this is the real accessor.
    """
    usage = torbox.createtorrent_usage()
    count = usage.get("count", 0)
    limit = usage.get("limit", 60)
    degraded_threshold = limit * 0.8
    if count >= limit:
        return "down", "TorBox rate limited"
    if count >= degraded_threshold:
        return "degraded", "TorBox near its limit"
    return "ok", "TorBox online"


def _counts(user_id: int | None) -> dict:
    """watchlist and requests are per-user; with no user_id they are always 0
    rather than leaking an all-users total. wanted stays global."""
    return {
        "watchlist": len(db.get_watchlist(user_id)) if user_id is not None else 0,
        "requests": len(db.get_user_requests(user_id=user_id, status="pending")) if user_id is not None else 0,
        "wanted": len([w for w in db.get_all_wanted_episodes() if w["status"] == "wanted"]),
    }


def get_shell_summary(user_id: int | None = None) -> dict:
    """Sidebar counts and the topbar TorBox pill."""
    try:
        counts = _counts(user_id)
    except Exception as exc:
        # The counts are the point of this endpoint, but a db hiccup must not
        # 500 the whole shell. Fall back to the empty-install shape.
        log.warning("shell summary: counts unavailable: %s", exc)
        counts = {"watchlist": 0, "requests": 0, "wanted": 0}

    try:
        state, label = _torbox_state()
    except Exception as exc:
        # The counts are the point of this endpoint. A TorBox outage must not
        # take the navigation down with it.
        log.warning("shell summary: torbox state unavailable: %s", exc)
        state, label = "down", "TorBox unreachable"

    return {"counts": counts, "torbox": {"state": state, "label": label}}
