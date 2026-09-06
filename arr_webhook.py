"""Turn delete notifications from Radarr, Sonarr and the Jellyfin webhook
plugin into one shape the /webhook/arr route can act on.

Level A only acts on whole-title deletions. File-level events
(MovieFileDelete, EpisodeFileDelete) are accepted and ignored: Mycelium
titles have no files in the arrs until the Level B stub tree exists.
"""
import logging
import re
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

_PLACEHOLDER = re.compile(r"^\s*\{\{.*\}\}\s*$")
_IMDB = re.compile(r"^tt\d+$")


@dataclass
class DeleteEvent:
    imdb_id: str | None
    tmdb_id: int | None
    tvdb_id: int | None
    media_type: str      # "movie" or "series"
    source: str          # "radarr", "sonarr", "jellyfin"
    event: str


def _clean_imdb(raw) -> str | None:
    s = str(raw or "").strip()
    return s if _IMDB.match(s) else None


def _clean_int(raw) -> int | None:
    s = str(raw or "").strip()
    if not s or _PLACEHOLDER.match(s):
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _finish(ev: DeleteEvent) -> DeleteEvent:
    if not (ev.imdb_id or ev.tmdb_id or ev.tvdb_id):
        raise ValueError(f"{ev.source} {ev.event}: no imdb, tmdb or tvdb id in payload")
    return ev


def parse(payload: dict) -> DeleteEvent | None:
    """None when this is not a whole-title deletion we act on."""
    if not isinstance(payload, dict):
        return None
    event = str(payload.get("eventType") or "")
    if event == "MovieDelete":
        m = payload.get("movie") or {}
        return _finish(DeleteEvent(_clean_imdb(m.get("imdbId")), _clean_int(m.get("tmdbId")),
                                   None, "movie", "radarr", event))
    if event == "SeriesDelete":
        s = payload.get("series") or {}
        return _finish(DeleteEvent(_clean_imdb(s.get("imdbId")), _clean_int(s.get("tmdbId")),
                                   _clean_int(s.get("tvdbId")), "series", "sonarr", event))
    if event == "ItemDeleted":
        item_type = str(payload.get("itemType") or "")
        if item_type not in ("Movie", "Series"):
            log.info("Arr webhook: ignoring Jellyfin ItemDeleted for %s", item_type or "?")
            return None
        return _finish(DeleteEvent(_clean_imdb(payload.get("imdb")), _clean_int(payload.get("tmdb")),
                                   _clean_int(payload.get("tvdb")),
                                   "movie" if item_type == "Movie" else "series",
                                   "jellyfin", event))
    if event:
        log.info("Arr webhook: ignoring %s", event)
    return None


def files_still_present(items: list[dict]) -> bool:
    """True when any virtual_items row still has a strm_path that exists on disk.

    Used to tell a real Jellyfin deletion (the .strm is gone too, since Jellyfin
    and Mycelium share PUID) apart from the echo of our own targeted refresh
    reporting a repair/upgrade's old path as Deleted while a replacement .strm
    still exists for the same title."""
    for item in items:
        strm_path = item.get("strm_path")
        if strm_path and Path(strm_path).exists():
            return True
    return False


def resolve_imdb(ev: DeleteEvent) -> str | None:
    """imdb straight from the payload, else via TMDB, else via TVDB."""
    if ev.imdb_id:
        return ev.imdb_id
    import tmdb
    kind = "movie" if ev.media_type == "movie" else "tv"
    if ev.tmdb_id:
        found = tmdb.tmdb_to_imdb(ev.tmdb_id, media_type=kind)
        if found:
            return found
    if ev.tvdb_id:
        return tmdb.imdb_from_tvdb(ev.tvdb_id)
    return None
