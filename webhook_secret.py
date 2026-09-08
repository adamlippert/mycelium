"""The inbound webhook secret: which value is active, rotation, and the
grace window during which the previous value is still accepted.

One secret guards every inbound webhook (Seerr, TorBox, the arr and
Jellyfin delete hooks). It is WEBHOOK_SECRET from the environment when set,
otherwise the auto-generated value app.py stores under WEBHOOK_SECRET_AUTO
at startup. Rotation only applies to the auto-generated value: with the
environment variable set, the environment would win again on the next
restart, so rotate() refuses.

After a rotation the previous secret keeps working for GRACE_SEC so the
integrations can be updated one by one; each accepted use of it is logged
so the log shows which sender still carries the old value.
"""
from __future__ import annotations

import hmac
import logging
import secrets as _secrets
import time
from datetime import datetime, timezone

import config as cfg
import settings

log = logging.getLogger(__name__)

GRACE_SEC = 24 * 3600
KEY_AUTO = "WEBHOOK_SECRET_AUTO"
KEY_PREVIOUS = "WEBHOOK_SECRET_PREVIOUS"
KEY_PREVIOUS_UNTIL = "WEBHOOK_SECRET_PREVIOUS_UNTIL"

_now = time.time  # test seam


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(value) -> float | None:
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def source() -> str:
    return "env" if cfg.WEBHOOK_SECRET else "auto"


def effective() -> str:
    """The active secret: the environment variable when set, else the
    auto-generated one. Empty when neither exists (webhooks unguarded)."""
    return cfg.WEBHOOK_SECRET or str(settings.get(KEY_AUTO, "") or "")


def previous() -> tuple[str, float] | None:
    """(secret, expiry timestamp) of the previous value while its grace
    window is open; None otherwise. An expired pair is cleared on read."""
    old = str(settings.get(KEY_PREVIOUS, "") or "")
    until = _parse(settings.get(KEY_PREVIOUS_UNTIL, ""))
    if not old or until is None:
        return None
    if until <= _now():
        _clear_previous()
        return None
    return old, until


def _clear_previous() -> None:
    settings.set(KEY_PREVIOUS, None)
    settings.set(KEY_PREVIOUS_UNTIL, None)


def status() -> dict:
    prev = previous()
    return {
        "secret": effective(),
        "source": source(),
        "previous_valid_until": _iso(prev[1]) if prev else None,
    }


def rotate() -> dict:
    """Issue a new auto-generated secret. The current one becomes the
    previous value with a GRACE_SEC window. Raises RuntimeError when the
    secret comes from the environment."""
    if cfg.WEBHOOK_SECRET:
        raise RuntimeError("the webhook secret is set in the environment; change WEBHOOK_SECRET there")
    current = effective()
    new = _secrets.token_urlsafe(32)
    now = _now()
    if current:
        settings.set(KEY_PREVIOUS, current)
        settings.set(KEY_PREVIOUS_UNTIL, _iso(now + GRACE_SEC))
    settings.set(KEY_AUTO, new)
    log.info("Webhook secret rotated; the previous value stays valid until %s",
             _iso(now + GRACE_SEC) if current else "now")
    return status()


def accepts(provided: str | None) -> str | None:
    """'current' or 'previous' when `provided` matches an accepted secret,
    None otherwise. Comparisons are constant-time."""
    if not provided:
        return None
    current = effective()
    if current and hmac.compare_digest(provided, current):
        return "current"
    prev = previous()
    if prev and hmac.compare_digest(provided, prev[0]):
        return "previous"
    return None
