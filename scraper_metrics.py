"""Rolling per-scraper call timings for the admin Scrapers tab.

In-process and unpersisted by design: the app runs one gunicorn worker
(the in-process catbox locks already rely on that), and history that did
not survive a restart must read as unknown, never as an outage.
"""
import statistics
import threading
import time
from collections import deque

_MAX_SAMPLES = 50
_SLOW_MS = 1000
_DOWN_AFTER = 3

_lock = threading.Lock()
_samples: dict[str, deque] = {}


def reset() -> None:
    with _lock:
        _samples.clear()


def record(name: str, elapsed_ms: float, ok: bool) -> None:
    with _lock:
        _samples.setdefault(name, deque(maxlen=_MAX_SAMPLES)).append((elapsed_ms, ok))


def timed(name: str, fn):
    """Wrap a scraper fetch so its latency and outcome are recorded.

    Re-raises: merge_candidates counts failures itself, and a swallowed
    exception would read upstream as an empty success.
    """
    def run(*args, **kwargs):
        t0 = time.monotonic()
        try:
            out = fn(*args, **kwargs)
        except Exception:
            record(name, (time.monotonic() - t0) * 1000, False)
            raise
        record(name, (time.monotonic() - t0) * 1000, True)
        return out
    return run


def get_health(active: list[str]) -> list[dict]:
    out = []
    with _lock:
        for name in active:
            buf = list(_samples.get(name, ()))
            if not buf:
                out.append({"name": name, "latency_ms": None, "state": "unknown", "samples": 0})
                continue
            median = statistics.median(ms for ms, _ in buf)
            recent = [ok for _, ok in buf[-_DOWN_AFTER:]]
            if len(recent) == _DOWN_AFTER and not any(recent):
                state = "down"
            elif median >= _SLOW_MS:
                state = "slow"
            else:
                state = "ok"
            out.append({"name": name, "latency_ms": int(median), "state": state, "samples": len(buf)})
    return out
