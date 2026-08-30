# C1 Inclusive Filter Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace twelve order-dependent boolean filters with a four-state
(preferred / excluded / required / included) rule model across seven release
categories, where every rejection records the rule that caused it.

**Architecture:** Three files with one responsibility each. `release_tags.py` is
pure text-to-tags detection with no settings and no ranking. `filter_rules.py`
reads the thirty-five settings and turns tags plus rules into a `Verdict` per
candidate. `streams.py` keeps the `Stream` dataclass and sorting, and delegates
all filtering to `filter_rules`. Categories are evaluated against the full
candidate pool independently, then drops are applied together, so no category
ever sees a pool another category already shrank.

**Tech Stack:** Python 3.12, stdlib `re` and `dataclasses`, pytest. No new
dependencies.

**Spec:** `docs/superpowers/specs/2026-08-29-inclusive-filter-model-design.md`

## Global Constraints

- **No em-dashes anywhere**, in code, comments, docstrings, log messages, or
  documentation. Use a spaced hyphen or restructure the sentence. This is a
  project rule from `CLAUDE.md`.
- **No `Co-Authored-By` lines in commit messages.**
- **Never edit `.env.example`.** It is under a permission deny rule. When a task
  would add keys there, list them in the task's final report instead.
- The repository is **public**. No API keys, tokens, passwords, or IP addresses
  in code, tests, fixtures, or commit messages.
- Work on branch `feat/inclusive-filter-model`, cut from `main`.
- Run the suite with `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/ -q`.
  The env var is required because `config.py` raises without it.
- Absence of data is never evidence of absence. Every category has an `unknown`
  sentinel. A `REQUIRED` rule never drops an `unknown`; only an explicit
  `unknown` in an `EXCLUDED` list does.
- Every filter is soft by default: if a rule would empty the candidate pool it
  self-disables and records `relaxed=True`. Only a `*_STRICT` toggle makes it
  hard.

## File Structure

| File | Responsibility |
|---|---|
| `release_tags.py` (new) | Pure detection. Release name to a `dict[str, tuple[str, ...]]` of category to detected values. No imports from `settings`, `config`, or `streams`. |
| `filter_rules.py` (new) | The four-state model. Reads the 35 settings, evaluates categories independently against the pool, returns a `Verdict` per candidate. Imports `release_tags` and `settings`, never `streams`. |
| `streams.py` (modify) | Keeps `Stream`, `parse_seeders`, `parse_size_gb`, `detect_languages`, and sorting. Delegates filtering to `filter_rules`. |
| `settings.py` (modify) | Registers the 35 new keys in `_LIST_KEYS`, `_BOOL_KEYS` and `SETTING_GROUPS`; adds vocabulary validation. |
| `migrate_filters.py` (new) | One-shot translation of the eleven retired settings into the new rows, plus the stale-`.env` startup warning. |
| `tests/test_release_tags.py` (new) | Detection tests, one real release name per pattern. |
| `tests/test_filter_rules.py` (new) | Four-state semantics, order independence, unknown handling, relaxation. |
| `tests/test_filter_migration.py` (new) | One test per row of the spec's migration table. |

`release_tags.py` is deliberately settings-free so its tests need no monkeypatching
and its ~30 patterns can be tested as pure functions.

---

### Task 1: Resolution and source detection

**Files:**
- Create: `release_tags.py`
- Test: `tests/test_release_tags.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `UNKNOWN: str = "unknown"`; `detect_resolution(text: str) -> str`;
  `detect_sources(text: str) -> tuple[str, ...]`;
  `RESOLUTION_VALUES: tuple[str, ...]`; `SOURCE_VALUES: tuple[str, ...]`.

The point of this task is that `bluray` and `remux` stop overlapping. Today
`_BLURAY_RE` matches `bluray|blu-ray|bdrip|brrip` and `_REMUX_RE` matches
`remux|bdremux`, so `BluRay.REMUX` matches both and `EXCLUDE_BLURAY` silently
drops remuxes, while `BDRemux` escapes the BluRay filter entirely. The new
values are mutually exclusive by construction: `remux` wins over `bluray` when
both tokens appear.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_release_tags.py
import os, sys
os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import release_tags as rt


@pytest.mark.parametrize("text,expected", [
    ("Movie.2024.2160p.WEB-DL.x265", "2160p"),
    ("Movie.2024.4K.UHD.BluRay", "2160p"),
    ("Movie.2024.1080p.WEB-DL", "1080p"),
    ("Movie.2024.720p.HDTV", "720p"),
    ("Movie.2024.480p.DVDRip", "480p"),
    ("Movie.2024.WEB-DL.x264", rt.UNKNOWN),
])
def test_detect_resolution(text, expected):
    assert rt.detect_resolution(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("Dune.2160p.UHD.BluRay.REMUX.HEVC", {"remux"}),
    ("Movie.1080p.BDRemux.x264", {"remux"}),
    ("Movie.1080p.BluRay.x264", {"bluray"}),
    ("Movie.1080p.BDRip.x264", {"bdrip"}),
    ("Movie.1080p.BRRip.x264", {"brrip"}),
    ("Movie.1080p.WEB-DL.DDP5.1", {"webdl"}),
    ("Movie.1080p.WEBRip.x264", {"webrip"}),
    ("Movie.720p.HDTV.x264", {"hdtv"}),
    ("Movie.DVDRip.XviD", {"dvdrip"}),
    ("Movie.2024.HDCAM.x264", {"cam"}),
    ("Movie.2024.TELESYNC.x264", {"ts"}),
    ("Movie.2024.DVDSCR.x264", {"scr"}),
    ("Movie.2024.x264", set()),
])
def test_detect_sources_are_mutually_exclusive(text, expected):
    assert set(rt.detect_sources(text)) == expected


def test_remux_and_bluray_no_longer_collide():
    """The defect this replaces: EXCLUDE_BLURAY silently dropped remuxes because
    _BLURAY_RE matched the same names as _REMUX_RE."""
    assert set(rt.detect_sources("Dune.2160p.UHD.BluRay.REMUX.HEVC")) == {"remux"}
    assert "bluray" not in rt.detect_sources("Dune.2160p.UHD.BluRay.REMUX.HEVC")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/test_release_tags.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'release_tags'`

- [ ] **Step 3: Write minimal implementation**

```python
# release_tags.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/test_release_tags.py -q`
Expected: PASS, 20 tests

- [ ] **Step 5: Verify the tests have teeth**

Reorder `_SOURCE_PATTERNS` so `bluray` precedes `remux`, confirm the mutation
landed, clear caches, and re-run:

```bash
grep -n '"bluray"' release_tags.py     # confirm the line moved
find . -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null
TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/test_release_tags.py -q
```
Expected: `test_remux_and_bluray_no_longer_collide` FAILS. Restore the order and
confirm the suite is green again. A test that has never been observed to fail
proves nothing.

- [ ] **Step 6: Commit**

```bash
git add release_tags.py tests/test_release_tags.py
git commit -m "feat(tags): non-overlapping resolution and source detection"
```

---

### Task 2: Encode and visual-tag detection

**Files:**
- Modify: `release_tags.py`
- Test: `tests/test_release_tags.py`

**Interfaces:**
- Consumes: `UNKNOWN` from Task 1.
- Produces: `detect_encode(text) -> tuple[str, ...]`;
  `detect_visual_tags(text) -> tuple[str, ...]`;
  `ENCODE_VALUES`, `VISUAL_TAG_VALUES`.

`dv_only` is synthetic: Dolby Vision present with no HDR10 base layer. That is
what `EXCLUDE_DV_P5` means today, and no plain token expresses it. Note that
`HDR10+` is not a safe HDR10 fallback, so the HDR10 pattern must reject it.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_release_tags.py

@pytest.mark.parametrize("text,expected", [
    ("Movie.2024.1080p.x265.HEVC", {"hevc"}),
    ("Movie.2024.1080p.H.265", {"hevc"}),
    ("Movie.2024.1080p.x264", {"avc"}),
    ("Movie.2024.1080p.H.264.AVC", {"avc"}),
    ("Movie.2024.2160p.AV1", {"av1"}),
    ("Movie.2024.XviD", {"xvid"}),
    ("Movie.2024.1080p", set()),
])
def test_detect_encode(text, expected):
    assert set(rt.detect_encode(text)) == expected


@pytest.mark.parametrize("text,expected", [
    ("Movie.2160p.HDR10.WEB-DL", {"hdr10"}),
    ("Movie.2160p.HDR10Plus.WEB-DL", {"hdr10plus"}),
    ("Movie.2160p.DV.HDR10.WEB-DL", {"dv", "hdr10"}),
    ("Movie.2160p.DoVi.WEB-DL", {"dv", "dv_only"}),
    ("Movie.2160p.HLG.WEB-DL", {"hlg"}),
    ("Movie.2160p.10bit.WEB-DL", {"10bit"}),
    ("Movie.2160p.IMAX.WEB-DL", {"imax"}),
    ("Movie.1080p.WEB-DL", set()),
])
def test_detect_visual_tags(text, expected):
    assert set(rt.detect_visual_tags(text)) == expected


def test_hdr10_plus_is_not_an_hdr10_fallback():
    """HDR10+ does not give a DV-only release a safe base layer, so it must not
    satisfy the hdr10 tag."""
    tags = rt.detect_visual_tags("Movie.2160p.DV.HDR10Plus.WEB-DL")
    assert "hdr10" not in tags
    assert "dv_only" in tags
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/test_release_tags.py -q`
Expected: FAIL with `AttributeError: module 'release_tags' has no attribute 'detect_encode'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to release_tags.py

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
    ("hdr10plus", re.compile(r"\bhdr10(\+|plus)\b", re.IGNORECASE)),
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/test_release_tags.py -q`
Expected: PASS, 36 tests

- [ ] **Step 5: Commit**

```bash
git add release_tags.py tests/test_release_tags.py
git commit -m "feat(tags): encode and visual tag detection with synthetic dv_only"
```

---

### Task 3: Audio tag and channel detection, and the unified entry point

**Files:**
- Modify: `release_tags.py`
- Test: `tests/test_release_tags.py`

**Interfaces:**
- Consumes: everything from Tasks 1 and 2, and
  `streams.detect_languages(text) -> tuple[str, ...]`.
- Produces: `detect_audio_tags(text) -> tuple[str, ...]`;
  `detect_audio_channels(text) -> tuple[str, ...]`;
  `AUDIO_TAG_VALUES`, `AUDIO_CHANNELS_VALUES`;
  `CATEGORIES: tuple[str, ...]`;
  `VALUES_BY_CATEGORY: dict[str, tuple[str, ...]]`;
  `detect_all(text: str, languages: tuple[str, ...]) -> dict[str, tuple[str, ...]]`.

`detect_all` takes languages as a parameter rather than importing `streams`,
keeping this module free of the import cycle `streams -> filter_rules ->
release_tags`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_release_tags.py

@pytest.mark.parametrize("text,expected", [
    ("Movie.2160p.TrueHD.Atmos.7.1", {"truehd", "atmos"}),
    ("Movie.1080p.DTS-HD.MA.5.1", {"dts_hd", "dts"}),
    ("Movie.1080p.DDP5.1.Atmos", {"ddp", "atmos"}),
    ("Movie.1080p.AC3", {"dd"}),
    ("Movie.1080p.AAC2.0", {"aac"}),
    ("Movie.1080p.FLAC", {"flac"}),
    ("Movie.1080p.x264", set()),
])
def test_detect_audio_tags(text, expected):
    assert set(rt.detect_audio_tags(text)) == expected


@pytest.mark.parametrize("text,expected", [
    ("Movie.2160p.TrueHD.7.1", {"7.1"}),
    ("Movie.1080p.DDP5.1", {"5.1"}),
    ("Movie.1080p.AAC2.0", {"2.0"}),
    ("Movie.1080p.x264", set()),
])
def test_detect_audio_channels(text, expected):
    assert set(rt.detect_audio_channels(text)) == expected


def test_detect_all_covers_every_category():
    tags = rt.detect_all("Movie.2024.1080p.WEB-DL.x265.HDR10.DDP5.1", ("en",))
    assert set(tags) == set(rt.CATEGORIES)
    assert tags["resolution"] == ("1080p",)
    assert tags["source"] == ("webdl",)
    assert tags["encode"] == ("hevc",)
    assert tags["language"] == ("en",)


def test_detect_all_uses_unknown_not_empty_for_silence():
    """An empty tuple and UNKNOWN must not both be reachable, or the rule engine
    has two spellings for the same idea."""
    tags = rt.detect_all("Some.Release.Name", ())
    for category, values in tags.items():
        assert values == (rt.UNKNOWN,), f"{category} was {values!r}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/test_release_tags.py -q`
Expected: FAIL with `AttributeError: module 'release_tags' has no attribute 'detect_audio_tags'`

- [ ] **Step 3: Write minimal implementation**

```python
# append to release_tags.py

AUDIO_TAG_VALUES = (
    "atmos", "truehd", "dts_hd", "dts", "ddp", "dd", "aac", "flac", "opus", UNKNOWN,
)

_AUDIO_TAG_PATTERNS = (
    ("atmos", re.compile(r"\batmos\b", re.IGNORECASE)),
    ("truehd", re.compile(r"\btrue-?hd\b", re.IGNORECASE)),
    ("dts_hd", re.compile(r"\bdts-?hd\b", re.IGNORECASE)),
    ("dts", re.compile(r"\bdts\b", re.IGNORECASE)),
    ("ddp", re.compile(r"\b(ddp|eac3|e-ac-3)\b", re.IGNORECASE)),
    ("dd", re.compile(r"\b(dd|ac3|ac-3)\b", re.IGNORECASE)),
    ("aac", re.compile(r"\baac\b", re.IGNORECASE)),
    ("flac", re.compile(r"\bflac\b", re.IGNORECASE)),
    ("opus", re.compile(r"\bopus\b", re.IGNORECASE)),
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
```

Also add, after `CATEGORIES`:

```python
VALUES_BY_CATEGORY: dict[str, tuple[str, ...]] = {
    "resolution": RESOLUTION_VALUES,
    "source": SOURCE_VALUES,
    "encode": ENCODE_VALUES,
    "visual_tag": VISUAL_TAG_VALUES,
    "audio_tag": AUDIO_TAG_VALUES,
    "audio_channels": AUDIO_CHANNELS_VALUES,
    "language": (),   # filled by Task 4 from streams.LANGUAGE_CODES
}
```

Note `detect_resolution` already returns `UNKNOWN` rather than an empty string,
so `_or_unknown` is not applied to it.

- [ ] **Step 4: Run test to verify it passes**

Run: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/test_release_tags.py -q`
Expected: PASS, 49 tests

- [ ] **Step 5: Commit**

```bash
git add release_tags.py tests/test_release_tags.py
git commit -m "feat(tags): audio tags, channels, and the detect_all entry point"
```

---

### Task 4: Register the thirty-five settings with vocabulary validation

**Files:**
- Modify: `settings.py`
- Modify: `release_tags.py` (fill the `language` vocabulary)
- Test: `tests/test_filter_rules.py`

**Interfaces:**
- Consumes: `release_tags.CATEGORIES`, `release_tags.VALUES_BY_CATEGORY`.
- Produces: 35 registered settings; `settings.set()` rejecting values outside a
  category's vocabulary.

Naming matters here. `SOURCE_*` is used, never `QUALITY_*`, because
`QUALITY_PREFERENCE` already exists and holds a **resolution**. A
`QUALITY_PREFERRED` two characters away from it, meaning something different,
is a defect waiting to be filed.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_filter_rules.py
import os, sys
os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import release_tags as rt
import settings as _s

STATES = ("PREFERRED", "EXCLUDED", "REQUIRED", "INCLUDED")
PREFIXES = ("RESOLUTION", "SOURCE", "ENCODE", "VISUAL_TAG",
            "AUDIO_TAG", "AUDIO_CHANNELS", "LANGUAGE")


def test_all_thirty_five_settings_are_registered():
    for prefix in PREFIXES:
        for state in STATES:
            key = f"{prefix}_{state}"
            assert key in _s._LIST_KEYS, f"{key} missing from _LIST_KEYS"
        assert f"{prefix}_STRICT" in _s._BOOL_KEYS, f"{prefix}_STRICT missing"
    total = len(PREFIXES) * len(STATES) + len(PREFIXES)
    assert total == 35


def test_every_registered_key_appears_in_a_settings_group():
    grouped = {k for g in _s.SETTING_GROUPS for k in g["keys"]}
    for prefix in PREFIXES:
        for state in STATES:
            assert f"{prefix}_{state}" in grouped, f"{prefix}_{state} not in any group"
        assert f"{prefix}_STRICT" in grouped


def test_no_quality_prefixed_rule_key_exists():
    """QUALITY_PREFERENCE already exists and means resolution. A QUALITY_PREFERRED
    two characters away from it, meaning source type, is a trap."""
    for state in STATES:
        assert f"QUALITY_{state}" not in _s._LIST_KEYS


def test_setting_an_unknown_value_is_rejected(monkeypatch):
    stored = {}
    monkeypatch.setattr(_s.db, "set_setting", lambda k, v: stored.__setitem__(k, v))
    with pytest.raises(ValueError) as exc:
        _s.set("RESOLUTION_EXCLUDED", ["1081p"])
    assert "1081p" in str(exc.value)
    assert stored == {}


def test_setting_a_known_value_is_accepted(monkeypatch):
    stored = {}
    monkeypatch.setattr(_s.db, "set_setting", lambda k, v: stored.__setitem__(k, v))
    _s.set("RESOLUTION_EXCLUDED", ["480p"])
    assert stored["RESOLUTION_EXCLUDED"] == "480p"


def test_unknown_is_a_settable_value_in_every_category():
    """Excluding 'unknown' is how a user asks for positively-tagged releases only."""
    for category in rt.CATEGORIES:
        assert rt.UNKNOWN in rt.VALUES_BY_CATEGORY[category], category
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/test_filter_rules.py -q`
Expected: FAIL with `AssertionError: RESOLUTION_PREFERRED missing from _LIST_KEYS`

- [ ] **Step 3: Write minimal implementation**

In `release_tags.py`, replace the placeholder language vocabulary. Import is
done lazily inside a function to avoid the cycle:

```python
def _language_values() -> tuple[str, ...]:
    from streams import LANGUAGE_CODES
    return tuple(LANGUAGE_CODES) + (UNKNOWN,)


def language_values() -> tuple[str, ...]:
    """Resolved lazily because streams imports release_tags indirectly."""
    if not VALUES_BY_CATEGORY["language"]:
        VALUES_BY_CATEGORY["language"] = _language_values()
    return VALUES_BY_CATEGORY["language"]
```

In `settings.py`, after the existing `_LIST_KEYS` definition:

```python
import release_tags as _rt

_RULE_PREFIX_BY_CATEGORY = {
    "resolution": "RESOLUTION",
    "source": "SOURCE",
    "encode": "ENCODE",
    "visual_tag": "VISUAL_TAG",
    "audio_tag": "AUDIO_TAG",
    "audio_channels": "AUDIO_CHANNELS",
    "language": "LANGUAGE",
}
_RULE_STATES = ("PREFERRED", "EXCLUDED", "REQUIRED", "INCLUDED")

# key -> category, used by set() to validate each value against that
# category's vocabulary, the same way _LANGUAGE_LIST_KEYS works.
_RULE_LIST_KEYS: dict[str, str] = {
    f"{prefix}_{state}": category
    for category, prefix in _RULE_PREFIX_BY_CATEGORY.items()
    for state in _RULE_STATES
}
_RULE_STRICT_KEYS = {f"{p}_STRICT" for p in _RULE_PREFIX_BY_CATEGORY.values()}

_LIST_KEYS |= set(_RULE_LIST_KEYS)
_BOOL_KEYS |= _RULE_STRICT_KEYS
```

Add validation inside `settings.set()`, immediately after the existing
`_LANGUAGE_LIST_KEYS` block:

```python
    if key in _RULE_LIST_KEYS:
        category = _RULE_LIST_KEYS[key]
        vocabulary = (_rt.language_values() if category == "language"
                      else _rt.VALUES_BY_CATEGORY[category])
        values = [v.strip().lower() for v in
                  (value if isinstance(value, list) else str(value).split(","))
                  if str(v).strip()]
        unknown = [v for v in values if v not in vocabulary]
        if unknown:
            raise ValueError(
                f"{key} has value(s) not valid for {category}: {unknown}. "
                f"Valid values are {list(vocabulary)}"
            )
        value = values
```

Add a settings group so the keys render. Insert into `SETTING_GROUPS` after the
existing quality group:

```python
    {
        "id": "filter_rules",
        "title": "Filtering rules",
        "keys": [k for k in _RULE_LIST_KEYS] + sorted(_RULE_STRICT_KEYS),
    },
```

- [ ] **Step 4: Run test to verify it passes**

Run: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/test_filter_rules.py -q`
Expected: PASS, 6 tests

- [ ] **Step 5: Confirm the whole suite still passes**

Run: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/ -q`
Expected: PASS. Four existing test files call `sys.modules.pop("settings")`, so a
new import at settings module scope can break them. If any fail, move the
`import release_tags as _rt` to the top of `settings.py` above all other imports
and re-run.

- [ ] **Step 6: Commit**

```bash
git add settings.py release_tags.py tests/test_filter_rules.py
git commit -m "feat(settings): register 35 filter-rule keys with vocabulary validation"
```

- [ ] **Step 7: Report the .env.example keys**

Do **not** edit `.env.example`; it is under a permission deny rule. List all 35
key names in the task report so a human can add them.

---

### Task 5: The Verdict type and the four-state evaluation engine

**Files:**
- Create: `filter_rules.py`
- Test: `tests/test_filter_rules.py`

**Interfaces:**
- Consumes: `release_tags.detect_all`, `release_tags.CATEGORIES`,
  `settings.get`.
- Produces: `Verdict` dataclass with fields
  `kept: bool, rule: str | None, value: str | None, relaxed: bool`;
  `evaluate(tagged: list[dict[str, tuple[str, ...]]], rules: dict) -> list[Verdict]`;
  `load_rules() -> dict[str, dict[str, list[str]]]`.

This is the task the whole plan exists for. Two properties must hold, and both
are tested here rather than assumed:

1. **Order independence.** Each category is evaluated against the full pool, and
   the drops are applied together. Evaluating source before resolution must give
   the same survivors as the reverse.
2. **Nothing is discarded silently.** Every candidate gets a `Verdict`, including
   the ones that survive.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_filter_rules.py
import filter_rules as fr


def _rules(**kw):
    """Every category empty unless named. Mirrors an untouched install."""
    base = {c: {"preferred": [], "excluded": [], "required": [], "included": [],
                "strict": False}
            for c in rt.CATEGORIES}
    for category, states in kw.items():
        base[category].update(states)
    return base


def _tag(name, languages=()):
    return rt.detect_all(name, languages)


def test_every_candidate_gets_a_verdict_including_survivors():
    tagged = [_tag("Movie.1080p.WEB-DL.x264"), _tag("Movie.1080p.HDCAM.x264")]
    verdicts = fr.evaluate(tagged, _rules(source={"excluded": ["cam"]}))
    assert len(verdicts) == 2
    assert verdicts[0].kept is True
    assert verdicts[1].kept is False


def test_a_drop_names_the_rule_and_the_value():
    tagged = [_tag("Movie.1080p.WEB-DL.x264"), _tag("Movie.1080p.HDCAM.x264")]
    verdicts = fr.evaluate(tagged, _rules(source={"excluded": ["cam"]}))
    assert verdicts[1].rule == "SOURCE_EXCLUDED"
    assert verdicts[1].value == "cam"


def test_evaluation_is_order_independent(monkeypatch):
    """Each category sees the full pool, so no category can shrink the pool
    another category then evaluates against."""
    tagged = [
        _tag("Movie.2160p.BluRay.REMUX.x265"),
        _tag("Movie.1080p.WEB-DL.x264"),
        _tag("Movie.720p.HDCAM.x264"),
    ]
    rules = _rules(source={"excluded": ["remux", "cam"]},
                   resolution={"excluded": ["720p"]})
    forward = fr.evaluate(tagged, rules)

    # evaluate() iterates rt.CATEGORIES, so the evaluation order lives THERE,
    # not in the rules dict. Reversing the dict would change nothing and the
    # test would pass against a sequential implementation too.
    monkeypatch.setattr(fr.rt, "CATEGORIES", tuple(reversed(rt.CATEGORIES)))
    backward = fr.evaluate(tagged, rules)

    assert [v.kept for v in forward] == [v.kept for v in backward]
    assert [v.kept for v in forward] == [False, True, False]


def test_required_does_not_drop_unknown():
    """Absence of data is not evidence of absence. Zilean supplies no language
    at all, so a required-language rule must not delete every Zilean result."""
    tagged = [_tag("Movie.1080p.WEB-DL.x264", ()),          # language unknown
              _tag("Movie.1080p.WEB-DL.FRENCH.x264", ("fr",))]
    verdicts = fr.evaluate(tagged, _rules(language={"required": ["en"]}))
    assert verdicts[0].kept is True, "unknown must survive a required rule"
    assert verdicts[1].kept is False, "a positively non-matching value is dropped"


def test_unknown_can_be_excluded_explicitly():
    tagged = [_tag("Movie.1080p.WEB-DL.x264", ())]
    verdicts = fr.evaluate(tagged, _rules(language={"excluded": [rt.UNKNOWN]}))
    assert verdicts[0].kept is False
    assert verdicts[0].rule == "LANGUAGE_EXCLUDED"


def test_included_rescues_across_categories_and_short_circuits():
    tagged = [_tag("Movie.1080p.HDCAM.Atmos.x264")]
    rules = _rules(source={"excluded": ["cam"]}, audio_tag={"included": ["atmos"]})
    verdicts = fr.evaluate(tagged, rules)
    assert verdicts[0].kept is True
    assert verdicts[0].rule == "AUDIO_TAG_INCLUDED"


def test_preferred_never_filters():
    tagged = [_tag("Movie.1080p.WEBRip.x264")]
    verdicts = fr.evaluate(tagged, _rules(source={"preferred": ["webdl"]}))
    assert verdicts[0].kept is True


def test_a_rule_that_would_empty_the_pool_relaxes_and_says_so():
    tagged = [_tag("Movie.1080p.HDCAM.x264"), _tag("Movie.720p.HDCAM.x264")]
    verdicts = fr.evaluate(tagged, _rules(source={"excluded": ["cam"]}))
    assert all(v.kept for v in verdicts), "soft by default"
    assert all(v.relaxed for v in verdicts), "relaxation must be recorded"


def test_strict_holds_even_when_it_empties_the_pool():
    tagged = [_tag("Movie.1080p.HDCAM.x264")]
    rules = _rules(source={"excluded": ["cam"], "strict": True})
    verdicts = fr.evaluate(tagged, rules)
    assert verdicts[0].kept is False
    assert verdicts[0].relaxed is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/test_filter_rules.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'filter_rules'`

- [ ] **Step 3: Write minimal implementation**

```python
# filter_rules.py
"""The four-state filter model.

Every category is evaluated against the full candidate pool, independently, and
the resulting drops are applied together. That is what makes the outcome
independent of category order, unlike the sequential chain it replaces, where
each filter rebound the candidate list before the next one ran.
"""
import logging
from dataclasses import dataclass

import release_tags as rt
import settings as _settings

log = logging.getLogger(__name__)

_STATES = ("preferred", "excluded", "required", "included")

_PREFIX_BY_CATEGORY = {
    "resolution": "RESOLUTION",
    "source": "SOURCE",
    "encode": "ENCODE",
    "visual_tag": "VISUAL_TAG",
    "audio_tag": "AUDIO_TAG",
    "audio_channels": "AUDIO_CHANNELS",
    "language": "LANGUAGE",
}


@dataclass(frozen=True)
class Verdict:
    kept: bool
    rule: str | None = None      # "SOURCE_EXCLUDED", "AUDIO_TAG_INCLUDED", ...
    value: str | None = None     # the value that matched
    relaxed: bool = False        # this rule self-disabled to avoid an empty pool


def load_rules() -> dict[str, dict]:
    """Read the 35 settings into the nested shape evaluate() expects."""
    rules = {}
    for category, prefix in _PREFIX_BY_CATEGORY.items():
        rules[category] = {
            state: [v.strip().lower()
                    for v in (_settings.get(f"{prefix}_{state.upper()}", []) or [])]
            for state in _STATES
        }
        rules[category]["strict"] = bool(_settings.get(f"{prefix}_STRICT", False))
    return rules


def _included_match(tags: dict, rules: dict) -> tuple[str, str] | None:
    """Included is checked first, across every category, and short-circuits.

    It is deliberately powerful: marking atmos as included will keep a cam rip
    that happens to carry Atmos. The UI must say so at the point of choosing.
    """
    for category in rt.CATEGORIES:
        included = rules.get(category, {}).get("included") or []
        for value in tags.get(category, ()):
            if value in included:
                return f"{_PREFIX_BY_CATEGORY[category]}_INCLUDED", value
    return None


def _category_drop(tags: dict, category: str, rules: dict) -> tuple[str, str] | None:
    """Return the rule and value that would drop this candidate, or None.

    A required rule never drops an UNKNOWN. "The release did not say" is not
    "the release does not match", and treating it as a mismatch would delete
    every result from a source that cannot supply this category at all.
    """
    prefix = _PREFIX_BY_CATEGORY[category]
    values = tags.get(category, ())
    spec = rules.get(category, {})

    required = spec.get("required") or []
    if required and not any(v in required for v in values):
        if rt.UNKNOWN not in values:
            return f"{prefix}_REQUIRED", ",".join(values) or rt.UNKNOWN

    excluded = spec.get("excluded") or []
    for value in values:
        if value in excluded:
            return f"{prefix}_EXCLUDED", value
    return None


def evaluate(tagged: list[dict], rules: dict) -> list[Verdict]:
    """One Verdict per candidate, in input order. Nothing is discarded silently."""
    if not tagged:
        return []

    # Included first, across all categories. A rescued candidate skips everything.
    rescued: dict[int, tuple[str, str]] = {}
    for i, tags in enumerate(tagged):
        hit = _included_match(tags, rules)
        if hit:
            rescued[i] = hit

    # Each category votes against the FULL pool. No category sees a pool that
    # another category has already shrunk.
    drops: dict[int, tuple[str, str]] = {}
    relaxed_categories: set[str] = set()
    for category in rt.CATEGORIES:
        spec = rules.get(category, {})
        category_drops = {}
        for i, tags in enumerate(tagged):
            if i in rescued:
                continue
            hit = _category_drop(tags, category, rules)
            if hit:
                category_drops[i] = hit
        survivors = len(tagged) - len(rescued) - len(category_drops)
        if survivors == 0 and category_drops and not spec.get("strict"):
            relaxed_categories.add(category)
            log.info("Filter %s would drop every candidate; relaxing it",
                     _PREFIX_BY_CATEGORY[category])
            continue
        drops.update(category_drops)

    verdicts = []
    for i in range(len(tagged)):
        if i in rescued:
            rule, value = rescued[i]
            verdicts.append(Verdict(kept=True, rule=rule, value=value))
        elif i in drops:
            rule, value = drops[i]
            verdicts.append(Verdict(kept=False, rule=rule, value=value))
        else:
            verdicts.append(Verdict(kept=True, relaxed=bool(relaxed_categories)))
    return verdicts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/test_filter_rules.py -q`
Expected: PASS, 15 tests

- [ ] **Step 5: Verify the order-independence test has teeth**

Rewrite `evaluate` so each category filters the surviving pool sequentially
(`tagged = [t for i, t in enumerate(tagged) if i not in category_drops]`),
confirm the mutation landed, clear caches, and re-run. `test_evaluation_is_order_independent`
must FAIL. Restore the correct implementation and confirm green. Without this
step the plan's central claim is untested.

- [ ] **Step 6: Commit**

```bash
git add filter_rules.py tests/test_filter_rules.py
git commit -m "feat(filters): four-state rule engine with per-candidate verdicts"
```

---

### Task 6: Source capability map

**Files:**
- Modify: `zilean.py`, `torrentio.py`, `debridio.py`, `filter_rules.py`
- Test: `tests/test_filter_rules.py`

**Interfaces:**
- Consumes: `release_tags.CATEGORIES`.
- Produces: `CAPABILITIES: frozenset[str]` in each scraper module;
  `filter_rules.warn_unsupported_requirements(rules, sources) -> list[str]`.

Zilean's payload carries no language data at all, which is why
`zilean.LANGUAGES_AVAILABLE` exists as a one-off today. Generalise it so a
`REQUIRED` rule naming a category a contributing source cannot populate is
visible rather than silent.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_filter_rules.py

def test_each_scraper_declares_its_capabilities():
    import debridio, torrentio, zilean
    for module in (debridio, torrentio, zilean):
        assert isinstance(module.CAPABILITIES, frozenset), module.__name__
        assert module.CAPABILITIES <= set(rt.CATEGORIES), module.__name__


def test_zilean_cannot_supply_language():
    import zilean
    assert "language" not in zilean.CAPABILITIES
    assert zilean.LANGUAGES_AVAILABLE is False


def test_required_rule_on_an_unsupported_category_is_warned_about():
    warnings = fr.warn_unsupported_requirements(
        _rules(language={"required": ["en"]}), ["zilean", "torrentio"])
    assert len(warnings) == 1
    assert "zilean" in warnings[0]
    assert "language" in warnings[0]


def test_no_warning_when_every_source_supports_the_category():
    warnings = fr.warn_unsupported_requirements(
        _rules(language={"required": ["en"]}), ["torrentio", "debridio"])
    assert warnings == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/test_filter_rules.py -q`
Expected: FAIL with `AttributeError: module 'zilean' has no attribute 'CAPABILITIES'`

- [ ] **Step 3: Write minimal implementation**

In `zilean.py`, beside the existing `LANGUAGES_AVAILABLE = False`:

```python
# Zilean's payload carries resolution and source tokens in the release title,
# and nothing else. Kept beside LANGUAGES_AVAILABLE, which it generalises.
CAPABILITIES = frozenset({"resolution", "source", "encode"})
```

In `torrentio.py` and `debridio.py`, near the top after the imports:

```python
# Every category is detectable from the release title this scraper returns.
CAPABILITIES = frozenset({
    "resolution", "source", "encode", "visual_tag",
    "audio_tag", "audio_channels", "language",
})
```

In `filter_rules.py`:

```python
def warn_unsupported_requirements(rules: dict, sources: list[str]) -> list[str]:
    """A required rule on a category a source cannot populate silently discards
    every result from that source. Surface it instead."""
    import importlib

    messages = []
    for category in rt.CATEGORIES:
        if not (rules.get(category, {}).get("required") or []):
            continue
        for source in sources:
            try:
                module = importlib.import_module(source)
            except ImportError:
                continue
            capabilities = getattr(module, "CAPABILITIES", None)
            if capabilities is not None and category not in capabilities:
                messages.append(
                    f"{_PREFIX_BY_CATEGORY[category]}_REQUIRED is set, but "
                    f"{source} cannot supply {category}; its results rely on the "
                    f"unknown-passes rule"
                )
    return messages
```

- [ ] **Step 4: Run test to verify it passes**

Run: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/test_filter_rules.py -q`
Expected: PASS, 19 tests

- [ ] **Step 5: Commit**

```bash
git add zilean.py torrentio.py debridio.py filter_rules.py tests/test_filter_rules.py
git commit -m "feat(filters): per-scraper capability map replacing the LANGUAGES_AVAILABLE one-off"
```

---

### Task 7: Wire the engine into rank_streams, keeping the existing signature

**Files:**
- Modify: `streams.py`
- Test: `tests/test_filter_rules.py`

**Interfaces:**
- Consumes: `filter_rules.evaluate`, `filter_rules.load_rules`,
  `filter_rules.Verdict`, `release_tags.detect_all`.
- Produces: `streams.rank_streams(streams, prefer_season_pack=False,
  override=None) -> list[Stream]` (unchanged signature);
  `streams.rank_streams_explained(...) -> tuple[list[Stream], list[Verdict]]`.

The two existing call sites, `torrentio.py:110` and `scrapers.py:150`, must not
change. `rank_streams` becomes a thin wrapper that discards the verdicts.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_filter_rules.py
import streams


def test_rank_streams_signature_is_unchanged(monkeypatch):
    monkeypatch.setattr(_s, "get", lambda k, d=None: d)
    out = streams.rank_streams([
        streams.Stream(name="Movie.1080p.WEB-DL.x264", title="Movie.1080p.WEB-DL.x264",
                       info_hash="a" * 40, quality="1080p", seeders=10, size_gb=5.0,
                       is_season_pack=False),
    ])
    assert isinstance(out, list)
    assert all(isinstance(s, streams.Stream) for s in out)


def test_rank_streams_explained_returns_a_verdict_per_input(monkeypatch):
    rules_seen = {}

    def fake_get(key, default=None):
        if key == "SOURCE_EXCLUDED":
            return ["cam"]
        return default
    monkeypatch.setattr(_s, "get", fake_get)

    cands = [
        streams.Stream(name="Movie.1080p.WEB-DL.x264", title="Movie.1080p.WEB-DL.x264",
                       info_hash="a" * 40, quality="1080p", seeders=10, size_gb=5.0,
                       is_season_pack=False),
        streams.Stream(name="Movie.1080p.HDCAM.x264", title="Movie.1080p.HDCAM.x264",
                       info_hash="b" * 40, quality="1080p", seeders=99, size_gb=5.0,
                       is_season_pack=False),
    ]
    kept, verdicts = streams.rank_streams_explained(cands)
    assert len(verdicts) == 2
    assert len(kept) == 1
    assert kept[0].info_hash == "a" * 40
    dropped = [v for v in verdicts if not v.kept]
    assert dropped[0].rule == "SOURCE_EXCLUDED"
    assert dropped[0].value == "cam"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/test_filter_rules.py -q`
Expected: FAIL with `AttributeError: module 'streams' has no attribute 'rank_streams_explained'`

- [ ] **Step 3: Write minimal implementation**

Replace the body of `rank_streams` in `streams.py`. The sequential filter chain
from the old `EXCLUDE_DV_P5` block through the `EXCLUDE_LANGUAGES` block is
deleted and replaced by the call to `filter_rules`. `MIN_SEEDERS`, `MAX_SIZE_GB`
and the undersized check stay where they are, because they are not categories.

```python
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
    streams: list["Stream"],
    prefer_season_pack: bool = False,
    override: dict | None = None,
) -> list["Stream"]:
    """Return streams sorted by preference. Thin wrapper over
    rank_streams_explained that discards the verdicts, so the two existing call
    sites keep working unchanged."""
    kept, _ = rank_streams_explained(streams, prefer_season_pack, override)
    return kept
```

Add the two helpers `_apply_non_category_filters` (the existing `MIN_SEEDERS`,
`MAX_SIZE_GB` and undersized blocks, moved verbatim) and `_sort_candidates` (the
existing `sort_key` closure, with `_lang_score` reading
`rules["language"]["preferred"]` instead of `AUDIO_LANGUAGE_PREFERENCE`).

- [ ] **Step 4: Run test to verify it passes**

Run: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/ -q`
Expected: PASS. Existing tests in `tests/test_languages.py` that assert ranking
order will need their `_RANK_SETTINGS` fixture updated to the new key names; do
that in this task, and keep the assertions identical so they still pin the same
behaviour.

- [ ] **Step 5: Commit**

```bash
git add streams.py tests/
git commit -m "feat(filters): route rank_streams through the rule engine, add explained variant"
```

---

### Task 8: Per-show override translation

**Files:**
- Modify: `streams.py`
- Test: `tests/test_filter_rules.py`

**Interfaces:**
- Consumes: `filter_rules.load_rules`.
- Produces: `streams._apply_show_override(rules: dict, override: dict) -> dict`.

`show_quality_override` (`db.py:168`, read by `processor.py:55` and `:62`) lets a
single show override `quality_preference`, `allow_4k` and `prefer_hevc`. Those
are three of the settings this project retires, so the table would otherwise
stop working. The table and its UI stay unchanged; the three fields are
translated per call.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_filter_rules.py

def test_show_override_replaces_resolution_preference():
    rules = _rules(resolution={"preferred": ["1080p"]})
    out = streams._apply_show_override(rules, {"quality_preference": "2160p,1080p"})
    assert out["resolution"]["preferred"] == ["2160p", "1080p"]


def test_show_override_allow_4k_false_excludes_2160p():
    out = streams._apply_show_override(_rules(), {"allow_4k": False})
    assert "2160p" in out["resolution"]["excluded"]


def test_show_override_prefer_hevc_adds_and_removes():
    on = streams._apply_show_override(_rules(), {"prefer_hevc": True})
    assert "hevc" in on["encode"]["preferred"]
    off = streams._apply_show_override(
        _rules(encode={"preferred": ["hevc"]}), {"prefer_hevc": False})
    assert "hevc" not in off["encode"]["preferred"]


def test_show_override_does_not_mutate_the_global_rules():
    base = _rules(resolution={"preferred": ["1080p"]})
    streams._apply_show_override(base, {"quality_preference": "720p"})
    assert base["resolution"]["preferred"] == ["1080p"], "global rules were mutated"


def test_empty_override_changes_nothing():
    base = _rules(resolution={"preferred": ["1080p"]})
    assert streams._apply_show_override(base, {}) == base
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/test_filter_rules.py -q`
Expected: FAIL with `AttributeError: module 'streams' has no attribute '_apply_show_override'`

- [ ] **Step 3: Write minimal implementation**

```python
# in streams.py
import copy


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/test_filter_rules.py -q`
Expected: PASS, 26 tests

- [ ] **Step 5: Commit**

```bash
git add streams.py tests/test_filter_rules.py
git commit -m "feat(filters): translate per-show overrides into the rule model"
```

---

### Task 9: Migration from the eleven retired settings

**Files:**
- Create: `migrate_filters.py`
- Modify: `app.py` (call the migration at startup)
- Test: `tests/test_filter_migration.py`

**Interfaces:**
- Consumes: `settings.get`, `settings.set`, `db.get_all_settings`.
- Produces: `migrate_filters.migrate(dry_run: bool = False) -> dict[str, list[str]]`;
  `migrate_filters.warn_stale_env() -> list[str]`.

One test per row of the spec's migration table. A migration that misreads a
setting silently changes which release a user downloads, which is the hardest
class of bug to notice, so each row is pinned individually.

`EXCLUDE_BLURAY` maps to three values now that `bluray`, `bdrip` and `brrip` are
distinct, and it no longer sweeps up remuxes. `STRICT_NO_CAM` maps only to
`SOURCE_STRICT`; its accidental control of the undersized check moves to the new
`EXCLUDE_UNDERSIZED_STRICT`, defaulting to `false` to match today's effective
behaviour.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_filter_migration.py
import os, sys
os.environ.setdefault("TORBOX_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import migrate_filters


@pytest.fixture
def store(monkeypatch):
    written = {}
    import settings as _s
    monkeypatch.setattr(_s, "set", lambda k, v: written.__setitem__(k, v))
    return written


def _old(monkeypatch, **values):
    import settings as _s
    monkeypatch.setattr(_s, "get", lambda k, d=None: values.get(k, d))


def test_quality_preference_becomes_resolution_preferred(monkeypatch, store):
    _old(monkeypatch, QUALITY_PREFERENCE=["1080p", "2160p", "720p"])
    migrate_filters.migrate()
    assert store["RESOLUTION_PREFERRED"] == ["1080p", "2160p", "720p"]


def test_quality_preference_does_not_become_a_source_rule(monkeypatch, store):
    """QUALITY_PREFERENCE holds a resolution despite its name. Reading it as a
    source preference would silently change every user's picks."""
    _old(monkeypatch, QUALITY_PREFERENCE=["1080p"])
    migrate_filters.migrate()
    assert "SOURCE_PREFERRED" not in store or store["SOURCE_PREFERRED"] == []


def test_allow_4k_false_excludes_2160p(monkeypatch, store):
    _old(monkeypatch, ALLOW_4K=False)
    migrate_filters.migrate()
    assert "2160p" in store["RESOLUTION_EXCLUDED"]


def test_exclude_bluray_no_longer_sweeps_up_remux(monkeypatch, store):
    _old(monkeypatch, EXCLUDE_BLURAY=True, EXCLUDE_REMUX=False)
    migrate_filters.migrate()
    excluded = store["SOURCE_EXCLUDED"]
    assert {"bluray", "bdrip", "brrip"} <= set(excluded)
    assert "remux" not in excluded


def test_exclude_cam_maps_to_every_cam_family_value(monkeypatch, store):
    _old(monkeypatch, EXCLUDE_CAM=True)
    migrate_filters.migrate()
    assert {"cam", "ts", "tc", "scr", "r5"} <= set(store["SOURCE_EXCLUDED"])


def test_strict_no_cam_maps_only_to_source_strict(monkeypatch, store):
    """It must not also make the undersized check hard; that coupling was a bug."""
    _old(monkeypatch, STRICT_NO_CAM=True)
    migrate_filters.migrate()
    assert store["SOURCE_STRICT"] is True
    assert store.get("EXCLUDE_UNDERSIZED_STRICT", False) is False


def test_prefer_webdl_and_hevc(monkeypatch, store):
    _old(monkeypatch, PREFER_WEBDL=True, PREFER_HEVC=True)
    migrate_filters.migrate()
    assert "webdl" in store["SOURCE_PREFERRED"]
    assert "hevc" in store["ENCODE_PREFERRED"]


def test_exclude_dv_p5_becomes_dv_only(monkeypatch, store):
    _old(monkeypatch, EXCLUDE_DV_P5=True)
    migrate_filters.migrate()
    assert "dv_only" in store["VISUAL_TAG_EXCLUDED"]


def test_language_settings_migrate_in_order(monkeypatch, store):
    _old(monkeypatch, AUDIO_LANGUAGE_PREFERENCE=["en", "multi"],
         EXCLUDE_LANGUAGES=["ru"])
    migrate_filters.migrate()
    assert store["LANGUAGE_PREFERRED"] == ["en", "multi"]
    assert store["LANGUAGE_EXCLUDED"] == ["ru"]


def test_dry_run_writes_nothing(monkeypatch, store):
    _old(monkeypatch, EXCLUDE_CAM=True)
    result = migrate_filters.migrate(dry_run=True)
    assert store == {}
    assert "SOURCE_EXCLUDED" in result


def test_stale_env_keys_are_reported(monkeypatch):
    import config
    monkeypatch.setattr(config, "QUALITY_PREFERENCE", ["1080p"], raising=False)
    messages = migrate_filters.warn_stale_env()
    assert any("QUALITY_PREFERENCE" in m for m in messages)
    assert any("RESOLUTION_PREFERRED" in m for m in messages)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/test_filter_migration.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'migrate_filters'`

- [ ] **Step 3: Write minimal implementation**

```python
# migrate_filters.py
"""One-shot translation of the retired boolean filters into the rule model.

Run once at startup. Idempotent: a second run overwrites the same rows with the
same values, so a partial first run is safe to repeat.
"""
import logging

import config
import settings as _settings

log = logging.getLogger(__name__)

CAM_FAMILY = ["cam", "ts", "tc", "scr", "r5", "ppvrip"]
BLURAY_FAMILY = ["bluray", "bdrip", "brrip"]

# Retired key -> the key that replaces it, for the stale-.env warning.
RETIRED = {
    "QUALITY_PREFERENCE": "RESOLUTION_PREFERRED",
    "ALLOW_4K": "RESOLUTION_EXCLUDED",
    "EXCLUDE_REMUX": "SOURCE_EXCLUDED",
    "EXCLUDE_BLURAY": "SOURCE_EXCLUDED",
    "EXCLUDE_CAM": "SOURCE_EXCLUDED",
    "STRICT_NO_CAM": "SOURCE_STRICT",
    "EXCLUDE_DV_P5": "VISUAL_TAG_EXCLUDED",
    "PREFER_WEBDL": "SOURCE_PREFERRED",
    "PREFER_HEVC": "ENCODE_PREFERRED",
    "AUDIO_LANGUAGE_PREFERENCE": "LANGUAGE_PREFERRED",
    "EXCLUDE_LANGUAGES": "LANGUAGE_EXCLUDED",
}


def migrate(dry_run: bool = False) -> dict:
    """Translate the eleven retired settings. Returns what was written."""
    out: dict = {}

    resolution_preferred = list(_settings.get("QUALITY_PREFERENCE", []) or [])
    if resolution_preferred:
        out["RESOLUTION_PREFERRED"] = resolution_preferred

    resolution_excluded = []
    if _settings.get("ALLOW_4K", True) is False:
        resolution_excluded.append("2160p")
    if resolution_excluded:
        out["RESOLUTION_EXCLUDED"] = resolution_excluded

    source_excluded = []
    if _settings.get("EXCLUDE_REMUX", False):
        source_excluded.append("remux")
    if _settings.get("EXCLUDE_BLURAY", False):
        source_excluded.extend(BLURAY_FAMILY)
    if _settings.get("EXCLUDE_CAM", False):
        source_excluded.extend(CAM_FAMILY)
    if source_excluded:
        out["SOURCE_EXCLUDED"] = source_excluded

    if _settings.get("PREFER_WEBDL", False):
        out["SOURCE_PREFERRED"] = ["webdl"]
    if _settings.get("PREFER_HEVC", False):
        out["ENCODE_PREFERRED"] = ["hevc"]
    if _settings.get("EXCLUDE_DV_P5", False):
        out["VISUAL_TAG_EXCLUDED"] = ["dv_only"]

    if _settings.get("STRICT_NO_CAM", False):
        out["SOURCE_STRICT"] = True

    language_preferred = list(_settings.get("AUDIO_LANGUAGE_PREFERENCE", []) or [])
    if language_preferred:
        out["LANGUAGE_PREFERRED"] = language_preferred
    language_excluded = list(_settings.get("EXCLUDE_LANGUAGES", []) or [])
    if language_excluded:
        out["LANGUAGE_EXCLUDED"] = language_excluded

    if not dry_run:
        for key, value in out.items():
            _settings.set(key, value)
        log.info("Filter migration wrote %d rule row(s)", len(out))
    return out


def warn_stale_env() -> list[str]:
    """A retired key left in .env is silently inert after upgrade. Say so."""
    messages = []
    for old, new in RETIRED.items():
        if hasattr(config, old) and getattr(config, old) not in (None, "", [], False):
            messages.append(
                f"{old} in your .env is no longer read; it was replaced by {new}. "
                f"Remove it to silence this warning."
            )
    for message in messages:
        log.warning("%s", message)
    return messages
```

In `app.py`, immediately after the settings module is importable at startup:

```python
import migrate_filters
migrate_filters.migrate()
migrate_filters.warn_stale_env()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/test_filter_migration.py -q`
Expected: PASS, 11 tests

- [ ] **Step 5: Run the full suite**

Run: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/ -q`
Expected: PASS, all tests

- [ ] **Step 6: Commit**

```bash
git add migrate_filters.py app.py tests/test_filter_migration.py
git commit -m "feat(filters): migrate the eleven retired settings, warn on stale .env keys"
```

---

### Task 10: Break the STRICT_NO_CAM coupling

**Files:**
- Modify: `streams.py`, `settings.py`, `config.py`
- Test: `tests/test_filter_rules.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `EXCLUDE_UNDERSIZED_STRICT` setting, default `False`.

`STRICT_NO_CAM` currently hard-fails two unrelated things: the cam filter and the
undersized-release check. A setting named for cam rips should not decide whether
a size heuristic is fatal. `SOURCE_STRICT` inherits the cam half only.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/test_filter_rules.py

def test_source_strict_does_not_make_the_size_check_fatal(monkeypatch):
    """STRICT_NO_CAM used to hard-fail the undersized check too. That coupling
    is a bug and must not survive the migration."""
    def fake_get(key, default=None):
        return {"SOURCE_STRICT": True,
                "EXCLUDE_UNDERSIZED_RELEASES": True,
                "EXCLUDE_UNDERSIZED_STRICT": False}.get(key, default)
    monkeypatch.setattr(_s, "get", fake_get)

    tiny = streams.Stream(name="Movie.1080p.WEB-DL.x264", title="Movie.1080p.WEB-DL.x264",
                          info_hash="c" * 40, quality="1080p", seeders=10, size_gb=0.05,
                          is_season_pack=False)
    kept, _ = streams.rank_streams_explained([tiny], override={"runtime_minutes": 120})
    assert kept, "the size check must relax, not hard-fail, under SOURCE_STRICT"


def test_undersized_strict_makes_the_size_check_fatal(monkeypatch):
    def fake_get(key, default=None):
        return {"EXCLUDE_UNDERSIZED_RELEASES": True,
                "EXCLUDE_UNDERSIZED_STRICT": True}.get(key, default)
    monkeypatch.setattr(_s, "get", fake_get)

    tiny = streams.Stream(name="Movie.1080p.WEB-DL.x264", title="Movie.1080p.WEB-DL.x264",
                          info_hash="d" * 40, quality="1080p", seeders=10, size_gb=0.05,
                          is_season_pack=False)
    kept, _ = streams.rank_streams_explained([tiny], override={"runtime_minutes": 120})
    assert kept == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/test_filter_rules.py -q`
Expected: FAIL, because `_apply_non_category_filters` still reads `strict_cam`
for the undersized branch.

- [ ] **Step 3: Write minimal implementation**

In `config.py`, beside the existing `EXCLUDE_UNDERSIZED_RELEASES`:

```python
EXCLUDE_UNDERSIZED_STRICT = _env("EXCLUDE_UNDERSIZED_STRICT", "false").lower() in ("1", "true", "yes")
```

In `settings.py`, add `"EXCLUDE_UNDERSIZED_STRICT"` to `_BOOL_KEYS` and to the
group that already holds `EXCLUDE_UNDERSIZED_RELEASES`.

In `streams.py`, inside `_apply_non_category_filters`, replace the
`elif strict_cam:` branch:

```python
        # Previously governed by STRICT_NO_CAM, which had nothing to do with
        # release size. Now it has its own toggle.
        elif _settings.get("EXCLUDE_UNDERSIZED_STRICT", False):
            log.warning("Only implausibly small candidates available and "
                        "EXCLUDE_UNDERSIZED_STRICT is on; rejecting all")
            return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/ -q`
Expected: PASS, all tests

- [ ] **Step 5: Commit**

```bash
git add streams.py settings.py config.py tests/test_filter_rules.py
git commit -m "fix(filters): give the undersized check its own strict toggle"
```

- [ ] **Step 6: Report the .env.example key**

`EXCLUDE_UNDERSIZED_STRICT=false` needs adding to `.env.example` by a human.

---

### Task 11: Documentation and cleanup

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `CHANGELOG.md`
- Delete: the dead regexes in `streams.py`

**Interfaces:**
- Consumes: everything.
- Produces: no code interface.

- [ ] **Step 1: Remove the superseded regexes**

Delete `_REMUX_RE`, `_BLURAY_RE`, `_CAM_RE`, `_WEBDL_RE`, `_HEVC_RE`, `_DV_RE`
and `_QUALITY_PATTERNS` from `streams.py`. Confirm nothing references them:

```bash
grep -rnE "_REMUX_RE|_BLURAY_RE|_CAM_RE|_WEBDL_RE|_HEVC_RE|_DV_RE|_QUALITY_PATTERNS" \
  --exclude-dir=.git --exclude-dir=.venv-sdd .
```
Expected: no hits outside `release_tags.py`. Note `torrentio.py` imports
`_QUALITY_PATTERNS` from `streams`, so that import must move to
`release_tags.detect_resolution`.

- [ ] **Step 2: Run the full suite**

Run: `TORBOX_API_KEY=test ./.venv-sdd/bin/python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 3: Update the CHANGELOG**

Add an `## [Unreleased]` entry covering: the four-state model, the thirty-five
settings, order-independent evaluation, drop-reason verdicts, the
`bluray`/`remux` overlap fix, the `STRICT_NO_CAM` decoupling, and the one
behaviour change where `EXCLUDE_LANGUAGES` loses its undocumented rescue.

Also correct the 0.6.6 entry, which claims a default of
`AUDIO_LANGUAGE_PREFERENCE=en,multi`. The shipped default is empty, so language
contributed nothing to ranking on a default install and the Debridio suppression
described there only affected users who had set a language preference.

- [ ] **Step 4: Update README and CLAUDE.md**

Replace the "Kwaliteitsfilters (torrentio.py)" section of `CLAUDE.md` and the
settings table in `README.md` with the new model. Document that `preferred`
never rescues and that `included` overrides every category.

- [ ] **Step 5: Commit**

```bash
git add streams.py torrentio.py README.md CLAUDE.md CHANGELOG.md
git commit -m "docs(filters): document the rule model, drop superseded regexes"
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: four states and evaluation
(5), categories and tag parsing (1, 2, 3), unknown handling (3, 5), storage
(4), sorting (7), explainability (5, 7), capability map (6), migration (9),
per-show overrides (8), the STRICT_NO_CAM coupling (10), setting names (4),
stale `.env` (9). The C2 section is deliberately unimplemented.

**Placeholder scan.** No TBD, TODO, or "add error handling" steps. Every code
step carries the code.

**Type consistency.** `Verdict(kept, rule, value, relaxed)` is defined in Task 5
and used with those field names in Tasks 5, 6, 7 and 10. `detect_all(text,
languages) -> dict[str, tuple[str, ...]]` is defined in Task 3 and consumed in
Tasks 5 and 7. `CATEGORIES` is defined in Task 3 and used in Tasks 4, 5 and 6.
`_apply_show_override(rules, override) -> dict` is defined in Task 8 and called
in Task 7, so Task 7 must land a stub returning `rules` unchanged if executed
first; the task order avoids this.

**Known ordering constraint.** Task 7 calls `_apply_show_override` and
`_apply_non_category_filters`. Execute Tasks 5 and 6 before 7, and 8 immediately
after 7.
