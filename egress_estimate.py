"""Estimated egress for the MKV redirect path.

MKV (and any non-MP4) playback is a 302 to the TorBox CDN, so no bytes pass
through Mycelium and the Go front has nothing to report. The Overview tile
would read near zero on an MKV library while TorBox's own meter is far
higher. This module records the file size once per play as an estimate.

One play, not one request: a player issues dozens to hundreds of Range
requests per viewing and every one of them resolves through the same
redirect branch. A redirect counts as a new play when the token has not
been resolved for PLAY_GAP_SEC. The map is in memory (gunicorn runs one
worker); a restart starts it fresh, so at worst one play that straddles a
restart is counted twice. Two viewers on the same title at once count as
one. Both errors are documented in docs/SCALING.md; the figure is an upper
bound per play (the whole file, even for a viewer who stops early).
"""
from __future__ import annotations

import logging
import threading
import time

import db

log = logging.getLogger(__name__)

PLAY_GAP_SEC = 2 * 3600

_lock = threading.Lock()
_last_seen: dict[str, float] = {}  # token -> monotonic of the last redirect


def note_redirect(token: str, size: int, now: float | None = None) -> bool:
    """Record `size` as estimated egress for `token` when this redirect
    starts a new play. Returns True when a row was written. A size of zero
    or less writes nothing but still marks the token as seen."""
    now = time.monotonic() if now is None else now
    with _lock:
        last = _last_seen.get(token)
        new_play = last is None or (now - last) >= PLAY_GAP_SEC
        _last_seen[token] = now
        if new_play:
            for stale in [t for t, seen in _last_seen.items() if now - seen >= PLAY_GAP_SEC and t != token]:
                _last_seen.pop(stale, None)
    if not new_play or size <= 0:
        return False
    try:
        db.record_egress_estimate(token, int(size))
    except Exception as exc:
        log.warning("egress estimate for token=%s not recorded: %s", token, exc)
        return False
    return True


def _reset() -> None:
    """Test seam: forget every token."""
    with _lock:
        _last_seen.clear()
