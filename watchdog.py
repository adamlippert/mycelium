"""Self-monitoring: deadman switch + disk-space warnings.

deadman_check(): if no successful add or strm_generator run has happened in
DEADMAN_HOURS, fire a notification once per debounce window. It also alerts
when the database has no library items but .strm files already exist under
MEDIA_PATH, since that combination means the database itself is empty or
unmounted, not that the install is genuinely fresh.

disk_check(): warn if MEDIA_PATH or the DB volume crosses the configured
fill percentage. De-bounced so it doesn't spam.
"""
import logging
import shutil
import time
from datetime import datetime
from pathlib import Path

import db
import notify
from config import DB_PATH, MEDIA_PATH

log = logging.getLogger(__name__)


_last_warn: dict[str, float] = {}
_WARN_DEBOUNCE_SEC = 6 * 3600  # 6h between repeated warnings per metric


def _warn(metric: str, title: str, message: str) -> None:
    now = time.monotonic()
    if now - _last_warn.get(metric, 0) < _WARN_DEBOUNCE_SEC:
        return
    _last_warn[metric] = now
    log.warning(message)
    db.log_activity("watchdog", title, message, False)
    notify.send(title, message, success=False)


# ── Deadman switch ────────────────────────────────────────────────────────────

DEADMAN_HOURS = 24


def _last_success_age_hours() -> float | None:
    """Hours since the most recent successful add (or 'added' activity event)."""
    try:
        activity = db.get_activity(50)
    except Exception:
        return None
    for ev in activity:
        if ev.get("success") and ev.get("event") in ("added", "upgraded"):
            ts = ev.get("created_at")
            if not ts:
                continue
            try:
                t = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue
            return (datetime.utcnow() - t).total_seconds() / 3600
    return None


def _library_has_ever_existed() -> bool:
    """At least one .strm exists under MEDIA_PATH. The media tree lives on
    its own mount, so unlike a settings row it survives the database
    being wiped or a fresh file being created on an unmounted volume,
    and a genuinely fresh install has none, so it stays quiet."""
    try:
        return next(Path(MEDIA_PATH).rglob("*.strm"), None) is not None
    except Exception as exc:
        log.debug("Deadman: could not scan %s: %s", MEDIA_PATH, exc)
        return False


def deadman_check() -> None:
    # An empty library on an install whose media tree already holds .strm
    # files is a wiped or unmounted database, and it is the state the age
    # check below cannot see: with no activity rows at all,
    # _last_success_age_hours() returns None and this function used to
    # return silently, exactly when it mattered most. The media tree, not
    # a settings row, is the signal: it lives on its own mount and survives
    # a database wipe.
    if _library_has_ever_existed():
        try:
            if db.count_virtual_items() == 0:
                _warn(
                    "empty-library",
                    "Library is empty",
                    "No library items in the database, but .strm files exist "
                    "on disk. The database may be a fresh file rather than "
                    "the real one: check that the data volume is mounted "
                    "before the repair jobs run.",
                )
                return
        except Exception as exc:
            log.debug("Deadman: could not count virtual items: %s", exc)

    age = _last_success_age_hours()
    if age is None or age < DEADMAN_HOURS:
        return
    _warn(
        "deadman",
        "Deadman: no activity",
        f"No successful add in the last {age:.1f} hours  -  scheduler stuck or services unreachable?",
    )


# ── Disk space ────────────────────────────────────────────────────────────────

DISK_WARN_PERCENT = 90


def _check_path(path: str, name: str) -> None:
    try:
        p = Path(path)
        target = p if p.exists() else p.parent
        usage = shutil.disk_usage(str(target))
    except Exception as exc:
        log.debug("Disk check %s failed: %s", path, exc)
        return
    pct = 100 * usage.used / max(1, usage.total)
    if pct >= DISK_WARN_PERCENT:
        gb_free = usage.free / 1e9
        _warn(
            f"disk:{name}",
            f"Disk almost full ({name})",
            f"{name} volume {pct:.0f}% full · {gb_free:.1f} GB free",
        )


def disk_check() -> None:
    _check_path(MEDIA_PATH, "media")
    _check_path(DB_PATH, "db")
