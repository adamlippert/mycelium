import logging
import threading
import time

import requests

from config import (
    TORBOX_BASE_URL as _TORBOX_BASE_URL_DEFAULT,
    TORBOX_POLL_INTERVAL_SEC,
    TORBOX_POLL_TIMEOUT_SEC,
)

log = logging.getLogger(__name__)


def _base_url() -> str:
    import settings
    return settings.get("TORBOX_BASE_URL", _TORBOX_BASE_URL_DEFAULT)


class AuthFailed(Exception):
    """TorBox answered 401 or 403 for this account: key revoked, plan
    restriction, or the account disabled on their side."""


def _headers(account_id: int) -> dict[str, str]:
    import torbox_pool
    acct = torbox_pool.account(account_id)
    if acct is None:
        raise RuntimeError(f"unknown TorBox account {account_id}")
    return {"Authorization": _AUTH.format(acct.api_key)}


_AUTH = "Bearer {}"


def _any_headers() -> dict[str, str]:
    """For calls not bound to an account (cache checks)."""
    import torbox_pool
    return {"Authorization": _AUTH.format(torbox_pool.any_key())}


def _check_auth(account_id: int, resp) -> None:
    if resp.status_code in (401, 403):
        import torbox_pool
        torbox_pool.mark_auth_failure(account_id)
        log.warning("TorBox account %s answered %s", account_id, resp.status_code)
        raise AuthFailed(f"account {account_id}: {resp.status_code}")


# ── createtorrent rate-limit visibility ───────────────────────────────────────
# TorBox limits POST /torrents/createtorrent to 60/hour per API key for
# UNCACHED torrents; cached adds fall under the general 300/minute limit
# (support.torbox.app, "API Rate Limits"). Every call is reserved in the
# createtorrent_log table BEFORE the HTTP request, in
# one immediate transaction, so the budget holds across threads AND across
# processes: the database is the single source of truth, and adding gunicorn
# workers cannot multiply the local guard into N independent 60/hour counters
# (TorBox's real limit does not care how many workers we run). Every account
# has its own 60/hour budget, so the reservation is keyed by account too.


def _reserve_createtorrent_slot(account_id: int, reason: str, cached: bool = False) -> int:
    """Atomically check both the hourly and per-minute budgets for this
    account and reserve a slot in the same transaction, so two concurrent
    callers can't both pass the check before either recorded a call. Raises
    RateLimited if no budget remains; otherwise returns the reservation's
    row id so the caller can roll it back if the API call itself fails."""
    import db as _db
    res = _db.reserve_createtorrent_slot(
        time.time(), reason, _CREATETORRENT_LIMIT_HOUR, _CREATETORRENT_LIMIT_MIN,
        cached=cached, account_id=account_id)
    if res["id"] is None:
        if not cached and res["hour_count"] >= _CREATETORRENT_LIMIT_HOUR - 2:
            log.warning("createtorrent [%s] account=%s SKIPPED  -  hourly quota %d/%d reached",
                        reason, account_id, res["hour_count"], _CREATETORRENT_LIMIT_HOUR)
        else:
            log.warning("createtorrent [%s] account=%s SKIPPED  -  per-minute burst %d/%d reached",
                        reason, account_id, res["min_count"], _CREATETORRENT_LIMIT_MIN)
        raise RateLimited()
    log.info("createtorrent [%s] account=%s (%d/60h uncached, %d/10m, %s): reserving slot",
             reason, account_id, res["hour_count"], res["min_count"], "cached" if cached else "uncached")
    return res["id"]


def _release_createtorrent_slot(entry: int) -> None:
    """Undo a reservation when the API call never actually reached/was
    accepted by TorBox (network error, explicit 429, or non-2xx response)."""
    import db as _db
    try:
        _db.release_createtorrent_slot(entry)
    except Exception as exc:
        log.debug("Could not release createtorrent slot %s: %s", entry, exc)


def createtorrent_usage(account_id: int | None = None, window_sec: int = 3600) -> dict:
    """Return how many createtorrent calls happened in the last `window_sec`,
    broken down by reason, for one account or (account_id=None) summed
    across every account."""
    import db as _db
    cutoff = time.time() - window_sec
    recent = _db.get_createtorrent_log(cutoff, account_id)
    by_reason: dict[str, int] = {}
    cached_count = 0
    for _, reason, cached, _account in recent:
        if cached:
            cached_count += 1
            continue
        by_reason[reason] = by_reason.get(reason, 0) + 1
    uncached = [ts for ts, _, cached, _account in recent if not cached]
    oldest = min(uncached, default=None)
    if account_id is None:
        # Summed across every account: the aggregate's limit is 60 per
        # account, not 60 flat  -  a two-account pool has 120/hour to spend,
        # not 60. At least one account's worth even if the pool is empty
        # (no accounts configured yet), so the figure stays meaningful.
        import torbox_pool
        try:
            n_accounts = max(1, len(torbox_pool.accounts()))
        except Exception:
            n_accounts = 1
        limit = _CREATETORRENT_LIMIT_HOUR * n_accounts
    else:
        limit = _CREATETORRENT_LIMIT_HOUR
    return {
        # `count` is the figure TorBox limits: uncached adds only.
        "count": len(uncached),
        "cached_count": cached_count,
        "limit": limit,
        "window_sec": window_sec,
        "by_reason": by_reason,
        "oldest_ts": oldest,
        "resets_in_sec": int(oldest + window_sec - time.time()) if oldest else 0,
    }


_CREATETORRENT_LIMIT_HOUR = 60   # TorBox: 60/hour per API key, uncached adds only
_CREATETORRENT_LIMIT_MIN  = 10   # local burst guard on every add, cached or not


class RateLimited(Exception):
    """Raised (proactively) when the local createtorrent budget is exhausted, so
    we never even send a request we know TorBox will reject with 429."""


_last_429: dict[int, float] = {}  # account_id -> wall-clock time of its last createtorrent 429


def last_429_at(account_id: int | None = None) -> float | None:
    if account_id is not None:
        return _last_429.get(account_id)
    return max(_last_429.values(), default=None)


def add_magnet(account_id: int, magnet: str, timeout: int = 30, reason: str = "unknown",
               cached: bool | None = None) -> dict:
    """Add a magnet to this account. `cached` is what the caller's cache
    check said: True means the add does not count against TorBox's hourly
    uncached budget. TorBox's answer corrects the flag afterwards where it
    is explicit."""
    url = f"{_base_url().rstrip('/')}/torrents/createtorrent"
    # Client-side guard: check both the 60/hour and the 10/minute edge limits,
    # and reserve the slot in the same locked step (see _reserve_createtorrent_slot).
    entry = _reserve_createtorrent_slot(account_id, reason, cached=bool(cached))
    log.info("createtorrent [%s] account=%s: %s", reason, account_id, magnet[:80])
    try:
        resp = requests.post(url, headers=_headers(account_id), data={"magnet": magnet}, timeout=timeout)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 60))
            _last_429[account_id] = time.time()
            import torbox_pool
            torbox_pool.mark_429(account_id)
            log.warning("createtorrent [%s] account=%s got 429 from TorBox (Retry-After=%ds)  -  raising RateLimited",
                        reason, account_id, retry_after)
            raise RateLimited()
        _check_auth(account_id, resp)
        resp.raise_for_status()
    except Exception:
        # TorBox never actually accepted this call - give the slot back.
        _release_createtorrent_slot(entry)
        raise
    payload = resp.json() or {}
    if not payload.get("success", False):
        # DUPLICATE_ITEM means the torrent is already in TorBox  -  treat as success
        if payload.get("error") == "DUPLICATE_ITEM":
            log.info("Torbox: torrent already exists (DUPLICATE_ITEM), treating as success")
            _correct_cached_flag(entry, bool(cached), True)
            invalidate_mylist_cache(account_id)
            return payload.get("data", {}) or {}
        raise RuntimeError(f"Torbox add failed: {payload}")
    data = payload.get("data", {}) or {}
    _correct_cached_flag(entry, bool(cached), _response_says_cached(payload))
    # Normalize: TorBox returns "torrent_id" for cached adds, "id" for others.
    if data.get("torrent_id") and not data.get("id"):
        data["id"] = data["torrent_id"]
    log.info("Torbox createtorrent response: %s (id=%s)", payload.get("detail") or data, data.get("id"))
    invalidate_mylist_cache(account_id)
    return data


def _response_says_cached(payload: dict) -> bool | None:
    """True/False when TorBox's createtorrent answer is explicit about the
    torrent being cached ("Found cached torrent") or queued for download,
    None when it says neither."""
    detail = str(payload.get("detail") or "").lower()
    if "cached" in detail:
        return True
    if "queue" in detail or "download" in detail:
        return False
    return None


def _correct_cached_flag(entry: int, reserved_cached: bool, actual: bool | None) -> None:
    """Fix the reservation's flag when TorBox's answer contradicts what the
    caller expected, so the hourly count matches what TorBox counted."""
    if actual is None or actual == reserved_cached:
        return
    import db as _db
    try:
        _db.mark_createtorrent_cached(entry, actual)
        log.info("createtorrent slot %s corrected to %s after TorBox's answer",
                 entry, "cached" if actual else "uncached")
    except Exception as exc:
        log.debug("Could not correct createtorrent slot %s: %s", entry, exc)


_MYLIST_TTL_SECONDS = 45
# account_id -> {"items": [...], "ts": monotonic}
_mylist: dict[int, dict] = {}
_mylist_lock = threading.Lock()
# Held for the duration of one account's refresh, so TTL expiry does not
# stampede: one thread pays the (up to 20-page) fetch, everyone else waits
# for its result or keeps serving the barely-stale copy. Created lazily
# under _mylist_lock so accounts don't share a lock.
_mylist_refresh_locks: dict[int, threading.Lock] = {}


def _refresh_lock(account_id: int) -> threading.Lock:
    with _mylist_lock:
        lock = _mylist_refresh_locks.get(account_id)
        if lock is None:
            lock = threading.Lock()
            _mylist_refresh_locks[account_id] = lock
        return lock


def _mylist_fresh(account_id: int):
    import time as _t
    entry = _mylist.get(account_id)
    if entry is not None and (_t.monotonic() - entry["ts"]) < _MYLIST_TTL_SECONDS:
        return entry["items"]
    return None


def list_torrents(account_id: int, timeout: int = 30, force_refresh: bool = False) -> list[dict]:
    """Return this account's TorBox mylist (all pages), cached for ~45s."""
    if not force_refresh:
        fresh = _mylist_fresh(account_id)
        if fresh is not None:
            return fresh
        # Stale but present, and another thread is already refreshing this
        # account: serve the stale copy instead of stacking a duplicate fetch.
        entry = _mylist.get(account_id)
        stale = entry["items"] if entry is not None else None
        if stale is not None and _refresh_lock(account_id).locked():
            return stale
    with _refresh_lock(account_id):
        # Re-check: the thread we waited behind may have just refreshed.
        if not force_refresh:
            fresh = _mylist_fresh(account_id)
            if fresh is not None:
                return fresh
        return _fetch_mylist(account_id, timeout)


def _fetch_mylist(account_id: int, timeout: int) -> list[dict]:
    import time as _t
    url = f"{_base_url().rstrip('/')}/torrents/mylist"
    all_items: list[dict] = []
    seen_ids: set[int] = set()
    offset = 0
    limit = 1000
    for _ in range(20):  # max 20 pages = 20 000 items; guards against infinite loop
        resp = requests.get(url, headers=_headers(account_id), timeout=timeout,
                            params={"limit": limit, "offset": offset})
        _check_auth(account_id, resp)
        resp.raise_for_status()
        payload = resp.json() or {}
        page = payload.get("data", []) or []
        new = [t for t in page if t.get("id") not in seen_ids]
        if not new:
            break
        all_items.extend(new)
        seen_ids.update(t["id"] for t in new)
        if len(page) < limit:
            break
        offset += limit
    with _mylist_lock:
        _mylist[account_id] = {"items": all_items, "ts": _t.monotonic()}
    return all_items


def invalidate_mylist_cache(account_id: int | None = None) -> None:
    """Drop the mylist cache for one account, or (account_id=None) every
    account, so the next list_torrents() hits TorBox fresh."""
    with _mylist_lock:
        if account_id is None:
            _mylist.clear()
        else:
            _mylist.pop(account_id, None)


def _matches_hash(item: dict, info_hash: str) -> bool:
    candidate = (item.get("hash") or "").lower()
    return candidate == info_hash.lower()


def find_by_hash(account_id: int, info_hash: str, force_refresh: bool = False) -> dict | None:
    for item in list_torrents(account_id, force_refresh=force_refresh):
        if _matches_hash(item, info_hash):
            return item
    return None


def find_by_id(account_id: int, torrent_id: int, timeout: int = 15) -> dict | None:
    """Fetch a single torrent by ID directly from TorBox  -  not limited to mylist top-1000."""
    url = f"{_base_url().rstrip('/')}/torrents/mylist"
    try:
        resp = requests.get(url, headers=_headers(account_id), timeout=timeout,
                            params={"id": torrent_id})
        _check_auth(account_id, resp)
        resp.raise_for_status()
        data = (resp.json() or {}).get("data")
        if isinstance(data, dict) and data.get("id") == torrent_id:
            return data
        if isinstance(data, list):
            for item in data:
                if item.get("id") == torrent_id:
                    return item
    except requests.RequestException as exc:
        log.warning("TorBox find_by_id(%s) account=%s failed: %s", torrent_id, account_id, exc)
    return None


def get_user_info(account_id: int, timeout: int = 10) -> dict | None:
    """Return TorBox user info (subscription, plan, etc) or None on failure."""
    url = f"{_base_url().rstrip('/')}/user/me"
    try:
        resp = requests.get(url, headers=_headers(account_id), timeout=timeout)
        _check_auth(account_id, resp)
        resp.raise_for_status()
        return (resp.json() or {}).get("data") or {}
    except AuthFailed:
        raise
    except Exception as exc:
        log.debug("TorBox user info account=%s failed: %s", account_id, exc)
        return None


def get_usage_summary(account_id: int) -> dict:
    """Derived usage info: torrent count, total bytes, active-state breakdown."""
    items = list_torrents(account_id)
    total_bytes = sum(t.get("size") or 0 for t in items)
    states: dict[str, int] = {}
    for t in items:
        s = (t.get("download_state") or "unknown").lower()
        states[s] = states.get(s, 0) + 1
    return {
        "torrent_count": len(items),
        "total_bytes": total_bytes,
        "total_gb": round(total_bytes / 1e9, 1),
        "states": states,
    }


# Track last warning to avoid spamming, keyed by (account_id, metric)
_last_quota_warn: dict[tuple[int, str], float] = {}


def check_quota_and_warn(threshold_count: int = 200, threshold_gb: int = 4000) -> None:
    """Notify if any account's torrent count or total size approaches the
    configured threshold. Re-warns at most once every 6 hours per account
    per metric."""
    import time
    import db
    import notify
    import torbox_pool
    now = time.monotonic()
    for acct in torbox_pool.accounts():
        try:
            summary = get_usage_summary(acct.id)
        except AuthFailed as exc:
            log.warning("Quota check skipped for %s (auth failed): %s", acct.label, exc)
            continue
        for metric, value, limit, fmt in (
            ("count", summary["torrent_count"], threshold_count, "%d torrents"),
            ("size", summary["total_gb"], threshold_gb, "%.1f GB"),
        ):
            if value < limit * 0.8:
                continue
            key = (acct.id, metric)
            if now - _last_quota_warn.get(key, 0) < 6 * 3600:
                continue
            _last_quota_warn[key] = now
            msg = f"TorBox usage approaching limit ({acct.label}): {fmt % value} (threshold {limit})"
            log.warning(msg)
            db.log_activity("quota_warn", "TorBox", msg, False)
            notify.send("TorBox quota warning", msg, success=False)


def delete_torrent(account_id: int, torrent_id: int, timeout: int = 15) -> bool:
    url = f"{_base_url().rstrip('/')}/torrents/controltorrent"
    try:
        resp = requests.post(
            url, headers=_headers(account_id),
            json={"torrent_id": torrent_id, "operation": "delete"},
            timeout=timeout,
        )
        _check_auth(account_id, resp)
        resp.raise_for_status()
        log.info("Deleted TorBox torrent %s (account=%s)", torrent_id, account_id)
        invalidate_mylist_cache(account_id)
        return True
    except Exception as exc:
        log.warning("Delete torrent %s (account=%s) failed: %s", torrent_id, account_id, exc)
        return False


def check_cached(hashes: list[str], timeout: int = 15) -> set[str]:
    """Return the subset of hashes that TorBox has cached (instant download
    available). Not bound to one account: any enabled account's key answers
    the same cache-status question."""
    if not hashes:
        return set()
    _BATCH = 100
    if len(hashes) > _BATCH:
        cached: set[str] = set()
        for i in range(0, len(hashes), _BATCH):
            cached |= check_cached(hashes[i:i + _BATCH], timeout=timeout)
        log.info("TorBox cache check: %d/%d hashes cached (batched)", len(cached), len(hashes))
        return cached
    url = f"{_base_url().rstrip('/')}/torrents/checkcached"
    params = {"hash": ",".join(hashes), "format": "object"}
    try:
        resp = requests.get(url, headers=_any_headers(), params=params, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("TorBox checkcached failed: %s", exc)
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (429, 403) or "429" in str(exc) or "403" in str(exc):
            # 429 = rate limited; 403 = API key invalid / plan restriction.
            raise RateLimited(f"checkcached {status or 'error'}")
        # 5xx or network error: TorBox is temporarily unavailable.
        # Raise so callers treat this as _SEARCH_UNAVAILABLE (30s cooldown)
        # instead of silently returning an empty set that causes a false 6h miss.
        raise RuntimeError(f"TorBox checkcached unavailable: {exc}")
    data = (resp.json() or {}).get("data") or {}
    cached = {h.lower() for h in data.keys()}
    log.info("TorBox cache check: %d/%d hashes cached", len(cached), len(hashes))
    return cached


def check_cached_files(hashes: list[str], timeout: int = 15) -> dict[str, dict]:
    """Like check_cached(), but keeps the per-hash name, size and files
    list (id, name, size per file) of the cached data. No torrent is added
    to the account, this is a pure cache-status lookup. Returns {} when the
    lookup fails; callers treat that as "contents unknown"."""
    if not hashes:
        return {}
    _BATCH = 100
    if len(hashes) > _BATCH:
        out: dict[str, dict] = {}
        for i in range(0, len(hashes), _BATCH):
            out.update(check_cached_files(hashes[i:i + _BATCH], timeout=timeout))
        return out
    url = f"{_base_url().rstrip('/')}/torrents/checkcached"
    # list_files makes each cached entry carry its files list with the
    # same ids the torrent shows once added (verified against the API on
    # 2026-09-13), so a season pack's contents are known before any add.
    params = {"hash": ",".join(hashes), "format": "object", "list_files": "true"}
    try:
        resp = requests.get(url, headers=_any_headers(), params=params, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("TorBox checkcached (files) failed: %s", exc)
        return {}
    data = (resp.json() or {}).get("data") or {}
    return {h.lower(): v for h, v in data.items()}


def title_exists(account_id: int, title: str) -> bool:
    """Return True if any torrent in this account's mylist appears to match the given title."""
    needle = title.lower()
    for item in list_torrents(account_id):
        name = (item.get("name") or "").lower()
        if needle in name or name in needle:
            return True
    return False


def _is_ready(item: dict) -> bool:
    if item.get("download_finished"):
        return True
    state = (item.get("download_state") or "").lower()
    return state in ("cached", "completed", "uploading", "metadl_done")


def wait_until_ready(account_id: int, info_hash: str, timeout: int | None = None,
                     torrent_id: int | None = None) -> dict | None:
    """Poll Torbox until the torrent reports completion or the timeout is reached.
    timeout defaults to TORBOX_POLL_TIMEOUT_SEC; pass a smaller value for
    latency-sensitive paths like on-play re-materialization.
    When torrent_id is given, uses find_by_id (single direct API call) instead
    of scanning the full mylist  -  faster and not limited to the top 1000."""
    limit = TORBOX_POLL_TIMEOUT_SEC if timeout is None else timeout
    deadline = time.monotonic() + limit
    last_state: str | None = None
    while time.monotonic() < deadline:
        item = find_by_id(account_id, torrent_id) if torrent_id else find_by_hash(account_id, info_hash)
        if item is None:
            log.debug("Torrent %s not in mylist yet (account=%s)", info_hash, account_id)
        else:
            state = item.get("download_state") or ""
            progress = item.get("progress") or 0
            if state != last_state:
                log.info("Torbox state: %s (progress=%.2f%%)", state, float(progress) * 100)
                last_state = state
            if _is_ready(item):
                log.info("Torbox reports torrent ready: %s", info_hash)
                return item
        time.sleep(TORBOX_POLL_INTERVAL_SEC)
    log.warning("Timed out waiting for Torbox to make %s available (account=%s)", info_hash, account_id)
    return find_by_id(account_id, torrent_id) if torrent_id else find_by_hash(account_id, info_hash)


def request_download_link(account_id: int, torrent_id: int, file_id: int, timeout: int = 15) -> str | None:
    """The CDN link for one file of a torrent in this account (requestdl)."""
    import torbox_pool
    acct = torbox_pool.account(account_id)
    if acct is None:
        return None
    url = f"{_base_url().rstrip('/')}/torrents/requestdl"
    params = {"token": acct.api_key, "torrent_id": torrent_id, "file_id": file_id, "zip_link": "false"}
    try:
        resp = requests.get(url, params=params, timeout=timeout)
        _check_auth(account_id, resp)
        resp.raise_for_status()
        return (resp.json() or {}).get("data") or None
    except Exception as exc:
        # Never str(exc): requests exceptions stringify with the full request
        # URL, which carries the API key in `token=`. Status code (when the
        # exception came from a response) plus the exception type is enough
        # to diagnose without leaking the key into the logs.
        status = getattr(getattr(exc, "response", None), "status_code", None)
        log.warning("requestdl failed account=%s torrent=%s file=%s: %s%s",
                    account_id, torrent_id, file_id, type(exc).__name__,
                    f" (status {status})" if status is not None else "")
        return None
