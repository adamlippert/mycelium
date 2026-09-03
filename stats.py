import logging
import threading
import time
from pathlib import Path

import db
from config import MEDIA_PATH

log = logging.getLogger(__name__)

# The admin Overview polls the overview every 30s and the Library page loads
# it too; the media-tree walk below is the single most expensive per-call
# piece of work in the app, so all pollers share one cached result.
OVERVIEW_CACHE_TTL_SEC = 60
_overview_cache: dict = {"ts": 0.0, "data": None}
_overview_lock = threading.Lock()


def _count_strms(base: Path) -> int:
    if not base.exists():
        return 0
    return sum(1 for _ in base.rglob("*.strm"))


def _build_overview() -> dict:
    media = Path(MEDIA_PATH)
    req = db.get_request_stats(days=7)
    wanted = db.count_wanted_episodes_by_status()
    success_rate = round(
        100 * req["succeeded"] / max(1, req["succeeded"] + req["failed"]), 1)

    return {
        "library": {
            "movie_count": _count_strms(media / "movies"),
            "episode_count": _count_strms(media / "series"),
            "series_count": db.count_monitored_series(),
        },
        "requests": {
            "total": req["total"],
            "succeeded_7d": req["succeeded"],
            "failed_7d": req["failed"],
            "success_rate_7d": success_rate,
        },
        "wanted": {
            "active": wanted.get("wanted", 0),
            "found": wanted.get("found", 0),
            "give_up": wanted.get("give_up", 0),
        },
        "movies_pending": db.count_media_items_pending("movie"),
        "egress_bytes_month": db.egress_this_month(),
        "qualities": req["qualities"],
    }


def get_overview(force: bool = False) -> dict:
    now = time.monotonic()
    if not force and _overview_cache["data"] is not None \
            and now - _overview_cache["ts"] < OVERVIEW_CACHE_TTL_SEC:
        return _overview_cache["data"]
    with _overview_lock:
        # Re-check under the lock: another poller may have just rebuilt it.
        now = time.monotonic()
        if not force and _overview_cache["data"] is not None \
                and now - _overview_cache["ts"] < OVERVIEW_CACHE_TTL_SEC:
            return _overview_cache["data"]
        data = _build_overview()
        _overview_cache["data"] = data
        _overview_cache["ts"] = time.monotonic()
        return data


def get_storage_breakdown(limit: int = 20) -> list[dict]:
    """Top folders by strm count (proxy for content size since strm files are tiny)."""
    media = Path(MEDIA_PATH)
    counts: dict[str, int] = {}
    for sub in ("movies", "series"):
        base = media / sub
        if not base.exists():
            continue
        for entry in base.iterdir():
            if entry.is_dir():
                n = sum(1 for _ in entry.rglob("*.strm"))
                if n:
                    counts[f"{sub}/{entry.name}"] = n
    items = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:limit]
    return [{"path": p, "count": c} for p, c in items]


def get_repair_overview(limit: int = 200) -> dict:
    """Everything the repair half of the Maintenance tab renders.

    That half is server-rendered, and until this existed the only way to
    refresh it was to reload the whole dashboard, which is exactly what
    templates/ui.html used to do every two minutes.

    last_cleanup is None before the first cleanup run; the template renders
    "No cleanup run yet." for that, so the key is always present rather than
    omitted.
    """
    return {
        "items": db.get_repair_items(limit),
        "last_cleanup": db.get_last_cleanup_run(),
    }
