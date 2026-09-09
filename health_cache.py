"""Light-weight cached service-health probe.

Other modules call is_up(name) to decide whether to skip a service. Caches
results for HEALTH_CACHE_SECONDS so we never block a hot path on a probe.
"""
import logging
import threading
import time

import requests
from urllib.parse import quote

import settings as _settings
import torznab_scraper
from config import (
    HEALTH_CACHE_SECONDS,
    TORRENTIO_BASE_URL,
    ZILEAN_URL as _ZILEAN_URL_DEFAULT,
)

log = logging.getLogger(__name__)

_lock = threading.Lock()
_cache: dict[str, tuple[bool, float]] = {}


def _zilean_native() -> bool:
    return _settings.get("ZILEAN_MODE", "external") == "native"


def _probe(name: str) -> bool:
    try:
        if name == "zilean":
            if _zilean_native():
                # The native index is local SQLite: no URL exists to probe.
                # Down means the index database itself cannot be opened.
                import zilean_index
                zilean_index.get_status()
                return True
            zilean_url = _settings.get("ZILEAN_URL", _ZILEAN_URL_DEFAULT)
            if not zilean_url:
                return False
            r = requests.get(f"{zilean_url.rstrip('/')}/healthz", timeout=3)
            return r.status_code < 500
        if name == "torrentio":
            r = requests.get(f"{TORRENTIO_BASE_URL.rstrip('/')}/manifest.json", timeout=3)
            return r.status_code < 500
        if name == "debridio":
            import debridio
            token = debridio.build_config_token()
            if not token:
                return False
            base = (_settings.get("DEBRIDIO_BASE_URL", "https://addon.debridio.com") or "").rstrip("/")
            r = requests.get(f"{base}/{token}/manifest.json", timeout=3)
            # 401/403 (lapsed subscription) and 404 (garbled config token) are
            # permanent for this config, not transient upstream trouble.
            return (r.status_code < 500
                    and r.status_code not in debridio.DOWN_STATUS_CODES)
        if name in ("comet", "mediafusion"):
            key = "COMET_URL" if name == "comet" else "MEDIAFUSION_URL"
            default = "" if name == "comet" else "https://mediafusion.elfhosted.com"
            base = str(_settings.get(key, default) or "").rstrip("/")
            if not base:
                return False
            path = torznab_scraper.COMET_PATH if name == "comet" else torznab_scraper.MEDIAFUSION_PATH
            url = f"{base}{path}?t=caps"
            if name == "mediafusion":
                # I3: the probe must mirror the tester (service_tests.py's
                # test_mediafusion), or a correctly configured private
                # instance answers 401/403 to a keyless caps request forever
                # and _active() drops it from every search permanently. The
                # public instance ignores apikey, so this is safe by default.
                api_key = str(_settings.get("MEDIAFUSION_API_KEY", "") or "")
                if api_key:
                    url += f"&apikey={quote(api_key)}"
            r = requests.get(url, timeout=3)
            # 403 is what Comet's public instance answers on this path: a
            # misconfigured URL must show as down, not silently empty.
            return r.status_code < 400
    except Exception as exc:
        import debridio
        msg = debridio.redact(exc)
        if name in ("comet", "mediafusion"):
            msg = torznab_scraper.redact(msg)
        log.debug("health probe %s failed: %s", name, msg)
        return False
    return True


def peek(name: str) -> bool | None:
    """The last probe result for name, without ever probing: None only when
    nothing has been probed yet. A stale result is still returned, because
    the last known state beats "unknown" while a refresh is in flight; use
    stale_names() to learn what needs a refresh."""
    with _lock:
        cached = _cache.get(name)
    return cached[0] if cached else None


def stale_names(names: list[str]) -> list[str]:
    """The names with no cached probe or one older than HEALTH_CACHE_SECONDS."""
    now = time.monotonic()
    with _lock:
        return [n for n in names
                if n not in _cache or now - _cache[n][1] >= HEALTH_CACHE_SECONDS]


_refresh_lock = threading.Lock()
_refreshing = False


def refresh_async(names: list[str]) -> bool:
    """Probe the stale entries among names on one daemon thread, at most one
    refresh at a time. Returns True when a refresh was started. The admin
    Overview poll uses this so it never probes inline yet the next poll
    sees real states; app.py calls it once after boot to warm the cache."""
    global _refreshing
    todo = stale_names(list(names))
    if not todo:
        return False
    with _refresh_lock:
        if _refreshing:
            return False
        _refreshing = True

    def _run():
        global _refreshing
        try:
            for n in todo:
                try:
                    is_up(n)
                except Exception as exc:
                    log.debug("health refresh %s failed: %s", n, exc)
        finally:
            with _refresh_lock:
                _refreshing = False

    threading.Thread(target=_run, name="health-refresh", daemon=True).start()
    return True


def is_up(name: str) -> bool:
    if name == "zilean" and (
        not _settings.get("ZILEAN_ENABLED", False)
        # Native mode needs no URL; requiring one here silently skipped the
        # built-in index for every search and showed it as permanently down.
        or (not _zilean_native() and not _settings.get("ZILEAN_URL", _ZILEAN_URL_DEFAULT))
    ):
        return False
    if name == "debridio":
        import debridio
        if not _settings.get("DEBRIDIO_ENABLED", False) or not debridio.is_configured():
            return False
    now = time.monotonic()
    with _lock:
        cached = _cache.get(name)
        if cached and now - cached[1] < HEALTH_CACHE_SECONDS:
            return cached[0]
    ok = _probe(name)
    with _lock:
        _cache[name] = (ok, now)
    if not ok:
        log.warning("Service %s reported down; will skip for %ds", name, HEALTH_CACHE_SECONDS)
    return ok
