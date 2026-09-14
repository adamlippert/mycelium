import logging

import requests

import config
import settings
from config import TORRENTIO_BASE_URL

log = logging.getLogger(__name__)


def _s(key: str) -> str:
    """Settings DB value with env/config fallback, trimmed."""
    return (settings.get(key, getattr(config, key, "")) or "").strip()


def _ping(name: str, url: str, headers: dict | None = None, timeout: int = 5,
          redact=None, down_codes: tuple[int, ...] = ()) -> dict:
    try:
        r = requests.get(url, headers=headers or {}, timeout=timeout)
        ok = r.status_code < 500 and r.status_code not in down_codes
        return {"name": name, "status": "ok" if ok else "down", "code": r.status_code}
    except Exception as exc:
        msg = str(exc)
        if redact is not None:
            msg = redact(msg)
        return {"name": name, "status": "down", "error": msg[:80]}


# Per-library Jellyfin options that open every file. On a .strm library each
# one pulls the whole title through the TorBox CDN and resets its retention.
_EXTRACTION_OPTIONS = (
    ("EnableTrickplayImageExtraction", "trickplay"),
    ("ExtractTrickplayImagesDuringLibraryScan", "trickplay"),
    ("EnableChapterImageExtraction", "chapter images"),
    ("ExtractChapterImagesDuringLibraryScan", "chapter images"),
)
_ADD_BUDGET_WARN_AT = 45


def _jellyfin_libraries_row(jellyfin_url: str, jellyfin_key: str) -> dict | None:
    """Which Jellyfin libraries sit on Mycelium's media, and whether any of
    them has image extraction on. None when the options cannot be read; the
    Jellyfin ping row already says whether Jellyfin is reachable."""
    try:
        import jellyfin
        r = requests.get(f"{jellyfin_url.rstrip('/')}/Library/VirtualFolders",
                         headers=jellyfin.auth_headers(jellyfin_key), timeout=5)
        if r.status_code >= 400:
            return None
        libraries = r.json() or []
    except Exception as exc:
        log.debug("Jellyfin library options unavailable: %s", exc)
        return None
    media_root = (_s("JELLYFIN_MEDIA_PATH") or config.MEDIA_PATH).rstrip("/")
    ours: list[dict] = []
    for lib in libraries:
        locations = lib.get("Locations") or []
        if any(loc == media_root or str(loc).startswith(media_root + "/") for loc in locations):
            ours.append(lib)
    if not ours:
        return {"name": "Jellyfin libraries", "status": "warn",
                "note": f"no library points at {media_root}; set JELLYFIN_MEDIA_PATH if Jellyfin mounts it elsewhere"}
    offenders = []
    for lib in ours:
        opts = lib.get("LibraryOptions") or {}
        on = []
        for key, label in _EXTRACTION_OPTIONS:
            if opts.get(key) and label not in on:
                on.append(label)
        if on:
            offenders.append(f"{lib.get('Name') or '?'}: {', '.join(on)}")
    if offenders:
        return {"name": "Jellyfin libraries", "status": "warn",
                "note": "; ".join(offenders) + " (each pulls every file through the CDN; turn off for .strm libraries)"}
    n = len(ours)
    return {"name": "Jellyfin libraries", "status": "ok",
            "note": f"{n} librar{'y' if n == 1 else 'ies'}, extraction off"}


def _torbox_budget_row(account, multi: bool) -> dict | None:
    """Uncached TorBox adds used this hour against the 60/hour limit, for one
    account. Cached adds are shown but do not count: TorBox only limits
    uncached ones. With a single enabled account the row keeps the name it
    has always had ("TorBox adds this hour"); with two or more, the label
    is appended so each account gets its own row."""
    try:
        import torbox
        usage = torbox.createtorrent_usage(account.id)
        count, limit = int(usage.get("count", 0)), int(usage.get("limit", 60) or 60)
        cached = int(usage.get("cached_count", 0) or 0)
    except Exception as exc:
        log.debug("TorBox add budget unavailable (%s): %s", account.label, exc)
        return None
    name = f"TorBox adds this hour ({account.label})" if multi else "TorBox adds this hour"
    note = f"{count}/{limit} uncached"
    if cached:
        note += f", {cached} cached (not limited)"
    if count >= _ADD_BUDGET_WARN_AT:
        note += " used; auto-requesters (Suggestarr, Trakt, MDBList, auto-approve) share this budget"
        return {"name": name, "status": "warn", "note": note}
    return {"name": name, "status": "ok", "note": note}


def _account_ping_headers(account) -> dict:
    """Falls back to an empty header (a doomed ping, not a crash) when the
    key can't be read at all, the way settings.get() already degrades
    elsewhere."""
    try:
        import torbox
        return torbox._headers(account.id)
    except Exception as exc:
        log.debug("TorBox ping headers unavailable (%s): %s", account.label, exc)
        return {}


def check_all() -> list[dict]:
    services = []
    import torbox_pool
    try:
        accounts = torbox_pool.accounts()
    except Exception as exc:
        log.debug("TorBox account pool unavailable: %s", exc)
        accounts = []
    # A single-key install keeps the plain "TorBox" name it has always had;
    # two or more enabled accounts each get their own labelled row, pinged
    # with their own key, so one account's 401/403 does not hide behind the
    # others' green pings.
    multi = len(accounts) > 1
    for account in accounts:
        name = f"TorBox {account.label}" if multi else "TorBox"
        services.append(_ping(
            name,
            f"{_s('TORBOX_BASE_URL').rstrip('/')}/torrents/mylist",
            headers=_account_ping_headers(account),
            down_codes=(401, 403),
        ))
        budget = _torbox_budget_row(account, multi)
        if budget:
            services.append(budget)
    if settings.get("ZILEAN_ENABLED", False):
        if settings.get("ZILEAN_MODE", "external") == "native":
            # Built-in SQLite index: nothing to ping. Down means the index
            # database itself cannot be opened.
            try:
                import zilean_index
                n = zilean_index.get_status().get("total_hashes", 0)
                services.append({"name": "Zilean", "status": "ok",
                                 "note": f"native index, {n} hashes"})
            except Exception:
                services.append({"name": "Zilean", "status": "down",
                                 "note": "native index unavailable"})
        else:
            services.append(_ping("Zilean", f"{_s('ZILEAN_URL').rstrip('/')}/healthz"))
    else:
        services.append({"name": "Zilean", "status": "disabled"})
    services.append(_ping("Torrentio", f"{TORRENTIO_BASE_URL.rstrip('/')}/manifest.json"))
    import debridio as _debridio
    if settings.get("DEBRIDIO_ENABLED", False) and _debridio.is_configured():
        base = _s("DEBRIDIO_BASE_URL").rstrip("/") or "https://addon.debridio.com"
        # Debridio is the only scraper with an auth failure mode: a lapsed
        # subscription answers 401/403 and a garbled config token 404. All are
        # < 500, so the generic predicate would report a dead addon as healthy
        # and every search would keep paying a round trip for nothing.
        entry = _ping("Debridio", f"{base}/{_debridio.build_config_token()}/manifest.json",
                      redact=_debridio.redact,
                      down_codes=_debridio.DOWN_STATUS_CODES)
        services.append(entry)
    else:
        services.append({"name": "Debridio", "status": "disabled"})
    tmdb_api_key = _s("TMDB_API_KEY")
    if tmdb_api_key:
        services.append(_ping(
            "TMDB",
            "https://api.themoviedb.org/3/configuration",
            headers={"Authorization": f"Bearer {tmdb_api_key}", "Accept": "application/json"},
        ))
    else:
        services.append({"name": "TMDB", "status": "disabled"})
    jellyfin_url = _s("JELLYFIN_URL")
    if jellyfin_url:
        import jellyfin
        jellyfin_key = _s("JELLYFIN_API_KEY")
        # With a key, ping the authenticated endpoint so a rejected key
        # (Jellyfin 12 refusing the legacy header, a revoked key) shows as
        # down instead of a green 401. Without one, plain reachability.
        services.append(_ping(
            "Jellyfin",
            f"{jellyfin_url.rstrip('/')}/System/Info" + ("" if jellyfin_key else "/Public"),
            headers=jellyfin.auth_headers(jellyfin_key),
            down_codes=(401, 403) if jellyfin_key else (),
        ))
        libraries = _jellyfin_libraries_row(jellyfin_url, jellyfin_key)
        if libraries:
            services.append(libraries)
    seerr_url = _s("SEERR_URL")
    if seerr_url:
        seerr_key = _s("SEERR_API_KEY")
        services.append(_ping(
            "Seerr",
            f"{seerr_url.rstrip('/')}/api/v1/status",
            headers={"X-Api-Key": seerr_key} if seerr_key else {},
        ))
    import arr_stubs
    if arr_stubs.is_enabled():
        ok, note = arr_stubs.root_status()
        services.append({"name": "Arr stubs", "status": "ok" if ok else "down", "note": note})
    else:
        services.append({"name": "Arr stubs", "status": "disabled"})
    return services
