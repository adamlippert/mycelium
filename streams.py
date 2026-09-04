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
    DEFAULT_SORT_ORDER,
    EXCLUDE_UNDERSIZED_RELEASES,
    MAX_SIZE_GB,
    MAX_SIZE_GB_BY_RESOLUTION,
    MIN_SEEDERS,
    PREFER_SMALLER_FILES,
    SORT_ORDER,
)

log = logging.getLogger(__name__)

# Messages already logged by rank_streams_explained's
# warn_unsupported_requirements loop, so a busy instance does not repeat the
# same warning on every single call. Resets on restart, which is the desired
# behaviour: a settings change should re-warn.
_warned_unsupported_requirements: set[str] = set()

_SEEDERS_RE = re.compile(r"👤\s*(\d+)")
_SIZE_RE = re.compile(r"💾\s*([\d.]+)\s*(GB|MB)", re.IGNORECASE)

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
    Delegates to release_tags.detect_resolution, which returns the same
    'unknown' sentinel for a no-match.
    """
    import release_tags
    return release_tags.detect_resolution(text)


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


def parse_size_limits(raw) -> dict[str, float]:
    """Parse "2160p=60,1080p=15" into {"2160p": 60.0, "1080p": 15.0}.

    Malformed entries are skipped with a warning rather than raising: a bad
    setting must narrow nothing, not break ranking for every request. Entries
    naming a resolution Mycelium never produces (say "4k=60", where
    Stream.quality would read "2160p") are dropped the same way, because they
    would silently cap nothing while looking like they worked.
    """
    import release_tags

    if isinstance(raw, str):
        raw = raw.split(",")
    out: dict[str, float] = {}
    bad: list[str] = []
    unknown: list[str] = []
    for item in (raw or []):
        text = str(item).strip()
        if not text:
            continue
        resolution, _, value = text.partition("=")
        resolution = resolution.strip().lower()
        try:
            parsed = float(value)
        except ValueError:
            bad.append(text)
            continue
        if resolution not in release_tags.RESOLUTION_VALUES:
            unknown.append(text)
            continue
        out[resolution] = parsed
    if bad:
        log.warning("Ignoring malformed MAX_SIZE_GB_BY_RESOLUTION entries: %s",
                    ", ".join(bad))
    if unknown:
        log.warning(
            "Ignoring MAX_SIZE_GB_BY_RESOLUTION entries for resolutions Mycelium "
            "never produces: %s  -  valid resolutions are %s",
            ", ".join(unknown), ", ".join(sorted(release_tags.RESOLUTION_VALUES)))
    return out


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
        # Previously governed by STRICT_NO_CAM, which had nothing to do with
        # release size. Now it has its own toggle.
        elif _settings.get("EXCLUDE_UNDERSIZED_STRICT", False):
            log.warning("Only implausibly small candidates available and "
                        "EXCLUDE_UNDERSIZED_STRICT is on; rejecting all")
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
    size_limits = parse_size_limits(
        _settings.get("MAX_SIZE_GB_BY_RESOLUTION", MAX_SIZE_GB_BY_RESOLUTION))
    if size_limits or max_size_gb > 0:
        def _within(s: Stream) -> bool:
            # A resolution named in the per-resolution caps overrides the
            # global cap for that resolution only. An unknown size (0.0)
            # always survives, the same as every other numeric filter here.
            limit = size_limits.get((s.quality or "").lower(), max_size_gb)
            return limit <= 0 or s.size_gb == 0.0 or s.size_gb <= limit
        filtered = [s for s in candidates if _within(s)]
        if filtered:
            candidates = filtered
        else:
            log.warning("No candidates within the configured size limits; allowing all")

    return candidates


# Every name SORT_ORDER may contain, in the order _sort_candidates would use
# them if a setting listed all ten. settings.py validates against this tuple
# the same way a rule-list key is validated against release_tags.values_for().
SORT_CRITERIA = (
    "season_pack", "resolution", "cached", "language", "source",
    "encode", "visual_tag", "audio_tag", "seeders", "size",
)


def _resolve_sort_order(raw) -> list[str]:
    """Normalise a SORT_ORDER value: lowercase, drop unknown names (warning),
    dedupe keeping the first occurrence, and fall back to the default when
    nothing usable survives.

    This is the one place that has to tolerate a value settings.set() never
    validated - one that arrived via .env, which parses SORT_ORDER as a plain
    comma-split list with no access to SORT_CRITERIA (config.py cannot import
    streams.py; the reverse import already exists). A DB-stored value already
    passed set()'s validation, but running it through here too is harmless and
    keeps this function the single source of truth for what actually sorts.

    Falls back to DEFAULT_SORT_ORDER, never to SORT_ORDER: SORT_ORDER is
    exactly the unvalidated config.SORT_ORDER value this function exists to
    tolerate, so falling back to it would mean a SORT_ORDER=bogus in .env gets
    rejected here and then handed straight back as the "default" - every
    rank_streams call would raise a KeyError in sort_key on the very name this
    function just dropped. DEFAULT_SORT_ORDER is a plain literal that cannot
    be broken by any env value.
    """
    names = raw if isinstance(raw, (list, tuple)) else []
    seen: set[str] = set()
    resolved: list[str] = []
    for name in names:
        name = str(name).strip().lower()
        if not name or name in seen:
            continue
        if name not in SORT_CRITERIA:
            log.warning(
                "SORT_ORDER has unknown criterion %r; dropping it. Valid "
                "names are %s", name, ", ".join(SORT_CRITERIA))
            continue
        seen.add(name)
        resolved.append(name)
    return resolved or list(DEFAULT_SORT_ORDER)


def _sort_candidates(
    candidates: list[Stream],
    rules: dict,
    prefer_season_pack: bool,
    override: dict,
) -> list[Stream]:
    """Sort survivors by preference, in the order SORT_ORDER names.

    The default order reproduces the old hardcoded tuple exactly: season pack,
    resolution, language, source, encode, seeders, size. cached, visual_tag
    and audio_tag are real criteria a user can add, but are deliberately absent
    from that default - see config.SORT_ORDER.

    override is accepted for signature symmetry with _apply_non_category_filters;
    a per-show quality_preference/prefer_hevc override is already folded into
    rules by the caller (_apply_show_override), so nothing here reads it again.
    """
    import release_tags
    import settings as _settings

    resolution_preferred = rules["resolution"]["preferred"]
    language_preferred = rules["language"]["preferred"]
    source_preferred = rules["source"]["preferred"]
    encode_preferred = rules["encode"]["preferred"]
    visual_tag_preferred = rules["visual_tag"]["preferred"]
    audio_tag_preferred = rules["audio_tag"]["preferred"]

    def _lang_score(s: Stream) -> int:
        if not language_preferred:          # no preference: everything ties
            return 0
        if not s.languages:                 # "did not say": second worst
            return len(language_preferred)
        for idx, want in enumerate(language_preferred):
            if want in s.languages or "multi" in s.languages:
                return idx                  # matched: by preference position
        return len(language_preferred) + 1  # positively non-matching: worst

    # Reward any source/encode/visual tag/audio tag the user listed as
    # preferred, not one hardcoded value. The old _WEBDL_RE matched web-dl,
    # webrip and web alike, so hardcoding webdl here silently demoted the
    # other two.
    prefer_smaller = _settings.get("PREFER_SMALLER_FILES", PREFER_SMALLER_FILES)

    scorers = {
        "season_pack": lambda s, blob: 0 if prefer_season_pack and s.is_season_pack else 1,
        "resolution": lambda s, blob: _quality_rank(s, resolution_preferred),
        "cached": lambda s, blob: 0 if s.cached else 1,
        "language": lambda s, blob: _lang_score(s),
        "source": lambda s, blob: 0 if any(
            v in source_preferred for v in release_tags.detect_sources(blob)) else 1,
        "encode": lambda s, blob: 0 if any(
            v in encode_preferred for v in release_tags.detect_encode(blob)) else 1,
        "visual_tag": lambda s, blob: 0 if any(
            v in visual_tag_preferred for v in release_tags.detect_visual_tags(blob)) else 1,
        "audio_tag": lambda s, blob: 0 if any(
            v in audio_tag_preferred for v in release_tags.detect_audio_tags(blob)) else 1,
        "seeders": lambda s, blob: -s.seeders,
        # Ascending by default, so the smallest file wins a tie once every
        # other term is equal. PREFER_SMALLER_FILES false flips it, for
        # libraries that read size as a proxy for quality.
        "size": (lambda s, blob: s.size_gb) if prefer_smaller else (lambda s, blob: -s.size_gb),
    }

    order = _resolve_sort_order(_settings.get("SORT_ORDER", SORT_ORDER))

    def sort_key(s: Stream) -> tuple:
        blob = f"{s.name} {s.title}"
        return tuple(scorers[name](s, blob) for name in order)

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

    for message in filter_rules.warn_unsupported_requirements(
            rules, sorted({s.source for s in streams})):
        if message not in _warned_unsupported_requirements:
            _warned_unsupported_requirements.add(message)
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

    An empty override returns rules unchanged (nothing to translate, so
    nothing to copy). Otherwise returns a deep copy with the override folded
    in, so a per-show override never mutates the caller's rules or leaks into
    the next call. runtime_minutes is not a filter category and is handled
    elsewhere.
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
