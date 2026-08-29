"""Shared stream model, parsing helpers and ranking for all scrapers.

Zilean, Torrentio and Debridio all produce Stream objects and are ranked by
the same function. That function used to live in torrentio.py, which made it
look Torrentio-specific; it never was.
"""
import logging
import re
from dataclasses import dataclass

from config import (
    ALLOW_4K,
    AUDIO_LANGUAGE_PREFERENCE,
    EXCLUDE_BLURAY,
    EXCLUDE_CAM,
    EXCLUDE_DV_P5,
    EXCLUDE_LANGUAGES,
    EXCLUDE_REMUX,
    EXCLUDE_UNDERSIZED_RELEASES,
    MAX_SIZE_GB,
    MIN_SEEDERS,
    PREFER_HEVC,
    PREFER_WEBDL,
    QUALITY_PREFERENCE,
)

log = logging.getLogger(__name__)

_QUALITY_PATTERNS = {
    "2160p": re.compile(r"\b(2160p|4k|uhd)\b", re.IGNORECASE),
    "1080p": re.compile(r"\b1080p\b", re.IGNORECASE),
    "720p": re.compile(r"\b720p\b", re.IGNORECASE),
    "480p": re.compile(r"\b480p\b", re.IGNORECASE),
}
_SEEDERS_RE = re.compile(r"👤\s*(\d+)")
_SIZE_RE = re.compile(r"💾\s*([\d.]+)\s*(GB|MB)", re.IGNORECASE)

_REMUX_RE = re.compile(r"\b(remux|bdremux)\b", re.IGNORECASE)
_BLURAY_RE = re.compile(r"\b(bluray|blu-ray|bdrip|brrip)\b", re.IGNORECASE)
_CAM_RE = re.compile(r"\b(cam|camrip|hdcam|ts|telesync|hdts|scr|screener|dvdscr|workprint|r5)\b", re.IGNORECASE)
_WEBDL_RE = re.compile(r"\b(web-?dl|webrip|web)\b", re.IGNORECASE)
_HEVC_RE  = re.compile(r"\b(hevc|x265|h\.?265)\b", re.IGNORECASE)
# Dolby Vision without an HDR10 base layer (Profile 5). The release name has
# DV/DoVi but no HDR10 keyword alongside it. Profile 8 (DV + HDR10) is safe
# and is NOT matched here.
_DV_RE    = re.compile(r"\b(dovi|dolby[\s.]?vision|\.dv\.)\b", re.IGNORECASE)
_HDR10_RE = re.compile(r"\bhdr10(?!\+)\b", re.IGNORECASE)

# Some release groups mislabel a cam/trailer/junk file as a much higher
# quality than it really is (title says "2160p" or doesn't mention "CAM" at
# all), so no title regex catches it. A real recording at a given resolution
# has a physical minimum size for its runtime; below this it's not actually
# that quality (or not actually the full movie at all). Expressed as GB per
# 90 minutes of runtime, scaled by the title's real (TMDB) runtime.
_MIN_GB_PER_90MIN = {
    "2160p": 3.0,
    "1080p": 1.1,
    "720p": 0.7,
    "480p": 0.4,
}


def _min_plausible_size_gb(quality: str, runtime_minutes: float | None) -> float:
    floor = _MIN_GB_PER_90MIN.get(quality)
    if not floor or not runtime_minutes or runtime_minutes <= 0:
        return 0.0
    return floor * (runtime_minutes / 90.0)


def parse_quality(text: str) -> str:
    """Highest-resolution bucket named in the text, or 'unknown' if none.

    'unknown' rather than '': the label lands in the quality_added metric, and
    two spellings of the same thing split the dashboard's Quality card in two.
    Zilean and Torrentio already said 'unknown', so that is the spelling.
    """
    for quality, pattern in _QUALITY_PATTERNS.items():
        if pattern.search(text or ""):
            return quality
    return "unknown"


def parse_size_gb(text: str) -> float:
    """Size in GB from a '💾 5.2 GB' marker. 0.0 when absent or unparseable."""
    m = _SIZE_RE.search(text or "")
    if not m:
        return 0.0
    value = float(m.group(1))
    # 1024, not 1000: matches torrentio._parse_size_gb, and both feed the
    # same MAX_SIZE_GB threshold and undersized check.
    return value if m.group(2).upper() == "GB" else value / 1024.0


def parse_seeders(text: str) -> int:
    """Seeder count from a '👤 42' marker. 0 when absent."""
    m = _SEEDERS_RE.search(text or "")
    return int(m.group(1)) if m else 0


@dataclass
class Stream:
    name: str
    title: str
    info_hash: str
    quality: str
    seeders: int
    size_gb: float
    is_season_pack: bool
    languages: tuple[str, ...] = ()
    source: str = "torrentio"
    # True when the debrid provider already has this cached (Debridio's ⚡).
    cached: bool = False
    # Other scrapers that returned this same info_hash, in priority order.
    # Populated by scrapers.fetch_candidates during dedup.
    also_seen_in: tuple[str, ...] = ()

    @property
    def magnet(self) -> str:
        return f"magnet:?xt=urn:btih:{self.info_hash}"

    @property
    def size(self) -> str:
        """Human-readable size (used in UI)."""
        return f"{self.size_gb:.2f} GB" if self.size_gb > 0 else ""


def _quality_rank(stream: Stream, quality_pref: list[str]) -> int:
    try:
        return quality_pref.index(stream.quality)
    except ValueError:
        return len(quality_pref) + 1


def rank_streams(
    streams: list[Stream],
    prefer_season_pack: bool = False,
    override: dict | None = None,
) -> list[Stream]:
    """Return streams sorted by preference. Per-show override (dict from DB) can replace
    quality_preference, allow_4k, prefer_hevc on a case-by-case basis. Global filters
    are pulled live from the settings overlay so the UI can toggle them at runtime."""
    if not streams:
        return []

    import settings as _settings
    override = override or {}
    quality_pref = (
        [q.strip() for q in (override.get("quality_preference") or "").split(",") if q.strip()]
        or _settings.get("QUALITY_PREFERENCE", QUALITY_PREFERENCE)
    )
    allow_4k = _settings.get("ALLOW_4K", ALLOW_4K) if override.get("allow_4k") is None else bool(override["allow_4k"])
    prefer_hevc = _settings.get("PREFER_HEVC", PREFER_HEVC) if override.get("prefer_hevc") is None else bool(override["prefer_hevc"])
    exclude_remux = _settings.get("EXCLUDE_REMUX", EXCLUDE_REMUX)
    exclude_bluray = _settings.get("EXCLUDE_BLURAY", EXCLUDE_BLURAY)
    exclude_dv_p5 = _settings.get("EXCLUDE_DV_P5", EXCLUDE_DV_P5)
    exclude_cam = _settings.get("EXCLUDE_CAM", EXCLUDE_CAM)
    strict_cam = _settings.get("STRICT_NO_CAM", False)
    prefer_webdl = _settings.get("PREFER_WEBDL", PREFER_WEBDL)
    min_seeders = _settings.get("MIN_SEEDERS", MIN_SEEDERS)
    max_size_gb = _settings.get("MAX_SIZE_GB", MAX_SIZE_GB)
    audio_pref = _settings.get("AUDIO_LANGUAGE_PREFERENCE", AUDIO_LANGUAGE_PREFERENCE)

    candidates = streams if allow_4k else [s for s in streams if s.quality != "2160p"]
    if not candidates:
        log.warning("No non-4K candidates; falling back to full list")
        candidates = list(streams)

    if exclude_dv_p5:
        def _is_dv_p5(s: Stream) -> bool:
            blob = f"{s.name} {s.title}"
            return bool(_DV_RE.search(blob)) and not bool(_HDR10_RE.search(blob))
        filtered = [s for s in candidates if not _is_dv_p5(s)]
        if filtered:
            candidates = filtered
        else:
            log.warning("Only DV Profile 5 candidates available; allowing them")

    if exclude_remux:
        filtered = [s for s in candidates if not _REMUX_RE.search(f"{s.name} {s.title}")]
        if filtered:
            candidates = filtered
        else:
            log.warning("Only remux candidates available; allowing them")

    if exclude_bluray:
        filtered = [s for s in candidates if not _BLURAY_RE.search(f"{s.name} {s.title}")]
        if filtered:
            candidates = filtered
        else:
            log.warning("Only BluRay candidates available; allowing them")

    if exclude_cam:
        filtered = [s for s in candidates if not _CAM_RE.search(f"{s.name} {s.title}")]
        if filtered:
            candidates = filtered
        elif strict_cam:
            log.warning("Only cam/telesync candidates available and STRICT_NO_CAM is on  -  rejecting all")
            return []
        else:
            log.warning("Only cam/telesync candidates available; allowing them")

    exclude_undersized = _settings.get("EXCLUDE_UNDERSIZED_RELEASES", EXCLUDE_UNDERSIZED_RELEASES)
    runtime_minutes = override.get("runtime_minutes")
    if exclude_undersized and runtime_minutes:
        def _is_undersized(s: Stream) -> bool:
            if s.size_gb <= 0:
                return False  # unknown size  -  don't penalize, nothing to check
            return s.size_gb < _min_plausible_size_gb(s.quality, runtime_minutes)
        filtered = [s for s in candidates if not _is_undersized(s)]
        if filtered:
            candidates = filtered
        elif strict_cam:
            log.warning("Only implausibly small (likely fake/cam/trailer) candidates available "
                        "and STRICT_NO_CAM is on  -  rejecting all")
            return []
        else:
            log.warning("Only implausibly small (likely fake/cam/trailer) candidates available; allowing them")

    if min_seeders > 0:
        filtered = [s for s in candidates if s.seeders == 0 or s.seeders >= min_seeders]
        if filtered:
            candidates = filtered
        else:
            log.warning("No candidates meet MIN_SEEDERS=%d; allowing all", min_seeders)

    if max_size_gb > 0:
        filtered = [s for s in candidates if s.size_gb == 0.0 or s.size_gb <= max_size_gb]
        if filtered:
            candidates = filtered
        else:
            log.warning("No candidates within MAX_SIZE_GB=%d; allowing all", max_size_gb)

    exclude_langs = set(_settings.get("EXCLUDE_LANGUAGES", EXCLUDE_LANGUAGES) or [])
    if exclude_langs:
        pref_langs = set(audio_pref) | {"multi"}
        filtered = [
            s for s in candidates
            if not (
                any(lang in s.languages for lang in exclude_langs)
                and not any(lang in s.languages for lang in pref_langs)
            )
        ]
        if filtered:
            candidates = filtered
        else:
            log.warning("All candidates match EXCLUDE_LANGUAGES; allowing all")

    def _lang_score(s: Stream) -> int:
        if not audio_pref:
            return 0
        if not s.languages:
            return len(audio_pref)
        for idx, want in enumerate(audio_pref):
            if want in s.languages or "multi" in s.languages:
                return idx
        return len(audio_pref) + 1

    def sort_key(s: Stream) -> tuple:
        blob = f"{s.name} {s.title}"
        return (
            0 if prefer_season_pack and s.is_season_pack else 1,
            _quality_rank(s, quality_pref),
            _lang_score(s),
            0 if prefer_webdl and _WEBDL_RE.search(blob) else 1,
            0 if prefer_hevc and _HEVC_RE.search(blob) else 1,
            -s.seeders,
            s.size_gb,
        )

    candidates.sort(key=sort_key)
    return candidates
