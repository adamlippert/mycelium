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
