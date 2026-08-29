"""Shared stream model, parsing helpers and ranking for all scrapers.

Zilean, Torrentio and Debridio all produce Stream objects and are ranked by
the same function. That function used to live in torrentio.py, which made it
look Torrentio-specific; it never was.
"""
import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)

_QUALITY_PATTERNS = {
    "2160p": re.compile(r"\b(2160p|4k|uhd)\b", re.IGNORECASE),
    "1080p": re.compile(r"\b1080p\b", re.IGNORECASE),
    "720p": re.compile(r"\b720p\b", re.IGNORECASE),
    "480p": re.compile(r"\b480p\b", re.IGNORECASE),
}
_SEEDERS_RE = re.compile(r"👤\s*(\d+)")
_SIZE_RE = re.compile(r"💾\s*([\d.]+)\s*(GB|MB)", re.IGNORECASE)


def parse_quality(text: str) -> str:
    """Highest-resolution bucket named in the text, or '' if none."""
    for quality, pattern in _QUALITY_PATTERNS.items():
        if pattern.search(text or ""):
            return quality
    return ""


def parse_size_gb(text: str) -> float:
    """Size in GB from a '💾 5.2 GB' marker. 0.0 when absent or unparseable."""
    m = _SIZE_RE.search(text or "")
    if not m:
        return 0.0
    value = float(m.group(1))
    return value if m.group(2).upper() == "GB" else value / 1000.0


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
