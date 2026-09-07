"""Stub files for Radarr and Sonarr (the "Level B" arr integration).

The arrs never import .strm files, so a mirrored title shows as Missing.
This module writes one tiny MKV per .strm into a folder tree the arrs mount
as their root folder: the same EBML header Spore builds for Plex, with a
Segment Duration from the TMDB runtime so MediaInfo reports a runtime and
the arrs' sample detection accepts it. The file name carries the quality
Mycelium actually found (truthful naming), which the arrs parse.

Mycelium writes into the folder the arr chose for the title: the arr's
naming format is respected for the title folder, and season subfolders
follow Mycelium's `.strm` layout. Each folder is marked with a `.mycelium`
file holding the imdb id, so removal can find the folder even if the arr
renamed it or is unreachable. Nothing here raises into the pipeline.

Paths: ARR_STUB_PATH is Mycelium's mount of the shared folder; the arr's
mount of <ARR_STUB_PATH>/movies and /series is RADARR_ROOT_FOLDER and
SONARR_ROOT_FOLDER. local_dir() translates one into the other.
"""
import logging
import re
import shutil
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import db
import release_tags
import settings as _settings

log = logging.getLogger(__name__)

MARKER = ".mycelium"
_IGNORE = ".ignore"
_STUB_MAGIC = b"\x1a\x45\xdf\xa3"
_STUB_MAX_SIZE = 64 * 1024
_SXXEXX = re.compile(r"S\d{1,2}E\d{1,3}")

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
    raw = (_settings.get("ARR_STUB_PATH", "/arr-stubs") or "").strip()
    return Path(raw or "/arr-stubs")


def root_status() -> tuple[bool, str]:
    """(ok, note). The mount point is never created by Mycelium: a missing
    directory means the bind mount is absent, and creating it would hide
    that behind an empty tree the arrs cannot see. Stubs are built from
    catbox virtual items, so CATBOX_MODE is required too. A root folder is
    only required for an arr that is actually configured (its URL setting
    is non-blank): a single-arr deployment must not be locked out because
    the other arr's root folder was never set."""
    root = _root()
    if not root.is_absolute():
        return False, f"{root} is not an absolute path"
    if not root.is_dir():
        return False, f"{root} not mounted"
    try:
        (root / _IGNORE).touch(exist_ok=True)
    except OSError as exc:
        return False, f"{root} not writable: {exc}"
    if not _settings.get("CATBOX_MODE", False):
        return False, "stub files need CATBOX_MODE (they are built from virtual items)"
    if (_settings.get("RADARR_URL", "") or "").strip() and not (_settings.get("RADARR_ROOT_FOLDER", "") or "").strip():
        return False, "RADARR_ROOT_FOLDER not set"
    if (_settings.get("SONARR_URL", "") or "").strip() and not (_settings.get("SONARR_ROOT_FOLDER", "") or "").strip():
        return False, "SONARR_ROOT_FOLDER not set"
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


def _resolve_duration(imdb_id: str, kind: str, items: list[dict]) -> float:
    """One TMDB lookup per write_title() call, reused for every stub it
    writes: a movie's runtime, or a series' first item's episode runtime.
    Per-item TMDB calls would make reconcile (one write_title per title)
    uncached and expensive."""
    import tmdb
    try:
        if kind == "series" and items:
            season, episode = items[0].get("season"), items[0].get("episode")
            dur = tmdb.get_episode_runtime_sec(imdb_id, season, episode)
        else:
            dur = tmdb.get_movie_runtime_sec(imdb_id)
        if dur and dur > 60:
            return float(dur)
    except Exception as exc:
        log.debug("Arr stubs: runtime lookup for %s failed: %s", imdb_id, exc)
    return 7200.0


def _looks_like_our_stub(path: Path) -> bool:
    """True when path is small and starts with the EBML magic Mycelium (and
    Spore) write stub MKVs with. Used to keep the stale-stub sweep from ever
    touching a real file in a misconfigured root. False on any OSError."""
    try:
        if path.stat().st_size >= _STUB_MAX_SIZE:
            return False
        with path.open("rb") as f:
            return f.read(4) == _STUB_MAGIC
    except OSError:
        return False


def _equivalent(target_dir: Path, stem: str, tag: str) -> Path | None:
    """An existing stub in target_dir that already represents this title
    (possibly renamed by the arr's "Rename Files"): one of our stubs whose
    name carries the wanted quality tag as a whole token, and, for an
    episode, the same SxxExx token as the strm stem. None when nothing
    matches, so the caller writes a fresh one.

    An empty tag never shortcuts (quality_tag() returns "" for an unknown
    resolution, and "" is a substring of everything). A bare resolution
    tag ("1080p") must not match inside a more specific "Source-Resolution"
    tag ("WEBDL-1080p"): that would make a stale, more specific stub look
    equivalent to a newly-unknown one and keep it as current."""
    if not tag or not target_dir.is_dir():
        return None
    ep_match = _SXXEXX.search(stem)
    ep_token = ep_match.group(0) if ep_match else None
    tag_re = re.compile(r"(?<![A-Za-z0-9])" + re.escape(tag) + r"(?![A-Za-z0-9])")
    full_tag = "-" in tag
    for candidate in target_dir.glob("*.mkv"):
        if not _looks_like_our_stub(candidate):
            continue
        m = tag_re.search(candidate.name)
        if not m:
            continue
        if not full_tag and m.start() > 0 and candidate.name[m.start() - 1] == "-":
            continue
        if ep_token and ep_token not in candidate.name:
            continue
        return candidate
    return None


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
    import strm_generator
    try:
        items = [i for i in db.get_virtual_items_by_imdb(imdb_id)
                if i.get("strm_path") and Path(i["strm_path"]).exists()]
    except Exception as exc:
        log.warning("Arr stubs: could not read virtual items for %s: %s", imdb_id, exc)
        return 0
    if not items:
        log.debug("Arr stubs: no virtual items for %s; nothing to write", imdb_id)
        return 0
    try:
        req = db.get_request_by_imdb(imdb_id) or {}
    except Exception as exc:
        log.warning("Arr stubs: could not read request for %s: %s", imdb_id, exc)
        return 0
    title = req.get("title") or items[0].get("title") or imdb_id
    duration = _resolve_duration(imdb_id, kind, items)
    written = 0
    wanted: dict[Path, set[str]] = {}
    for item in items:
        strm = Path(item["strm_path"])
        # Per-item quality first (episodes of one show can differ), the
        # request row's as the fallback. Used for both the file name and
        # the stub's own embedded quality so they never disagree.
        quality = item.get("quality") or req.get("quality")
        tag = quality_tag(quality, _release_name(item.get("magnet") or ""))
        target_dir = folder
        if kind == "series" and strm.parent.name.lower().startswith("season"):
            target_dir = folder / strm.parent.name
        target = target_dir / stub_name(strm, tag)
        if target.exists():
            wanted.setdefault(target_dir, set()).add(target.name)
            continue
        existing = _equivalent(target_dir, strm.stem, tag)
        if existing is not None:
            # Already present, possibly under a name the arr's own "Rename
            # Files" gave it: keep it, do not rewrite it on every reconcile.
            wanted.setdefault(target_dir, set()).add(existing.name)
            continue
        wanted.setdefault(target_dir, set()).add(target.name)
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            target.write_bytes(strm_generator.make_stub_mkv(
                title, quality, duration_sec=duration))
            written += 1
        except Exception as exc:
            log.warning("Arr stubs: could not write %s: %s", target, exc)
    try:
        (folder / MARKER).write_text(imdb_id + "\n", encoding="utf-8")
    except OSError as exc:
        log.warning("Arr stubs: could not mark %s: %s", folder, exc)
    for target_dir, names in wanted.items():
        for stale in target_dir.glob("*.mkv"):
            if stale.name in names:
                continue
            if not _looks_like_our_stub(stale):
                # Not one of ours (a real file in a misconfigured root, or
                # anything else): never touch it.
                continue
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
    except Exception:
        return False


def remove_title(media_type: str, imdb_id: str, arr_path: str | None = None) -> int:
    """Delete the title's stub folder(s). Only folders carrying our marker
    with this imdb id are touched, so a foreign folder under the same name
    survives. Returns folders removed."""
    if not is_enabled():
        return 0
    if not _root().is_absolute():
        log.warning("Arr stubs: %s is not an absolute path", _root())
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
