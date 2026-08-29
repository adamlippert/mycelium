"""Shared stream model, parsing helpers and ranking for all scrapers.

Zilean, Torrentio and Debridio all produce Stream objects and are ranked by
the same function. That function used to live in torrentio.py, which made it
look Torrentio-specific; it never was.
"""
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)


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
