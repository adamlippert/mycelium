"""Stub files for Radarr and Sonarr (the "Level B" arr integration).

The arrs never import .strm files, so a mirrored title shows as Missing.
This module writes one tiny MKV per .strm into a folder tree the arrs mount
as their root folder: the same EBML header Spore builds for Plex, with a
Segment Duration from the TMDB runtime so MediaInfo reports a runtime and
the arrs' sample detection accepts it. The file name carries the quality
Mycelium actually found (truthful naming), which the arrs parse.

Mycelium writes into the folder the arr chose for the title (its naming
format is respected) and marks each folder with a `.mycelium` file holding
the imdb id, so removal can find the folder even if the arr renamed it or
is unreachable. Nothing here raises into the pipeline.

Paths: ARR_STUB_PATH is Mycelium's mount of the shared folder; the arr's
mount of <ARR_STUB_PATH>/movies and /series is RADARR_ROOT_FOLDER and
SONARR_ROOT_FOLDER. local_dir() translates one into the other.
"""
import logging
import shutil
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import db
import release_tags
import settings as _settings

log = logging.getLogger(__name__)

MARKER = ".mycelium"
_IGNORE = ".ignore"

# release_tags source -> the arr's quality source word. Anything else is
# left off and the resolution alone is used, which the arrs still parse.
_SOURCE_WORD = {
    "remux": "Remux",
    "bluray": "Bluray", "bdrip": "Bluray", "brrip": "Bluray",
    "webdl": "WEBDL", "web": "WEBDL",
    "webrip": "WEBRip",
    "hdtv": "HDTV", "satrip": "HDTV", "tvrip": "HDTV",
    "dvdrip": "DVD", "dvd": "DVD",
}
_KIND_DIR = {"movie": "movies", "series": "series"}


def is_enabled() -> bool:
    return bool(_settings.get("ARR_STUBS_ENABLED", False)) and bool(_settings.get("ARR_SYNC_ENABLED", False))


def _root() -> Path:
    return Path((_settings.get("ARR_STUB_PATH", "/arr-stubs") or "/arr-stubs").strip())


def root_status() -> tuple[bool, str]:
    """(ok, note). The mount point is never created by Mycelium: a missing
    directory means the bind mount is absent, and creating it would hide
    that behind an empty tree the arrs cannot see."""
    root = _root()
    if not root.is_dir():
        return False, f"{root} not mounted"
    try:
        (root / _IGNORE).touch(exist_ok=True)
    except OSError as exc:
        return False, f"{root} not writable: {exc}"
    return True, str(root)


def _kind(media_type: str) -> str:
    return "movie" if media_type == "movie" else "series"


def _arr_root(kind: str) -> str:
    key = "RADARR_ROOT_FOLDER" if kind == "movie" else "SONARR_ROOT_FOLDER"
    return (_settings.get(key, "") or "").strip().rstrip("/")


def local_dir(kind: str, arr_path: str) -> Path | None:
    """The arr's folder for a title, as Mycelium sees it. None when the path
    is outside the configured arr root or tries to escape it."""
    arr_root = _arr_root(kind)
    if not arr_root or not arr_path:
        return None
    arr_path = arr_path.rstrip("/")
    if arr_path != arr_root and not arr_path.startswith(arr_root + "/"):
        return None
    rel = Path(arr_path[len(arr_root):].lstrip("/"))
    if not rel.parts or any(p in ("..", "") for p in rel.parts):
        return None
    return _root() / _KIND_DIR[kind] / rel


def quality_tag(resolution: str | None, release_name: str) -> str:
    """`WEBDL-1080p`, `Bluray-2160p`, or the resolution alone."""
    res = (resolution or "").strip()
    if res.lower() == "unknown":
        res = ""
    word = ""
    for source in release_tags.detect_sources(release_name or ""):
        if source in _SOURCE_WORD:
            word = _SOURCE_WORD[source]
            break
    if word and res:
        return f"{word}-{res}"
    return word or res


def stub_name(strm_path: Path, tag: str) -> str:
    return f"{strm_path.stem} - {tag}.mkv" if tag else f"{strm_path.stem}.mkv"


def _release_name(magnet: str) -> str:
    try:
        return parse_qs(urlparse(magnet or "").query).get("dn", [""])[0]
    except Exception:
        return ""


def _duration(imdb_id: str, item: dict) -> float:
    import tmdb
    try:
        season, episode = item.get("season"), item.get("episode")
        if season and episode:
            dur = tmdb.get_episode_runtime_sec(imdb_id, season, episode)
        else:
            dur = tmdb.get_movie_runtime_sec(imdb_id)
        if dur and dur > 60:
            return float(dur)
    except Exception as exc:
        log.debug("Arr stubs: runtime lookup for %s failed: %s", imdb_id, exc)
    return 7200.0


def write_title(imdb_id: str, media_type: str, arr_path: str) -> int:
    """Write the title's stubs into the arr's folder; returns how many were
    written. Stale stubs (an older quality tag) in the same folders are
    removed. 0 when disabled, unmounted, or nothing to do."""
    if not is_enabled():
        return 0
    ok, note = root_status()
    if not ok:
        log.warning("Arr stubs: %s", note)
        return 0
    kind = _kind(media_type)
    folder = local_dir(kind, arr_path)
    if folder is None:
        log.warning("Arr stubs: %s is outside the %s root folder; skipping %s", arr_path, kind, imdb_id)
        return 0
    items = [i for i in db.get_virtual_items_by_imdb(imdb_id) if i.get("strm_path")]
    if not items:
        return 0
    req = db.get_request_by_imdb(imdb_id) or {}
    title = req.get("title") or items[0].get("title") or imdb_id
    written = 0
    wanted: dict[Path, set[str]] = {}
    for item in items:
        strm = Path(item["strm_path"])
        # Per-item quality first (episodes of one show can differ), the
        # request row's as the fallback.
        tag = quality_tag(item.get("quality") or req.get("quality"),
                          _release_name(item.get("magnet") or ""))
        target_dir = folder
        if kind == "series" and strm.parent.name.lower().startswith("season"):
            target_dir = folder / strm.parent.name
        wanted.setdefault(target_dir, set()).add(stub_name(strm, tag))
        target = target_dir / stub_name(strm, tag)
        if target.exists():
            continue
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            import strm_generator
            target.write_bytes(strm_generator.make_stub_mkv(
                title, req.get("quality"), duration_sec=_duration(imdb_id, item)))
            written += 1
        except Exception as exc:
            log.warning("Arr stubs: could not write %s: %s", target, exc)
    try:
        (folder / MARKER).write_text(imdb_id + "\n", encoding="utf-8")
    except OSError as exc:
        log.warning("Arr stubs: could not mark %s: %s", folder, exc)
    for target_dir, names in wanted.items():
        for stale in target_dir.glob("*.mkv"):
            if stale.name not in names:
                try:
                    stale.unlink()
                except OSError as exc:
                    log.warning("Arr stubs: could not remove stale %s: %s", stale, exc)
    if written:
        log.info("Arr stubs: wrote %d stub(s) for %s in %s", written, imdb_id, folder)
    return written


def _is_ours(folder: Path, imdb_id: str) -> bool:
    try:
        return (folder / MARKER).read_text(encoding="utf-8").strip() == imdb_id
    except OSError:
        return False


def remove_title(media_type: str, imdb_id: str, arr_path: str | None = None) -> int:
    """Delete the title's stub folder(s). Only folders carrying our marker
    with this imdb id are touched, so a foreign folder under the same name
    survives. Returns folders removed."""
    if not is_enabled():
        return 0
    kind = _kind(media_type)
    candidates: list[Path] = []
    if arr_path:
        direct = local_dir(kind, arr_path)
        if direct is not None:
            candidates.append(direct)
    kind_root = _root() / _KIND_DIR[kind]
    if kind_root.is_dir():
        candidates.extend(p for p in kind_root.iterdir() if p.is_dir())
    removed = 0
    seen: set[Path] = set()
    for folder in candidates:
        if folder in seen or not folder.is_dir() or not _is_ours(folder, imdb_id):
            continue
        seen.add(folder)
        try:
            shutil.rmtree(folder)
            removed += 1
        except OSError as exc:
            log.warning("Arr stubs: could not remove %s: %s", folder, exc)
    if removed:
        log.info("Arr stubs: removed %d folder(s) for %s", removed, imdb_id)
    return removed
