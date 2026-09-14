"""The TorBox account pool: several API keys as equal peers.

Account 1 is the configured TORBOX_API_KEY (its row mirrors the setting);
extra accounts live only in `torbox_accounts`. `choose_for_add()` picks the
least loaded healthy account for a new torrent; every later play of that
title uses the account recorded on the item. Health (last 429, last auth
failure) is process state, forgotten on restart, like the single
`_last_429_at` before the pool.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

import db
import settings

log = logging.getLogger(__name__)

EXCLUDE_WINDOW_SEC = 600      # a 429 or an auth failure keeps an account out of new adds this long
MIN_BUDGET_LEFT = 2           # fewer uncached adds left than this: not a candidate
_CACHE_TTL_SEC = 60.0


@dataclass(frozen=True)
class Account:
    id: int
    label: str
    api_key: str
    enabled: bool


_lock = threading.Lock()
_cache: dict = {"accounts": None, "ts": None}
# account id -> {"rate_limited_at": float | None, "auth_failed_at": float | None}
_health: dict[int, dict] = {}


def invalidate() -> None:
    with _lock:
        _cache["accounts"] = None
        _cache["ts"] = None


def _load() -> list[Account]:
    rows = db.list_torbox_accounts()
    out = []
    for r in rows:
        key = r["api_key"]
        if r["id"] == 1:
            key = settings.get("TORBOX_API_KEY", "") or key
        out.append(Account(id=int(r["id"]), label=r["label"], api_key=key, enabled=bool(r["enabled"])))
    return out


def accounts(enabled_only: bool = True) -> list[Account]:
    with _lock:
        ts = _cache["ts"]
        if _cache["accounts"] is None or ts is None or time.monotonic() - ts > _CACHE_TTL_SEC:
            _cache["accounts"] = _load()
            _cache["ts"] = time.monotonic()
        all_accounts = list(_cache["accounts"])
    return [a for a in all_accounts if a.enabled] if enabled_only else all_accounts


def account(account_id: int) -> Account | None:
    for a in accounts(enabled_only=False):
        if a.id == account_id:
            return a
    return None


def any_key() -> str:
    """A key for calls that are not bound to an account (cache checks)."""
    enabled = accounts()
    return enabled[0].api_key if enabled else ""


def find_hash_anywhere(info_hash: str) -> tuple[int, dict] | None:
    """The first enabled account whose library already holds this hash, and
    the TorBox item there  -  so an add path checks every account, not just
    the one choose_for_add() would pick, before spending a createtorrent
    slot re-adding a torrent another account already holds. An account
    whose key has been revoked (AuthFailed) is skipped rather than hiding a
    hit that sits in another account."""
    import torbox
    for a in accounts():
        try:
            item = torbox.find_by_hash(a.id, info_hash)
        except torbox.AuthFailed:
            continue
        if item:
            return a.id, item
    return None


def mark_429(account_id: int) -> None:
    _health.setdefault(account_id, {})["rate_limited_at"] = time.time()


def mark_auth_failure(account_id: int) -> None:
    _health.setdefault(account_id, {})["auth_failed_at"] = time.time()


def _budget_left(account_id: int) -> int:
    import torbox
    try:
        return max(0, torbox._CREATETORRENT_LIMIT_HOUR - torbox.createtorrent_usage(account_id)["count"])
    except Exception as exc:
        log.debug("budget for account %s unavailable: %s", account_id, exc)
        return 0


def health(account_id: int) -> dict:
    h = _health.get(account_id, {})
    limited = h.get("rate_limited_at")
    return {
        "rate_limited_until": (limited + EXCLUDE_WINDOW_SEC) if limited else None,
        "auth_failed_at": h.get("auth_failed_at"),
        "budget_left": _budget_left(account_id),
        "torrents": db.count_items_by_account().get(account_id, 0),
    }


def _excluded(a: Account, now: float) -> str | None:
    h = _health.get(a.id, {})
    if h.get("rate_limited_at") and now - h["rate_limited_at"] < EXCLUDE_WINDOW_SEC:
        return "rate limited"
    if h.get("auth_failed_at") and now - h["auth_failed_at"] < EXCLUDE_WINDOW_SEC:
        return "auth failure"
    if _budget_left(a.id) < MIN_BUDGET_LEFT:
        return "no budget"
    return None


def choose_for_add() -> Account:
    """The account a new torrent goes to. Candidates are the enabled
    accounts minus those rate limited or auth-failed in the last ten
    minutes and those with fewer than two uncached adds left; the winner
    holds the fewest torrents, ties by most budget left, then lowest id.
    With no candidate at all the account whose 429 is oldest is returned,
    so a burst degrades to a 429 and today's cooldown, never a hard fail."""
    enabled = accounts()
    if not enabled:
        raise RuntimeError("no enabled TorBox account")
    now = time.time()
    reasons = {a.id: _excluded(a, now) for a in enabled}
    candidates = [a for a in enabled if reasons[a.id] is None]
    if candidates:
        counts = db.count_items_by_account()
        chosen = min(candidates, key=lambda a: (counts.get(a.id, 0), -_budget_left(a.id), a.id))
        log.info("TorBox pool: %s for the next add (%d torrents, %d adds left)",
                 chosen.label, counts.get(chosen.id, 0), _budget_left(chosen.id))
        return chosen
    chosen = min(enabled, key=lambda a: (_health.get(a.id, {}).get("rate_limited_at") or 0.0, a.id))
    log.warning("TorBox pool: every account excluded (%s); falling back to %s",
                ", ".join(f"{a.label}: {reasons[a.id]}" for a in enabled), chosen.label)
    return chosen
