"""Notice titles whose .strm files were deleted on disk and purge them.

Jellyfin deletes the file when a person (or Maintainerr through Jellyfin)
deletes an item, and Mycelium shares PUID with it. A title whose every
.strm is gone was therefore deleted in Jellyfin; without this job only the
Jellyfin webhook plugin would tell us, and the repair job would put the
files straight back. Runs on its own schedule whenever CATBOX_MODE is on:
it needs no Radarr, Sonarr or mirror. The webhook plugin makes the same
deletion instant; this job makes it converge within DISK_SYNC_INTERVAL_MINUTES.

The grace period, the mass-loss guards and the purge loop live here and are
shared with arr_sync, which watches the arrs the same way.
"""
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import db
import settings as _settings

log = logging.getLogger(__name__)

# A deletion elsewhere is only believed when it looks like one. Below this
# many titles the fraction guard cannot say anything; above it, more than
# this share vanishing at once is a rebuilt arr or a lost mount, and the
# right move is to purge nothing and say so.
PURGE_GUARD_MIN_TITLES = 5
PURGE_GUARD_MAX_SHARE = 0.5
PURGE_GRACE_MINUTES = 10


def is_enabled() -> bool:
    import config
    return bool(config.CATBOX_MODE) and bool(_settings.get("DISK_SYNC_ENABLED", True))


def older_than_grace(row: dict) -> bool:
    """True when the row was last touched (updated, or first mirrored) more
    than the grace ago. A row still being written, or mirrored after a
    listing was taken, must not look deleted. Unparseable dates count as
    recent: no purge."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    stamps = [row.get("updated_at") or row.get("created_at") or "", row.get("arr_mirrored_at") or ""]
    for raw in stamps:
        if not raw:
            continue
        try:
            when = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return False
        if now - when <= timedelta(minutes=PURGE_GRACE_MINUTES):
            return False
    return True


def purge_rows(victims: dict[str, tuple[dict, str]]) -> int:
    """purge_title() each (row, reason), logging and recording why. Returns
    how many succeeded; one failure never stops the rest."""
    import cleanup
    purged = 0
    for imdb_id, (r, why) in victims.items():
        try:
            log.info("%s (%s) was %s; purging", r.get("title") or imdb_id, imdb_id, why)
            cleanup.purge_title(imdb_id, row_id=r.get("id"))
            purged += 1
            try:
                db.log_activity("purged", r.get("title") or imdb_id, f"{imdb_id}: {why}; removed by the reconcile", imdb_id=imdb_id)
            except Exception:
                pass
        except Exception as exc:
            log.warning("Purge of %s failed: %s", imdb_id, exc)
    return purged


def find_missing(success: list[dict]) -> tuple[list[dict], list[dict]]:
    """(titles with .strm rows, those whose files are all gone and are past
    the grace). Pure bookkeeping: no purge, no guard."""
    from arr_webhook import files_still_present
    with_files: list[dict] = []
    missing: list[dict] = []
    for r in success:
        try:
            items = [i for i in db.get_virtual_items_by_imdb(r["imdb_id"]) if i.get("strm_path")]
        except Exception as exc:
            log.debug("Disk sync: items for %s unavailable: %s", r["imdb_id"], exc)
            continue
        if not items:
            continue
        with_files.append(r)
        if not files_still_present(items) and older_than_grace(r):
            missing.append(r)
    return with_files, missing


def reconcile() -> dict:
    """Purge every successful title whose .strm files are all gone from disk,
    unless the whole media tree looks gone (lost mount) or more than half
    the titles lost their files at once. Scheduled; never raises."""
    out = {"checked": 0, "missing": 0, "purged": 0, "refused": 0}
    if not is_enabled():
        return out
    try:
        import config
        success = [r for r in db.get_recent(100000) if r.get("status") == "success"]
        with_files, missing = find_missing(success)
        out["checked"] = len(with_files)
        out["missing"] = len(missing)
        if not missing:
            return out
        media_root = Path(config.MEDIA_PATH)
        tree_alive = media_root.is_dir() and next(media_root.rglob("*.strm"), None) is not None
        if not tree_alive:
            log.warning("Disk sync: no .strm under %s; refusing to purge %d title(s) with missing files "
                        "(media mount gone?)", media_root, len(missing))
            out["refused"] = len(missing)
        elif len(with_files) >= PURGE_GUARD_MIN_TITLES and len(missing) > PURGE_GUARD_MAX_SHARE * len(with_files):
            log.warning("Disk sync: %d of %d titles lost their files at once; refusing to purge",
                        len(missing), len(with_files))
            out["refused"] = len(missing)
        else:
            out["purged"] = purge_rows({r["imdb_id"]: (r, "gone from disk (deleted in Jellyfin?)") for r in missing})
    except Exception as exc:
        log.warning("Disk sync: reconcile failed: %s", exc)
    if out["missing"]:
        log.info("Disk sync: reconcile %s", out)
    return out
