"""Background jobs for the catbox play path: releasing idle TorBox items and
reconciling stored TorBox ids against each account's own list. Split out of
catbox.py so the play path stays lean; imports catbox at module level for the
private state it shares with the play path (_home, _token_lock,
invalidate_url_cache, _sweep_caches, _settings, db, torbox). catbox.py
re-exports release_idle, reconcile_torbox_ids and last_reconcile as thin
wrappers with a lazy import back into this module, so it cannot import
catbox_jobs at module level without deadlocking the import.
"""
import logging
import threading
from datetime import datetime, timedelta, timezone

import catbox
from config import CATBOX_IDLE_MINUTES as _CATBOX_IDLE_MINUTES_DEFAULT

log = logging.getLogger(__name__)


_last_reconcile: dict | None = None
_reconcile_lock = threading.Lock()


def last_reconcile() -> dict | None:
    """The most recent reconcile_torbox_ids() result, or None since start."""
    with _reconcile_lock:
        return dict(_last_reconcile) if _last_reconcile else None


def _account_lists(accounts: list) -> tuple[dict[int, list], dict[int, str]]:
    """Each enabled account's live TorBox list, fetched once. An empty list
    is treated the same as a failure to fetch it (an outage would otherwise
    look like the account cleared house): both mark the account skipped."""
    lists: dict[int, list] = {}
    skipped: dict[int, str] = {}
    for a in accounts:
        try:
            live = catbox.torbox.list_torrents(a.id, force_refresh=True)
        except Exception as exc:
            log.warning("Catbox: TorBox id reconcile skipped for %s, list unavailable: %s", a.label, exc)
            skipped[a.id] = str(exc)
            continue
        if not live:
            skipped[a.id] = "list empty"
            continue
        lists[a.id] = live
    return lists, skipped


def reconcile_torbox_ids() -> dict:
    """Compare stored TorBox ids with each account's own list. An id whose
    torrent is gone (deleted in the TorBox app, expired) is cleared so the
    next play re-adds cleanly instead of discovering the loss first; when
    the same hash lives under another id (its own account, or another one)
    the item is pointed at that one. An item whose account is disabled or
    unknown is checked by hash only, since it has no list to belong to.
    Never deletes anything on TorBox. An account whose list is empty or
    unavailable is skipped entirely: its items are left alone rather than
    cleared as if the account had emptied out."""
    import torbox_pool
    result = {"ran_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
              "checked": 0, "cleared": 0, "repointed": 0, "skipped": None, "accounts": {}}
    items = catbox.db.get_virtual_items_with_torbox_id()
    result["checked"] = len(items)

    enabled = torbox_pool.accounts()
    label_by_id = {a.id: a.label for a in enabled}
    account_stats = {a.label: {"checked": 0, "cleared": 0, "repointed": 0, "skipped": None} for a in enabled}

    if items and enabled:
        lists, skipped = _account_lists(enabled)
        for acct_id, reason in skipped.items():
            account_stats[label_by_id[acct_id]]["skipped"] = reason

        live_ids_by_account = {acct_id: {t.get("id") for t in live} for acct_id, live in lists.items()}
        hash_to_home: dict[str, tuple[int, int]] = {}
        for acct_id, live in lists.items():
            for t in live:
                h = (t.get("hash") or "").lower()
                if h:
                    hash_to_home[h] = (acct_id, t.get("id"))

        for item in items:
            acct_id = catbox._home(item)
            if acct_id is not None:
                account_stats[label_by_id[acct_id]]["checked"] += 1
                if acct_id in skipped:
                    continue  # its account's list didn't answer; leave it
                if item["torbox_id"] in live_ids_by_account.get(acct_id, set()):
                    continue
            elif not lists:
                continue  # homeless, and no account answered: nothing known to have changed
            if catbox._token_lock(item["token"]).locked():
                continue  # a play is materializing it right now
            target = hash_to_home.get((item.get("info_hash") or "").lower())
            if target is not None:
                new_acct, new_id = target
                catbox.db.set_virtual_torbox(item["token"], new_id, new_acct)
                result["repointed"] += 1
                if acct_id is not None:
                    account_stats[label_by_id[acct_id]]["repointed"] += 1
                log.info("Catbox: %s (%s) now under TorBox id %s on %s, was %s",
                         item.get("title"), item["token"], new_id, label_by_id.get(new_acct, new_acct),
                         item["torbox_id"])
            else:
                catbox.db.set_virtual_torbox(item["token"], None, None)
                catbox.invalidate_url_cache(item["token"])
                result["cleared"] += 1
                if acct_id is not None:
                    account_stats[label_by_id[acct_id]]["cleared"] += 1
                log.info("Catbox: TorBox id %s for %s (%s) is gone; cleared, next play re-adds",
                         item["torbox_id"], item.get("title"), item["token"])

        unanswered = [label_by_id[a.id] for a in enabled if a.id in skipped]
        if unanswered:
            result["skipped"] = ", ".join(unanswered)
        if result["cleared"] or result["repointed"]:
            log.info("Catbox: TorBox id reconcile: %d checked, %d cleared, %d repointed",
                     result["checked"], result["cleared"], result["repointed"])
    elif items and not enabled:
        result["skipped"] = "no enabled TorBox account"

    result["accounts"] = account_stats
    global _last_reconcile
    with _reconcile_lock:
        _last_reconcile = result
    return result


def release_idle() -> int:
    """Remove TorBox items idle longer than CATBOX_IDLE_MINUTES. Returns count released."""
    catbox._sweep_caches()
    idle_minutes = catbox._settings.get("CATBOX_IDLE_MINUTES", _CATBOX_IDLE_MINUTES_DEFAULT)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=idle_minutes)
    cutoff_iso = cutoff.strftime("%Y-%m-%d %H:%M:%S")
    items = catbox.db.get_idle_virtual_items(cutoff_iso)
    released = 0
    for item in items:
        acct = catbox._home(item)
        if acct is None:
            # Disabled or unknown account (or, after the migration, no
            # account at all): nothing to delete through, so just clear
            # the local reference. The torrent (if any) stays on TorBox
            # until its account is enabled again.
            catbox.db.set_virtual_torbox(item["token"], None, None)
            raw_account = item.get("torbox_account")
            if raw_account:
                log.info("Catbox: %s's TorBox id %s stays on account %s until it is enabled again; cleared locally",
                         item.get("title"), item["torbox_id"], raw_account)
            else:
                log.info("Catbox: %s had no TorBox account on record; cleared locally",
                         item.get("title"))
            released += 1
            continue
        try:
            deleted = catbox.torbox.delete_torrent(acct, item["torbox_id"])
            if not deleted:
                # Torrent may already be gone from TorBox (evicted or manually removed).
                # Still clear the local reference so catbox can re-add it on next play.
                still_there = catbox.torbox.find_by_id(acct, item["torbox_id"])
                if still_there:
                    continue
            catbox.db.set_virtual_torbox(item["token"], None, None)
            log.info("Catbox: released idle torrent %s (%s)", item["torbox_id"], item["title"])
            released += 1
        except Exception as exc:
            log.warning("Catbox: failed to release idle torrent %s (%s): %s",
                        item["torbox_id"], item.get("title"), exc)
    if released:
        log.info("Catbox: released %d idle torrent(s)", released)
    return released
