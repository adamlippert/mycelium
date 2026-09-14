"""The two decisions /spore-stream makes before a byte is served.

They live here rather than in routes/stream.py because that module imports
the Flask blueprint (and appcore with it), which no test may import. Nothing
here touches the network, Flask or the clock: the caller passes in the probe,
the cache and the current time, so both decisions are testable at runtime.
"""


def link_is_alive(cdn_url: str, head_status, cache: dict, now: float,
                  ttl: float) -> bool:
    """Is the cached CDN link still worth handing to a client?

    A cache hit inside the TTL is trusted; otherwise probe once through
    `head_status(url) -> int`. A probe that raises counts as dead. Only a live
    answer refreshes the cache, so a dead link is probed again next time
    instead of being remembered as dead.
    """
    cached_until = cache.get(cdn_url)
    if cached_until and cached_until > now:
        return True
    try:
        alive = head_status(cdn_url) < 400
    except Exception:
        alive = False
    if alive:
        cache[cdn_url] = now + ttl
    return alive


def should_start_build(fsh_exists: bool, building_now: bool) -> bool:
    """Start the background .fsh build only when there is no cache yet and no
    earlier request already started one for this token."""
    return not fsh_exists and not building_now
