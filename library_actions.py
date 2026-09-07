"""Per-title actions behind the Library drawer and the bulk bar. Thin
wrappers over existing helpers; each returns {ok, message}, never raises,
and starts long work on a thread through _spawn so a request returns at
once."""
from __future__ import annotations

import logging
import re
import threading

import db

log = logging.getLogger(__name__)
_HASH = re.compile(r"^[0-9a-fA-F]{40}$")


def _spawn(target, name: str) -> None:
    threading.Thread(target=target, name=name, daemon=True).start()


def _req(imdb_id: str) -> dict | None:
    return db.get_request_by_imdb(imdb_id)


def _guard(fn):
    def wrapped(*a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as exc:
            log.warning("Library action %s failed: %s", fn.__name__, exc)
            return {"ok": False, "message": f"{fn.__name__} failed: {exc.__class__.__name__}"}
    wrapped.__name__ = fn.__name__
    return wrapped


@_guard
def mirror(imdb_id: str) -> dict:
    import arr_sync
    r = _req(imdb_id)
    if not r:
        return {"ok": False, "message": "unknown title"}
    ok = arr_sync.mirror_add(imdb_id, r["media_type"], r.get("tmdb_id"), r.get("title") or "")
    return {"ok": bool(ok), "message": "mirrored into the arr" if ok else "the arr did not accept it; see the log"}


@_guard
def unmirror(imdb_id: str) -> dict:
    import arr_sync
    r = _req(imdb_id)
    if not r:
        return {"ok": False, "message": "unknown title"}
    ok = arr_sync.mirror_remove(imdb_id, r["media_type"], r.get("tmdb_id"))
    return {"ok": bool(ok), "message": "removed from the arr" if ok else "the arr did not remove it; see the log"}


@_guard
def drop_retry(imdb_id: str) -> dict:
    row = db.get_retry_by_imdb(imdb_id)
    if not row:
        return {"ok": False, "message": "not in the retry queue"}
    db.remove_retry(row["id"])
    return {"ok": True, "message": "dropped from the retry queue"}


@_guard
def retry_now(imdb_id: str) -> dict:
    import processor
    from webhook_parser import MediaRequest
    r = _req(imdb_id)
    if not r:
        return {"ok": False, "message": "unknown title"}
    row = db.get_retry_by_imdb(imdb_id)
    if row:
        db.remove_retry(row["id"])
    seasons = [int(s) for s in (r.get("seasons") or "").split(",") if s.strip().isdigit()]
    req = MediaRequest(title=r["title"], media_type=r["media_type"], imdb_id=imdb_id, seasons=seasons,
                       tmdb_id=r.get("tmdb_id"))
    db.update_request(r["id"], "pending")
    _spawn(lambda: processor.process(req), f"retry-{imdb_id}")
    return {"ok": True, "message": "retry started"}


@_guard
def recheck_series(imdb_id: str) -> dict:
    import monitor
    series = db.get_monitored_series_by_imdb(imdb_id)
    if not series:
        return {"ok": False, "message": "not a monitored series"}
    _spawn(lambda: monitor._check_one_series(series), f"recheck-{imdb_id}")
    return {"ok": True, "message": "series check started"}


@_guard
def retry_episode(imdb_id: str, season: int, episode: int) -> dict:
    import monitor
    r = _req(imdb_id)
    if not r:
        return {"ok": False, "message": "unknown title"}
    _spawn(lambda: monitor.search_episode_now(imdb_id, r["title"], season, episode),
           f"episode-{imdb_id}-S{season:02d}E{episode:02d}")
    return {"ok": True, "message": f"searching S{season:02d}E{episode:02d}"}


@_guard
def blacklist(info_hash: str, note: str = "blacklisted by admin") -> dict:
    if not _HASH.match(info_hash or ""):
        return {"ok": False, "message": "not a valid info hash"}
    db.blacklist_hash(info_hash.lower(), note)
    return {"ok": True, "message": "hash blacklisted"}


@_guard
def unblacklist(info_hash: str) -> dict:
    if not _HASH.match(info_hash or ""):
        return {"ok": False, "message": "not a valid info hash"}
    db.clear_failed_hash(info_hash.lower())
    return {"ok": True, "message": "hash cleared"}


@_guard
def reset_playability(imdb_id: str) -> dict:
    n = db.reset_playability_for_title(imdb_id)
    return {"ok": True, "message": f"{n} record(s) reset"}


@_guard
def save_override(imdb_id: str, body: dict) -> dict:
    if not _req(imdb_id):
        return {"ok": False, "message": "unknown title"}
    def _b(v):
        return None if v is None else bool(v)
    db.upsert_show_override(imdb_id, (body.get("quality_preference") or None), _b(body.get("allow_4k")),
                            _b(body.get("prefer_hevc")), (body.get("notes") or None))
    return {"ok": True, "message": "override saved"}


@_guard
def clear_override(imdb_id: str) -> dict:
    db.delete_show_override(imdb_id)
    return {"ok": True, "message": "override cleared"}
