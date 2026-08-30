"""Shared stream model, parsing helpers and ranking for all scrapers.

Zilean, Torrentio and Debridio all produce Stream objects and are ranked by
the same function. That function used to live in torrentio.py, which made it
look Torrentio-specific; it never was.
"""
import copy
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


# ── Languages ────────────────────────────────────────────────────────────────
#
# Two independent sources, because the scrapers disagree wildly about what they
# ship. Torrentio spells a language out in the release name, when it says so at
# all; Debridio ships flag emoji in the title, which is richer and structured;
# Zilean carries nothing (see zilean.LANGUAGES_AVAILABLE).
#
# An empty result means "the release did not say", NOT "this release has no
# languages" - untagged English is the overwhelming default in release naming.
# Anything that treats absence as a positive fact will throw away most of the
# catalogue. Use languages_or_unknown() where that distinction has to be
# visible.
#
# LANGUAGE_UNKNOWN and languages_or_unknown() below have no production callers
# yet - they are deliberate groundwork for a planned filter model where "the
# release did not say" must stay distinguishable from "has no languages" (the
# current EXCLUDE_LANGUAGES filter only ever looks at s.languages directly, so
# it doesn't need this yet). Keep them; this is not dead code left by mistake.

LANGUAGE_UNKNOWN = "unknown"

_LANG_NAME_PATTERNS = {
    "nl":    re.compile(r"\b(dutch|nederlands?|nl[. -]?(?:nlt?[. -]?)?(?:dubbed|sub|audio|subs)|nl(?:nlt)?\b|nlsubs?)\b", re.IGNORECASE),
    "en":    re.compile(r"\b(english|eng(?:lish)?(?:[. -](?:audio|dubbed|dub))?|eng-?subs?)\b", re.IGNORECASE),
    "multi": re.compile(r"\b(multi(?:lang|-?audio|-?subs?)?|dual[. -]?audio|tri-?audio)\b", re.IGNORECASE),
    "ru":    re.compile(r"\b(russian|rus(?:sian)?|ru[. -]?dub(?:bed)?|rudub)\b|[\u0430-\u044f\u0410-\u042f\u0451\u0401]{4,}", re.IGNORECASE),
}

# Regional indicator pairs, as Debridio ships them. Several regions map to one
# language on purpose - a GB and a US flag both mean English for our purposes.
# This is deliberately lossy for multilingual regions: CA -> en, BE -> nl,
# CH -> de, IN -> hi, so e.g. a French-Canadian track flagged with a Canada
# flag comes out tagged "en". There is no per-region sub-language signal in a
# flag emoji to do better than that.
_FLAG_RE = re.compile(r"[\U0001F1E6-\U0001F1FF]{2}")
_REGION_TO_LANGUAGE = {
    "GB": "en", "US": "en", "AU": "en", "CA": "en", "IE": "en", "NZ": "en",
    "NL": "nl", "BE": "nl",
    "FR": "fr", "DE": "de", "AT": "de", "CH": "de",
    "ES": "es", "MX": "es", "AR": "es", "CO": "es", "CL": "es",
    "IT": "it", "PT": "pt", "BR": "pt",
    "RU": "ru", "UA": "uk", "PL": "pl", "CZ": "cs", "SK": "sk",
    "HU": "hu", "RO": "ro", "BG": "bg", "GR": "el", "TR": "tr",
    "SE": "sv", "NO": "no", "DK": "da", "FI": "fi", "IS": "is",
    "JP": "ja", "KR": "ko", "CN": "zh", "TW": "zh", "HK": "zh",
    "IN": "hi", "TH": "th", "VN": "vi", "ID": "id", "MY": "ms",
    "IL": "he", "SA": "ar", "EG": "ar", "AE": "ar", "IR": "fa",
}

# Every code a release can be tagged with. settings.set() validates
# AUDIO_LANGUAGE_PREFERENCE and EXCLUDE_LANGUAGES against this (rejecting
# unknown codes); settings.py also warns - without raising - about values that
# arrived via .env, since config.py's own parsing can't see this module.
LANGUAGE_CODES = tuple(sorted(set(_LANG_NAME_PATTERNS) | set(_REGION_TO_LANGUAGE.values())))


def _flag_to_region(flag: str) -> str:
    """Regional-indicator pair -> ISO country code, e.g. the GB flag -> "GB"."""
    return "".join(chr(ord(c) - 0x1F1E6 + ord("A")) for c in flag)


def detect_languages(text: str) -> tuple[str, ...]:
    """Languages a release positively declares, from flag emoji and name tokens.

    Empty means the release did not say - never that it has no audio. Order is
    deterministic for its own sake (stable logs, stable tests, and a possible
    future filter model may care about it) - NOT because it feeds a ranking
    index: _lang_score in rank_streams indexes into audio_pref, not into this
    tuple's order, so detection order has no effect on ranking today.

    Note also that knowing more can rank a release WORSE, not just better: a
    release that positively declares a language outside AUDIO_LANGUAGE_PREFERENCE
    scores worse in _lang_score than one that declared nothing at all (the
    latter is merely "unknown", the former is a known non-match). That is a
    real, intended outcome of adding a new detection source, not a bug.
    """
    blob = text or ""
    found: list[str] = []
    for flag in _FLAG_RE.findall(blob):
        code = _REGION_TO_LANGUAGE.get(_flag_to_region(flag))
        if code and code not in found:
            found.append(code)
    for code, pattern in _LANG_NAME_PATTERNS.items():
        if code not in found and pattern.search(blob):
            found.append(code)
    return tuple(found)


def languages_or_unknown(languages) -> tuple[str, ...]:
    """Detected languages, or ("unknown",) when the release did not say.

    Use where the difference has to be visible - a filter that treats absence as
    a match, or a UI that would otherwise render an empty cell.
    """
    return tuple(languages) if languages else (LANGUAGE_UNKNOWN,)


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


def _apply_non_category_filters(candidates: list[Stream], override: dict) -> list[Stream]:
    """MIN_SEEDERS, MAX_SIZE_GB and the undersized-release check.

    These three are not filter-rule categories (release_tags.CATEGORIES), so
    filter_rules never evaluates them; they run here exactly as they did in the
    old sequential rank_streams body. Same "unknown passes" semantics (a
    seeders of 0 or a size_gb of 0.0 always survives, because that means the
    scraper did not report a value, not that the value is zero), and each
    filter still self-disables with the same log message when it would empty
    the pool.
    """
    if not candidates:
        return candidates

    import settings as _settings

    strict_cam = _settings.get("STRICT_NO_CAM", False)
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

    min_seeders = _settings.get("MIN_SEEDERS", MIN_SEEDERS)
    if min_seeders > 0:
        filtered = [s for s in candidates if s.seeders == 0 or s.seeders >= min_seeders]
        if filtered:
            candidates = filtered
        else:
            log.warning("No candidates meet MIN_SEEDERS=%d; allowing all", min_seeders)

    max_size_gb = _settings.get("MAX_SIZE_GB", MAX_SIZE_GB)
    if max_size_gb > 0:
        filtered = [s for s in candidates if s.size_gb == 0.0 or s.size_gb <= max_size_gb]
        if filtered:
            candidates = filtered
        else:
            log.warning("No candidates within MAX_SIZE_GB=%d; allowing all", max_size_gb)

    return candidates


def _sort_candidates(
    candidates: list[Stream],
    rules: dict,
    prefer_season_pack: bool,
    override: dict,
) -> list[Stream]:
    """Sort survivors by preference. The tuple shape and order are unchanged
    from the old sort_key closure; only the inputs moved, from settings/config
    to the rule dict the category engine already produced. Configurable
    SORT_ORDER is out of scope for this step, see the follow-up task.

    override is accepted for signature symmetry with _apply_non_category_filters;
    a per-show quality_preference/prefer_hevc override is already folded into
    rules by the caller (_apply_show_override), so nothing here reads it again.
    """
    import release_tags

    resolution_preferred = rules["resolution"]["preferred"]
    language_preferred = rules["language"]["preferred"]
    prefer_webdl = "webdl" in rules["source"]["preferred"]
    prefer_hevc = "hevc" in rules["encode"]["preferred"]

    def _lang_score(s: Stream) -> int:
        if not language_preferred:          # no preference: everything ties
            return 0
        if not s.languages:                 # "did not say": second worst
            return len(language_preferred)
        for idx, want in enumerate(language_preferred):
            if want in s.languages or "multi" in s.languages:
                return idx                  # matched: by preference position
        return len(language_preferred) + 1  # positively non-matching: worst

    def sort_key(s: Stream) -> tuple:
        blob = f"{s.name} {s.title}"
        return (
            0 if prefer_season_pack and s.is_season_pack else 1,
            _quality_rank(s, resolution_preferred),
            _lang_score(s),
            0 if prefer_webdl and "webdl" in release_tags.detect_sources(blob) else 1,
            0 if prefer_hevc and "hevc" in release_tags.detect_encode(blob) else 1,
            -s.seeders,
            s.size_gb,
        )

    candidates.sort(key=sort_key)
    return candidates


def rank_streams_explained(
    streams: list["Stream"],
    prefer_season_pack: bool = False,
    override: dict | None = None,
) -> tuple[list["Stream"], list["filter_rules.Verdict"]]:
    """Rank candidates and return the verdict for every input, kept or dropped.

    Nothing is discarded silently: each rejected candidate carries the rule and
    value that removed it, and whether that rule later relaxed itself.
    """
    import filter_rules
    import release_tags

    if not streams:
        return [], []

    override = override or {}
    rules = filter_rules.load_rules()
    rules = _apply_show_override(rules, override)

    # filter_rules.warn_unsupported_requirements ships in a later task in this
    # series and is not present on this branch yet; call it once it lands.
    # Guarded so this function activates the warning automatically the moment
    # that function exists, with no further change here.
    warn_unsupported_requirements = getattr(filter_rules, "warn_unsupported_requirements", None)
    if warn_unsupported_requirements is not None:
        for message in warn_unsupported_requirements(
                rules, sorted({s.source for s in streams})):
            log.warning("%s", message)

    tagged = [release_tags.detect_all(f"{s.name} {s.title}", s.languages)
              for s in streams]
    verdicts = filter_rules.evaluate(tagged, rules)
    kept = [s for s, v in zip(streams, verdicts) if v.kept]

    dropped = len(streams) - len(kept)
    if dropped:
        by_rule: dict[str, int] = {}
        for v in verdicts:
            if not v.kept and v.rule:
                by_rule[v.rule] = by_rule.get(v.rule, 0) + 1
        log.info("kept %d of %d; %s", len(kept), len(streams),
                 ", ".join(f"{r} dropped {n}" for r, n in sorted(by_rule.items())))

    kept = _apply_non_category_filters(kept, override)
    kept = _sort_candidates(kept, rules, prefer_season_pack, override)
    return kept, verdicts


def rank_streams(
    streams: list[Stream],
    prefer_season_pack: bool = False,
    override: dict | None = None,
) -> list[Stream]:
    """Return streams sorted by preference. Thin wrapper over
    rank_streams_explained that discards the verdicts, so the two existing
    call sites (torrentio.py, scrapers.py) keep working unchanged."""
    kept, _ = rank_streams_explained(streams, prefer_season_pack, override)
    return kept


def _apply_show_override(rules: dict, override: dict) -> dict:
    """Translate the three show_quality_override fields into the rule model.

    Returns a deep copy so a per-show override never leaks into the next call.
    runtime_minutes is not a filter category and is handled elsewhere.
    """
    if not override:
        return rules
    out = copy.deepcopy(rules)

    raw = override.get("quality_preference")
    if raw:
        out["resolution"]["preferred"] = [
            v.strip().lower() for v in str(raw).split(",") if v.strip()
        ]

    allow_4k = override.get("allow_4k")
    if allow_4k is not None and not allow_4k:
        if "2160p" not in out["resolution"]["excluded"]:
            out["resolution"]["excluded"].append("2160p")

    prefer_hevc = override.get("prefer_hevc")
    if prefer_hevc is not None:
        preferred = out["encode"]["preferred"]
        if prefer_hevc and "hevc" not in preferred:
            preferred.insert(0, "hevc")
        elif not prefer_hevc and "hevc" in preferred:
            preferred.remove("hevc")

    return out
