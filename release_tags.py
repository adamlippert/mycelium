"""Pure release-name detection. No settings, no ranking, no I/O.

Every category returns UNKNOWN or an empty tuple when the name says nothing.
That means "the release did not say", never "the release lacks this". Untagged
English audio and untagged WEB-DL are both common, so treating silence as a
negative fact would discard most of the catalogue.
"""
import re

UNKNOWN = "unknown"

RESOLUTION_VALUES = ("2160p", "1080p", "720p", "480p", UNKNOWN)

_RESOLUTION_PATTERNS = (
    ("2160p", re.compile(r"\b(2160p|4k|uhd)\b", re.IGNORECASE)),
    ("1080p", re.compile(r"\b1080p\b", re.IGNORECASE)),
    ("720p", re.compile(r"\b720p\b", re.IGNORECASE)),
    ("480p", re.compile(r"\b480p\b", re.IGNORECASE)),
)

SOURCE_VALUES = (
    "remux", "bluray", "bdrip", "brrip", "webdl", "webrip", "hdrip",
    "dvdrip", "dvd", "hdtv", "satrip", "tvrip", "r5", "ppvrip",
    "ts", "tc", "scr", "cam", UNKNOWN,
)

# Ordered most-specific first. The first match wins, which is what makes the
# values mutually exclusive: "BluRay.REMUX" resolves to remux, not both.
_SOURCE_PATTERNS = (
    ("remux", re.compile(r"\b(remux|bdremux)\b", re.IGNORECASE)),
    ("bdrip", re.compile(r"\bbd-?rip\b", re.IGNORECASE)),
    ("brrip", re.compile(r"\bbr-?rip\b", re.IGNORECASE)),
    ("bluray", re.compile(r"\b(bluray|blu-ray)\b", re.IGNORECASE)),
    ("webdl", re.compile(r"\bweb-?dl\b", re.IGNORECASE)),
    ("webrip", re.compile(r"\bweb-?rip\b", re.IGNORECASE)),
    ("hdrip", re.compile(r"\bhd-?rip\b", re.IGNORECASE)),
    ("dvdrip", re.compile(r"\bdvd-?rip\b", re.IGNORECASE)),
    ("ppvrip", re.compile(r"\bppv-?rip\b", re.IGNORECASE)),
    ("satrip", re.compile(r"\bsat-?rip\b", re.IGNORECASE)),
    ("tvrip", re.compile(r"\btv-?rip\b", re.IGNORECASE)),
    ("hdtv", re.compile(r"\bhdtv\b", re.IGNORECASE)),
    ("scr", re.compile(r"\b(scr|screener|dvdscr|bdscr)\b", re.IGNORECASE)),
    ("cam", re.compile(r"\b(cam|camrip|hdcam)\b", re.IGNORECASE)),
    ("ts", re.compile(r"\b(ts|telesync|hdts)\b", re.IGNORECASE)),
    ("tc", re.compile(r"\b(tc|telecine)\b", re.IGNORECASE)),
    ("r5", re.compile(r"\br5\b", re.IGNORECASE)),
    ("dvd", re.compile(r"\bdvd\b", re.IGNORECASE)),
)


def detect_resolution(text: str) -> str:
    blob = text or ""
    for value, pattern in _RESOLUTION_PATTERNS:
        if pattern.search(blob):
            return value
    return UNKNOWN


def detect_sources(text: str) -> tuple[str, ...]:
    """First match wins, so the returned tuple holds at most one source value.

    A tuple rather than a str because every other category is multi-valued and
    the rule engine treats all categories identically.
    """
    blob = text or ""
    for value, pattern in _SOURCE_PATTERNS:
        if pattern.search(blob):
            return (value,)
    return ()


ENCODE_VALUES = ("hevc", "avc", "av1", "xvid", "divx", UNKNOWN)

_ENCODE_PATTERNS = (
    ("hevc", re.compile(r"\b(hevc|x265|h\.?265)\b", re.IGNORECASE)),
    ("avc", re.compile(r"\b(avc|x264|h\.?264)\b", re.IGNORECASE)),
    ("av1", re.compile(r"\bav1\b", re.IGNORECASE)),
    ("xvid", re.compile(r"\bxvid\b", re.IGNORECASE)),
    ("divx", re.compile(r"\bdivx\b", re.IGNORECASE)),
)

VISUAL_TAG_VALUES = (
    "hdr10", "hdr10plus", "dv", "dv_only", "hlg", "10bit", "sdr", "imax", UNKNOWN,
)

# hdr10plus is matched before hdr10, and the hdr10 pattern uses a negative
# lookahead, so "HDR10+" never counts as plain HDR10. HDR10+ is not a safe
# fallback for a Dolby Vision profile 5 release.
_VISUAL_PATTERNS = (
    ("hdr10plus", re.compile(r"\bhdr10(?:\+|plus\b)", re.IGNORECASE)),
    ("hdr10", re.compile(r"\bhdr10(?!\+|plus)\b", re.IGNORECASE)),
    ("dv", re.compile(r"\b(dovi|dolby[\s.]?vision|dv)\b", re.IGNORECASE)),
    ("hlg", re.compile(r"\bhlg\b", re.IGNORECASE)),
    ("10bit", re.compile(r"\b10-?bit\b", re.IGNORECASE)),
    ("sdr", re.compile(r"\bsdr\b", re.IGNORECASE)),
    ("imax", re.compile(r"\bimax\b", re.IGNORECASE)),
)


def detect_encode(text: str) -> tuple[str, ...]:
    blob = text or ""
    return tuple(v for v, p in _ENCODE_PATTERNS if p.search(blob))


def detect_visual_tags(text: str) -> tuple[str, ...]:
    """Adds the synthetic dv_only when Dolby Vision has no HDR10 base layer.

    That combination is Dolby Vision profile 5, which clients without DV support
    render with washed-out colour because there is no fallback layer.
    """
    blob = text or ""
    found = [v for v, p in _VISUAL_PATTERNS if p.search(blob)]
    if "dv" in found and "hdr10" not in found:
        found.append("dv_only")
    return tuple(found)


AUDIO_TAG_VALUES = (
    "atmos", "truehd", "dts_hd", "dts", "ddp", "dd", "aac", "flac", "opus", UNKNOWN,
)

# A codec token may be followed by channel digits (DDP5.1), a separator, or the
# end of the name, but never by another letter. A plain trailing \b would reject
# DDP5.1 and AAC2.0, which are the most common real spellings. The negative
# letter case is what keeps ddp from also satisfying dd.
_AUDIO_TAG_TERMINATOR = r"(?=\d|\W|$)"

_AUDIO_TAG_PATTERNS = (
    ("atmos", re.compile(r"\batmos" + _AUDIO_TAG_TERMINATOR, re.IGNORECASE)),
    ("truehd", re.compile(r"\btrue-?hd" + _AUDIO_TAG_TERMINATOR, re.IGNORECASE)),
    ("dts_hd", re.compile(r"\bdts-?hd" + _AUDIO_TAG_TERMINATOR, re.IGNORECASE)),
    ("dts", re.compile(r"\bdts" + _AUDIO_TAG_TERMINATOR, re.IGNORECASE)),
    ("ddp", re.compile(r"\b(?:ddp|dd\+|e-?ac-?3)" + _AUDIO_TAG_TERMINATOR, re.IGNORECASE)),
    ("dd", re.compile(r"\b(?:dd(?!\+)|(?<!e)(?<!e-)ac-?3)" + _AUDIO_TAG_TERMINATOR, re.IGNORECASE)),
    ("aac", re.compile(r"\baac" + _AUDIO_TAG_TERMINATOR, re.IGNORECASE)),
    ("flac", re.compile(r"\bflac" + _AUDIO_TAG_TERMINATOR, re.IGNORECASE)),
    ("opus", re.compile(r"\bopus" + _AUDIO_TAG_TERMINATOR, re.IGNORECASE)),
)

AUDIO_CHANNELS_VALUES = ("2.0", "5.1", "7.1", UNKNOWN)

_AUDIO_CHANNEL_PATTERNS = (
    ("7.1", re.compile(r"(?<!\d)7[\s._]?1(?!\d)")),
    ("5.1", re.compile(r"(?<!\d)5[\s._]?1(?!\d)")),
    ("2.0", re.compile(r"(?<!\d)2[\s._]?0(?!\d)")),
)

CATEGORIES = (
    "resolution", "source", "encode", "visual_tag",
    "audio_tag", "audio_channels", "language",
)

# Static per-category vocabularies. "language" is deliberately absent: it is
# not static, it is resolved lazily by values_for() below. There is no
# all-seven-categories mapping on this module, on purpose - a dict that looks
# fully populated but has a permanently-empty "language" slot invites
# .get()/.items()/.values()/dict(d)/.copy() reads that would silently return
# an empty vocabulary instead of raising, which is exactly the silent-wrong-
# value failure mode this whole filter model exists to remove.
_STATIC_CATEGORY_VALUES: dict[str, tuple[str, ...]] = {
    "resolution": RESOLUTION_VALUES,
    "source": SOURCE_VALUES,
    "encode": ENCODE_VALUES,
    "visual_tag": VISUAL_TAG_VALUES,
    "audio_tag": AUDIO_TAG_VALUES,
    "audio_channels": AUDIO_CHANNELS_VALUES,
}

_language_cache: tuple[str, ...] = ()


def values_for(category: str) -> tuple[str, ...]:
    """The vocabulary a user may type for one category.

    Language is resolved on first call rather than at import, because
    streams imports settings which imports this module, and a module-level
    streams import here would be a cycle. Every other category is static.
    """
    global _language_cache
    if category == "language":
        if not _language_cache:
            from streams import LANGUAGE_CODES
            _language_cache = tuple(LANGUAGE_CODES) + (UNKNOWN,)
        return _language_cache
    return _STATIC_CATEGORY_VALUES[category]


def language_values() -> tuple[str, ...]:
    """Resolved lazily because streams imports release_tags indirectly."""
    return values_for("language")


def detect_audio_tags(text: str) -> tuple[str, ...]:
    blob = text or ""
    return tuple(v for v, p in _AUDIO_TAG_PATTERNS if p.search(blob))


def detect_audio_channels(text: str) -> tuple[str, ...]:
    blob = text or ""
    return tuple(v for v, p in _AUDIO_CHANNEL_PATTERNS if p.search(blob))


def _or_unknown(values: tuple[str, ...]) -> tuple[str, ...]:
    return values if values else (UNKNOWN,)


def detect_all(text: str, languages: tuple[str, ...] = ()) -> dict[str, tuple[str, ...]]:
    """Every category maps to a non-empty tuple. Silence is spelled UNKNOWN.

    languages is passed in rather than detected here so this module never
    imports streams, which would create a cycle.
    """
    resolution = detect_resolution(text)
    return {
        "resolution": (resolution,),
        "source": _or_unknown(detect_sources(text)),
        "encode": _or_unknown(detect_encode(text)),
        "visual_tag": _or_unknown(detect_visual_tags(text)),
        "audio_tag": _or_unknown(detect_audio_tags(text)),
        "audio_channels": _or_unknown(detect_audio_channels(text)),
        "language": _or_unknown(tuple(languages)),
    }
